"""PDF ingestion, retrieval, MinerU upgrade, and Ollama generation for MatchPDF.

Fast-load: chi dung pypdf + TF-IDF o startup, Ollama/embedding lazy.
Khong Ollama van chay duoc (tra loi trich doan + citation).
"""
import json
import math
import os
import re
import threading
import time
from pathlib import Path

import requests
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from llm.latex_norm import normalize_latex
from llm.ocr import extract_pages

try:
    from llm.src.run_mineru import find_content_list, find_mineru_outputs, run_mineru
    from llm.src.structured import load_raw, normalize_blocks
    from llm.src.build_docx import md_to_docx, prepare_work_md
    from llm.latex_norm import fix_vni, normalize_math_in_text
except ImportError:  # fallback khi chay tu thu muc llm/
    from src.run_mineru import find_content_list, find_mineru_outputs, run_mineru  # type: ignore
    from src.structured import load_raw, normalize_blocks  # type: ignore
    from src.build_docx import md_to_docx, prepare_work_md  # type: ignore
    from latex_norm import fix_vni, normalize_math_in_text  # type: ignore

TOP_K = 5
MAX_CHARS = 1500
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:0.6b")
ALLOWED_MODELS = set(os.getenv(
    "OLLAMA_ALLOWED_MODELS", "qwen2.5:1.5b,qwen3:8b,qwen3:14b"
).split(","))
MINERU_LOCK = threading.Lock()
PAGE_REF = re.compile(r"(?:trang|page|tr\.)\s*(\d{1,4})", re.I)


def _safe_chunks(pages: list[str]) -> list[dict]:
    chunks = []
    for page, text in enumerate(pages, start=1):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        current = ""
        for paragraph in paragraphs:
            if current and len(current) + len(paragraph) + 2 > MAX_CHARS:
                chunks.append({"page": page, "text": current})
                current = ""
            while len(paragraph) > MAX_CHARS:
                cut = paragraph.rfind(". ", 0, MAX_CHARS)
                cut = cut + 1 if cut > 0 else MAX_CHARS
                chunks.append({"page": page, "text": paragraph[:cut].strip()})
                paragraph = paragraph[cut:].strip()
            current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append({"page": page, "text": current})
    return [chunk for chunk in chunks if len(chunk["text"]) >= 40]


def _pages_from_blocks(blocks: list[dict], page_count: int) -> list[str]:
    pages = ["" for _ in range(page_count)]
    for block in blocks:
        page = block.get("page")
        if not isinstance(page, int) or page < 1 or page > page_count:
            continue
        text = block.get("text") or ""
        if block.get("content_type") == "formula" and block.get("formula_latex"):
            text = f"$$\n{normalize_latex(block['formula_latex'])}\n$$"
        if text.strip():
            pages[page - 1] = f"{pages[page - 1]}\n\n{text.strip()}".strip()
    return pages


def _prompt(hits: list[dict], question: str, history: list[dict]) -> str:
    context = "\n\n".join(f"[trang {hit['page']}]\n{hit['text']}" for hit in hits)
    past = "\n".join(
        f"{'Nguoi dung' if item.get('role') == 'user' else 'Tro ly'}: {item.get('content', '')[:3000]}"
        for item in history[-6:]
    )
    return f"""Ban la tro ly hoi dap tai lieu hoc thuat bang tieng Viet.

QUY TAC BAT BUOC:
- Chi dung thong tin trong CONTEXT; khong du thi noi ro.
- Moi y phai co trich dan trang dang [so].
- Giu nguyen LaTeX trong $...$ hoac $$...$$; khong bia cong thuc/so lieu.
- Cau chao khong lien quan tai lieu chi dap mot cau ngan, khong trich dan.

LICH SU:
{past or '(chua co)'}

CONTEXT:
{context}

CAU HOI: {question}
TRA LOI:"""


def _fallback_answer(hits: list[dict], question: str) -> str:
    lines = [f"Cau hoi: {question}", "",
             "Tai lieu co cac doan lien quan nhat (Ollama chua chay nen tra loi trich doan):", ""]
    for i, h in enumerate(hits[:5], 1):
        snippet = h["text"][:600].replace("\n", " ")
        lines.append(f"{i}. [trang {h['page']}] {snippet}")
    lines += ["", "Bat Ollama (ollama serve + ollama pull qwen3:8b) roi bam Chat that de co cau tra loi tong hop."]
    return "\n".join(lines)


def _embed(texts: list[str]) -> list[list[float]]:
    response = requests.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts}, timeout=60)
    response.raise_for_status()
    vectors = response.json()["embeddings"]
    return [[value / max(math.sqrt(sum(item * item for item in vector)), 1e-12) for value in vector]
            for vector in vectors]


def _ollama_online() -> tuple[bool, list[str]]:
    try:
        payload = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
        return True, [m.get("name", "") for m in payload.get("models", [])]
    except requests.RequestException:
        return False, []


class MatchPdfStore:
    """One in-process store: PDFs persist to disk; indexes are rebuilt after restart."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.docs: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}  # PDF đã nhận, đang đọc chữ/embedding nền

    def begin_upload(self, doc_id: str, name: str, pdf_path: Path) -> dict:
        """Nhận PDF ngay (chỉ đếm trang); phần nặng chạy ở index_background."""
        pages = len(PdfReader(str(pdf_path)).pages)
        self.pending[doc_id] = {"name": name, "file": pdf_path, "num_pages": pages, "status": "indexing"}
        return self.pending_info(doc_id)

    def pending_info(self, doc_id: str) -> dict:
        job = self.pending[doc_id]
        return {"doc_id": doc_id, "name": job["name"], "status": job["status"], "error": job.get("error"),
                "parser": "indexing", "docx": "unavailable", "num_pages": job["num_pages"],
                "file_url": f"/api/file/{doc_id}", "docx_url": f"/api/docx/{doc_id}"}

    def index_background(self, doc_id: str) -> None:
        job = self.pending[doc_id]
        try:
            self.index_upload(doc_id, job["name"], job["file"])
            self.docs[doc_id]["parser"] = "mineru_running"  # upgrade_mineru chạy ngay sau
            self._save(doc_id)
            del self.pending[doc_id]
        except Exception as exc:
            print(f"[index] {doc_id} failed: {exc}")
            job.update(status="failed", error=f"Không đọc được nội dung PDF: {str(exc)[:200]}")

    def health(self) -> dict:
        online, models = _ollama_online()
        # ok=True de frontend mo chat that ngay; ollama status nam rieng
        return {"ok": True, "ollama_online": online, "ollama_models": models,
                "llm": DEFAULT_MODEL, "rag_engine": "ollama-embedding+tfidf" if online else "tfidf",
                "docs": len(self.docs)}

    def _meta_path(self, doc_id: str) -> Path:
        return self.data_dir / f"{doc_id}.json"

    def _save(self, doc_id: str) -> None:
        doc = self.docs[doc_id]
        # Path khong json-serializable -> luu str
        self._meta_path(doc_id).write_text(json.dumps({
            "name": doc["name"], "pages": doc["pages"], "ocr": doc["ocr"], "parser": doc["parser"],
            "docx": doc.get("docx", "unavailable")
        }, ensure_ascii=False), encoding="utf-8")

    def _index(self, doc_id: str, name: str, pdf_path: Path, pages: list[str], ocr: bool, parser: str) -> dict:
        chunks = _safe_chunks(pages)
        if not chunks:
            raise ValueError("Khong trich duoc chu nao tu PDF (ke ca OCR).")
        vectorizer = TfidfVectorizer(max_features=8000, ngram_range=(1, 2),
                                     token_pattern=r"(?u)\b\w+(?:\.\w+)*\b")
        matrix = vectorizer.fit_transform([chunk["text"] for chunk in chunks])
        self.docs[doc_id] = {"file": pdf_path, "name": name, "pages": pages, "chunks": chunks,
                             "ocr": ocr, "parser": parser, "vectorizer": vectorizer, "matrix": matrix,
                             "docx": self.docs.get(doc_id, {}).get("docx", "unavailable")}
        try:
            self.docs[doc_id]["embeddings"] = _embed([chunk["text"] for chunk in chunks])
        except requests.RequestException as exc:
            self.docs[doc_id]["embeddings"] = None
            print(f"[embedding] fallback TF-IDF: {exc}")
        self._save(doc_id)
        return self.info(doc_id)

    def index_upload(self, doc_id: str, name: str, pdf_path: Path) -> dict:
        embedded = [(page.extract_text() or "").strip() for page in PdfReader(str(pdf_path)).pages]
        is_text_pdf = sum(map(len, embedded)) >= 50 * max(1, len(embedded))
        pages = embedded if is_text_pdf else extract_pages(pdf_path)
        return self._index(doc_id, name, pdf_path, pages, not is_text_pdf, "pypdf" if is_text_pdf else "ocr")

    def load(self, doc_id: str) -> bool:
        if doc_id in self.docs:
            return True
        if not re.fullmatch(r"[0-9a-f]{10}", doc_id):
            return False
        meta_path, pdf_path = self._meta_path(doc_id), self.data_dir / f"{doc_id}.pdf"
        if not meta_path.exists() or not pdf_path.exists():
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._index(doc_id, meta["name"], pdf_path, meta["pages"], meta.get("ocr", False), meta.get("parser", "pypdf"))
        # trạng thái docx tính lại từ đĩa (trung thực sau restart)
        self.docs[doc_id]["docx"] = "ready" if (self.data_dir / f"{doc_id}.docx").exists() else "unavailable"
        return True

    def info(self, doc_id: str) -> dict:
        doc = self.docs[doc_id]
        return {"doc_id": doc_id, "name": doc["name"], "status": "ready", "ocr": doc["ocr"], "parser": doc["parser"],
                "docx": doc.get("docx", "unavailable"),
                "num_pages": len(doc["pages"]), "num_chunks": len(doc["chunks"]),
                "total_chars": sum(map(len, doc["pages"])), "file_url": f"/api/file/{doc_id}",
                "docx_url": f"/api/docx/{doc_id}"}

    def upgrade_mineru(self, doc_id: str) -> None:
        if not self.load(doc_id):
            return
        doc = self.docs[doc_id]
        doc["parser"] = "mineru_running"
        self._save(doc_id)
        try:
            with MINERU_LOCK:
                out_dir = self.data_dir / f"{doc_id}_mineru"
                run_mineru(doc["file"], out_dir)
                content_list = find_content_list(out_dir)
                if not content_list:
                    raise RuntimeError("MinerU khong tao content list")
                blocks = normalize_blocks(load_raw(content_list, None), doc["name"], doc_id)
                pages = _pages_from_blocks(blocks, len(doc["pages"]))
            if not any(pages):
                raise RuntimeError("MinerU khong trich duoc chu")
            self._index(doc_id, doc["name"], doc["file"], pages, doc["ocr"], "mineru")
            self._build_docx_rich(doc_id, out_dir)
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            doc["parser"] = "mineru_failed"
            self._save(doc_id)
            print(f"[MinerU] {doc_id} failed: {exc}")

    def _docx_path(self, doc_id: str) -> Path:
        return self.data_dir / f"{doc_id}.docx"

    def _set_docx(self, doc_id: str, status: str) -> None:
        if doc_id in self.docs:
            self.docs[doc_id]["docx"] = status
            try:
                self._save(doc_id)
            except OSError:
                pass

    def build_docx_fast(self, doc_id: str) -> None:
        """DOCX nhanh từ bản đọc pypdf/OCR (xong trong vài giây)."""
        if not self.load(doc_id):
            return
        if self.docs[doc_id].get("docx") == "ready" and self._docx_path(doc_id).exists():
            return
        self._set_docx(doc_id, "building")
        try:
            doc = self.docs[doc_id]
            parts = [f"# {doc['name']}", ""]
            for i, page in enumerate(doc["pages"], start=1):
                text = (page or "").strip()
                if not text:
                    continue
                parts += [f"## Trang {i}", "", normalize_math_in_text(text), ""]
            work_md = self.data_dir / f"{doc_id}.work.md"
            prepare_work_md("\n".join(parts), self.data_dir, work_md)
            md_to_docx(work_md, self._docx_path(doc_id), self.data_dir)
            self._set_docx(doc_id, "ready")
        except Exception as exc:
            print(f"[DOCX] {doc_id} fast failed: {exc}")
            self._set_docx(doc_id, "failed")
        finally:
            try:
                (self.data_dir / f"{doc_id}.work.md").unlink(missing_ok=True)
            except OSError:
                pass

    def _build_docx_rich(self, doc_id: str, out_dir: Path) -> None:
        """DOCX đẹp từ Markdown MinerU (công thức thành Equation)."""
        self._set_docx(doc_id, "building")
        try:
            doc = self.docs[doc_id]
            md_path, _, _ = find_mineru_outputs(out_dir)
            text = normalize_math_in_text(
                fix_vni(md_path.read_text(encoding="utf-8", errors="ignore")))
            work_md = out_dir / "source_for_docx.md"
            prepare_work_md(text, md_path, work_md)
            md_to_docx(work_md, self._docx_path(doc_id), md_path.parent)
            self._set_docx(doc_id, "ready")
        except Exception as exc:
            print(f"[DOCX] {doc_id} rich failed: {exc}")
            # giữ bản nhanh (nếu có) thay vì đánh failed
            self._set_docx(doc_id, "ready" if self._docx_path(doc_id).exists() else "failed")

    def retrieve(self, doc_id: str, question: str, history: list[dict], top_k: int) -> tuple[list[dict], str]:
        doc = self.docs[doc_id]
        previous = next((item.get("content", "") for item in reversed(history) if item.get("role") == "user"), "")
        query = f"{previous}\n{question}" if previous and len(question) < 60 else question
        page_numbers = {int(value) for value in PAGE_REF.findall(question)}
        hits = [{"page": page, "text": doc["pages"][page - 1], "score": 1.0} for page in sorted(page_numbers)
                if 1 <= page <= len(doc["pages"])]
        scores = cosine_similarity(doc["vectorizer"].transform([query]), doc["matrix"])[0]
        if doc.get("embeddings"):
            try:
                query_vector = _embed([f"Instruct: Given a question, retrieve passages that answer it\nQuery: {query}"])[0]
                scores = [0.7 * sum(value * query_value for value, query_value in zip(vector, query_vector))
                          + 0.3 * float(scores[index]) for index, vector in enumerate(doc["embeddings"])]
            except requests.RequestException:
                scores = list(scores)
        else:
            scores = list(scores)
        for index in sorted(range(len(scores)), key=lambda item: scores[item], reverse=True):
            chunk = doc["chunks"][index]
            if chunk["page"] not in page_numbers:
                hits.append({**chunk, "score": float(scores[index])})
            if len(hits) >= max(1, min(top_k, 10)):
                break
        return hits, question

    def warm(self, model: str) -> None:
        self._request(model, "Tra loi dung mot tu: OK", stream=False)

    def _request(self, model: str, prompt: str, stream: bool):
        if model not in ALLOWED_MODELS:
            raise ValueError("Model khong duoc phep dung.")
        return requests.post(f"{OLLAMA_URL}/api/generate", json={"model": model, "prompt": prompt,
            "stream": stream, "think": False, "options": {"temperature": 0.2, "num_ctx": 8192}},
            stream=stream, timeout=300)

    def stream_chat(self, doc_id: str, question: str, history: list[dict], top_k: int, model: str):
        hits, question = self.retrieve(doc_id, question, history, top_k)
        started = time.time()
        try:
            response = self._request(model, _prompt(hits, question, history), stream=True)
            response.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            # Ollama tat / thieu model -> tra loi trich doan ngay, van co citation
            text = _fallback_answer(hits, question) + f"\n(ly do fallback: {str(exc)[:160]})"
            for i in range(0, len(text), 120):
                yield {"t": text[i:i + 120]}
                time.sleep(0.01)
            yield {"done": True, "citations": sorted({hit["page"] for hit in hits}),
                   "elapsed_s": round(time.time() - started, 1)}
            return
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                item = json.loads(line)
                token = re.sub(r"<think>.*?</think>", "", item.get("response", ""), flags=re.S)
                if token:
                    yield {"t": token}
        except requests.RequestException as exc:
            yield {"error": f"Ollama ngat giua chung: {str(exc)[:200]}"}
            return
        yield {"done": True, "citations": sorted({hit["page"] for hit in hits}),
               "elapsed_s": round(time.time() - started, 1)}
