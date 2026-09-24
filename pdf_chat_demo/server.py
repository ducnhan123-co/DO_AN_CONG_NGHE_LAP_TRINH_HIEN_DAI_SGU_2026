"""SGU PDF Chat — backend thực chiến.

Kiến trúc:
  PDF upload -> pypdf (hoặc OCR tesseract nếu PDF scan) trích text theo trang
  -> chat được NGAY; song song MinerU chạy nền -> thay text bằng bản LaTeX chuẩn
  -> chunk (giữ số trang) -> retrieval hybrid: embedding qwen3-embedding (Ollama)
     + TF-IDF; hỏi "trang N" thì đưa nguyên trang N
  -> Ollama local (qwen3) sinh câu trả lời kèm [trang], có lịch sử hội thoại.

Chạy:
  python3 server.py                      # API http://127.0.0.1:8001
  python3 -m http.server 8080            # rồi mở http://localhost:8080/index.html
  MINERU_BIN=/đường/dẫn/mineru-kit python3 server.py   # đổi chỗ cài MinerU 4.x
"""
import os
import re
import json
import uuid
import time
import asyncio
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np
import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from latex_norm import normalize_latex

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

OLLAMA_URL = "http://localhost:11434"
LLM_MODEL = "qwen3:8b"          # model chat local (máy đã có sẵn)
FAST_MODEL = "qwen2.5:1.5b"     # model nhẹ: trả lời nhanh, hợp M5
BIG_MODEL = "qwen3:14b"         # model lớn: hay nhất, chậm nhất
EMBED_MODEL = "qwen3-embedding:0.6b"  # để dành khi cần dense retrieval
TOP_K = 5
NUM_CTX = 8192        # đủ chỗ cho cả 1 trang + lịch sử chat
HISTORY_TURNS = 6     # số tin nhắn cũ gửi kèm (3 lượt hỏi-đáp)
HISTORY_CHARS = 3000  # mỗi tin; câu trả lời có LaTeX dài, cắt ngắn là model mất đếm "công thức thứ 3"
# MinerU 4.x (venv riêng vì kéo torch): chạy nền sau upload để lấy công thức LaTeX chuẩn.
MINERU_BIN = Path(os.environ.get(
    "MINERU_BIN", Path.home() / "Documents/00_Inbox/src_update_fixed/.venv/bin/mineru-kit"))
MINERU_TIER = "standard"
MINERU_LOCK = threading.Lock()  # ponytail: 1 MinerU mỗi lúc (ăn nhiều RAM); hàng đợi thật nếu nhiều user
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200

app = FastAPI(title="SGU PDF Chat API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# doc_id -> {"file": Path, "name": str, "pages": [str], "chunks": [...],
#            "vectorizer": ..., "matrix": ...}
STORE: dict = {}


def ocr_pages(pdf_path: Path, dpi=180, lang="vie+eng") -> list[str]:
    """Fallback cho PDF scan: render từng trang rồi OCR tiếng Việt."""
    import fitz
    doc = fitz.open(str(pdf_path))
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            tmp = tf.name
        try:
            pix.save(tmp)
            p = subprocess.run(["tesseract", tmp, "stdout", "-l", lang],
                               capture_output=True, text=True, timeout=240)
            out.append(p.stdout.strip())
        finally:
            Path(tmp).unlink(missing_ok=True)
    doc.close()
    return out


MINERU_SKIP = {"header", "footer", "page_number", "page_footnote", "aside_text"}


def _mineru_text(c) -> str:
    """Gom chữ trong 'content' của middle_json; công thức inline -> $..$."""
    if isinstance(c, str):
        return c
    out = []
    for x in c or []:
        if not isinstance(x, dict):
            continue
        if x.get("type") == "equation_inline":
            out.append(f" ${normalize_latex(x.get('content', ''))}$ ")
        elif x.get("type") != "image_body":
            out.append(_mineru_text(x.get("content")))
    return "".join(out)


def mineru_pages(pdf_path: Path) -> list[str]:
    """PDF -> MinerU middle_json -> text từng trang (giữ số trang để trích dẫn)."""
    out = DATA / f"{pdf_path.stem}_mineru"
    subprocess.run([str(MINERU_BIN), "parse", str(pdf_path), "-o", str(out),
                    "-f", "middle_json", "--tier", MINERU_TIER],
                   check=True, capture_output=True, text=True, timeout=3600)
    d = json.loads(next(out.glob("*.json")).read_text())
    pages = [""] * len(d["pages"])
    for pg in d["pages"]:
        parts = []
        for b in pg["blocks"]:
            if b["type"] in MINERU_SKIP:
                continue
            if b["type"] == "equation":
                tex = normalize_latex(b.get("content", ""))
                tag = re.search(r"\\tag\{([^}]*)\}", tex)  # để tìm được "(3.1)" bằng chữ
                parts.append(f"$${tex}$$" + (f" ({tag.group(1)})" if tag else ""))
            else:
                t = _mineru_text(b.get("content")).strip()
                if b["type"] == "paragraph_title" and t:
                    t = "## " + t
                parts.append(t)
        pages[pg["page_idx"]] = "\n\n".join(x for x in parts if x.strip())
    return pages


def _mineru_upgrade(doc_id: str):
    """Chạy nền: thay text pypdf/OCR bằng text MinerU (LaTeX) khi xong."""
    d = STORE[doc_id]
    d["parser"] = "mineru_running"
    try:
        with MINERU_LOCK:
            t0 = time.time()
            pages = mineru_pages(d["file"])
        if not any(pages):
            raise RuntimeError("MinerU không ra chữ")
        _index_pages(doc_id, d["name"], d["file"], pages, ocr=d["ocr"], parser="mineru")
        print(f"[MinerU] {doc_id}: {len(pages)} trang, {time.time() - t0:.0f}s")
    except Exception as e:  # giữ bản pypdf, chat vẫn chạy
        d["parser"] = "mineru_failed"
        print(f"[MinerU] {doc_id} lỗi: {str(e)[:300]}")


def split_chunks(text: str, max_chars=CHUNK_CHARS, overlap=CHUNK_OVERLAP):
    """Cắt theo đoạn văn (giữ công thức/bảng không bị chém đôi như src_update fix #3)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
            # đoạn quá dài mới cắt cứng theo câu (luôn tiến: step >= 1)
            while len(p) > max_chars:
                cut = p.rfind(". ", 0, max_chars)
                cut = cut + 2 if cut > 0 else max_chars
                chunks.append(p[:cut])
                step = cut - overlap
                if step <= 0:
                    step = cut  # câu đầu quá ngắn: bỏ overlap nhưng vẫn tiến
                p = p[step:]
            buf = p
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c.strip()) > 40]


def embed(texts: list[str]):
    """Vector ngữ nghĩa đa ngôn ngữ (hỏi tiếng Việt vẫn khớp tài liệu tiếng Anh)."""
    r = requests.post(f"{OLLAMA_URL}/api/embed",
                      json={"model": EMBED_MODEL, "input": texts}, timeout=300)
    r.raise_for_status()
    v = np.array(r.json()["embeddings"], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)


def index_doc(doc_id: str):
    d = STORE[doc_id]
    texts = [c["text"] for c in d["chunks"]]
    # giữ token 1 ký tự và số hiệu kiểu 3.1 (mặc định sklearn bỏ cả hai)
    vec = TfidfVectorizer(max_features=8000, ngram_range=(1, 2),
                          token_pattern=r"(?u)\b\w+(?:\.\w+)*\b")
    d["vectorizer"] = vec
    d["matrix"] = vec.fit_transform(texts)
    try:
        d["emb"] = embed(texts)
    except Exception as e:  # thiếu model embedding -> chỉ dùng TF-IDF
        d["emb"] = None
        print(f"[embed] bỏ qua: {e}")


def retrieve(doc_id: str, question: str, top_k=TOP_K):
    d = STORE[doc_id]
    scores = cosine_similarity(d["vectorizer"].transform([question]), d["matrix"])[0]
    if d.get("emb") is not None:  # hybrid: ngữ nghĩa là chính, từ khoá để bắt số hiệu/ký hiệu
        q = embed([f"Instruct: Given a question, retrieve passages that answer it\nQuery: {question}"])[0]
        scores = d["emb"] @ q + 0.5 * scores
    idx = scores.argsort()[::-1][:top_k]
    return [{**d["chunks"][int(i)], "score": float(scores[int(i)])} for i in idx]


def ollama_chat(prompt: str, model: str = LLM_MODEL) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False,
              "think": False,  # tắt chain-of-thought: nhanh gấp nhiều lần
              "options": {"temperature": 0.2, "num_ctx": NUM_CTX}},
        timeout=300,
    )
    r.raise_for_status()
    ans = r.json().get("response", "").strip()
    # phòng khi model vẫn nhả <think>
    ans = re.sub(r"<think>.*?</think>", "", ans, flags=re.S).strip()
    return ans


PAGE_REF = re.compile(r"(?:trang|page|tr\.)\s*(\d{1,4})", re.I)


def gather_context(doc_id: str, question: str, history: list[dict], top_k=TOP_K):
    """Hỏi "trang N" -> đưa NGUYÊN trang N vào context (1 trang bị chia nhiều chunk,
    retrieval chỉ bắt được 1 phần). Câu hỏi nối tiếp ngắn -> ghép câu hỏi trước
    để tìm đúng chủ đề ("nói cụ thể hơn" không tự chứa từ khoá)."""
    prev = next((m["content"] for m in reversed(history) if m.get("role") == "user"), "")
    pages = {int(n) for n in PAGE_REF.findall(question)}
    inherited = False
    if not pages and len(question) < 60:  # ponytail: heuristic câu nối tiếp; nâng cấp = cho LLM viết lại câu hỏi
        pages = {int(n) for n in PAGE_REF.findall(prev)}
        inherited = bool(pages)
    query = f"{prev}\n{question}" if prev and len(question) < 60 else question
    all_pages = STORE[doc_id]["pages"]
    pages = sorted(p for p in pages if 1 <= p <= len(all_pages))
    hits = [{"page": p, "text": _annotate_page(p, all_pages[p - 1]), "score": 1.0}
            for p in pages]
    for h in retrieve(doc_id, query, top_k=top_k + len(pages)):
        if len(hits) >= top_k + len(pages):
            break
        if h["page"] not in pages:
            hits.append(h)
    if inherited:  # "nó nói về gì" -> nói rõ "nó" là trang nào, model nhỏ hay hiểu thành cả tài liệu
        question = f"(Câu hỏi nối tiếp, đang nói về trang {', '.join(map(str, pages))}) {question}"
    return hits, question


DISPLAY_MATH = re.compile(r"\$\$.+?\$\$", re.S)


def _annotate_page(page: int, text: str) -> str:
    """Nguyên trang + đếm/đánh số công thức sẵn: LLM đếm hay sai (từng trả lời 3 thay vì 5)."""
    n = len(DISPLAY_MATH.findall(text))
    k = iter(range(1, n + 1))
    body = DISPLAY_MATH.sub(lambda m: f"[Công thức {next(k)}/{n}] {m.group(0)}", text)
    return (f"(TOÀN BỘ trang {page}: có đúng {n} công thức riêng dòng, "
            f"đã đánh số [Công thức i/{n}])\n{body}")


def build_prompt(hits, question: str, history: list[dict] = ()) -> str:
    context = "\n\n".join(
        f"[trang {h['page']}]\n{h['text']}"  # không đánh số nguồn: model hay lấy nhầm làm số trang
        for h in hits)
    past = "\n".join(
        f"{'Người dùng' if m.get('role') == 'user' else 'Trợ lý'}: {m.get('content', '')[:HISTORY_CHARS]}"
        for m in history[-HISTORY_TURNS:])
    return f"""Bạn là trợ lý hỏi đáp tài liệu học thuật (tiếng Việt).

QUY TẮC BẮT BUỘC:
- Chỉ dùng thông tin trong CONTEXT. Không bịa công thức/số liệu.
- Mỗi ý trả lời PHẢI kèm trích dẫn số trang dạng [số], ví dụ [3].
- Nếu CONTEXT không đủ, nói rõ tài liệu không cung cấp đủ thông tin.
- Giữ nguyên công thức/ký hiệu khi trích dẫn. Trả lời súc tích.
- Công thức trong CONTEXT viết bằng LaTeX; khi nêu công thức hãy giữ LaTeX
  trong $...$ (inline) hoặc $$...$$ (dòng riêng).
- Nhắc tới công thức nào thì PHẢI chép lại nguyên văn LaTeX $$...$$ của nó.
  Nhãn [Công thức i/n] chỉ để đếm/đánh số: KHÔNG in nhãn này ra, gọi là
  "Công thức i" rồi chép LaTeX ngay bên dưới.
- Nếu người dùng chỉ chào hỏi hoặc tin nhắn không phải câu hỏi về tài liệu
  (vd "chào", "bạn", "ok"): chỉ đáp lại 1 câu ngắn và mời họ đặt câu hỏi,
  KHÔNG liệt kê nội dung tài liệu, KHÔNG trích dẫn.
- Nếu hỏi về một trang cụ thể: dùng MỌI đoạn [trang đó] trong CONTEXT, liệt kê
  ĐẦY ĐỦ theo thứ tự xuất hiện (vd tất cả công thức), không bỏ sót.
- Câu hỏi có thể nối tiếp LỊCH SỬ HỘI THOẠI ("nói rõ hơn", "cái thứ 2"...):
  hiểu theo ngữ cảnh đó.

LỊCH SỬ HỘI THOẠI:
{past or "(chưa có)"}

CONTEXT:
{context}

CÂU HỎI:
{question}

TRẢ LỜI (mỗi ý kèm số trang trong ngoặc vuông, ví dụ [6]):"""


@app.get("/api/health")
def health():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
        models = [m["name"] for m in r.get("models", [])]
    except Exception as e:
        return {"ok": False, "ollama": f"unreachable: {e}", "docs": len(STORE)}
    return {"ok": True, "ollama_models": models, "llm": LLM_MODEL,
            "docs": len(STORE)}


@app.post("/api/upload")
async def upload(f: UploadFile = File(...)):
    if not f.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Chỉ nhận file .pdf")
    doc_id = uuid.uuid4().hex[:10]
    path = DATA / f"{doc_id}.pdf"
    path.write_bytes(await f.read())
    try:
        pages, ocr = await _extract_or_ocr(path)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    res = _index_pages(doc_id, f.filename, path, pages, ocr=ocr)
    if MINERU_BIN.exists():  # chat được ngay bằng bản nhanh, MinerU nâng cấp sau
        STORE[doc_id]["parser"] = res["parser"] = "mineru_running"
        threading.Thread(target=_mineru_upgrade, args=(doc_id,), daemon=True).start()
    return res


class IngestReq(BaseModel):
    path: str  # đường dẫn file PDF có sẵn trên máy chủ (tránh upload lớn)


def _index_pages(doc_id: str, name: str, path: Path, pages: list[str], ocr=False,
                 parser="pypdf"):
    chunks = []
    for i, t in enumerate(pages, start=1):
        for c in split_chunks(t):
            chunks.append({"page": i, "text": c})
    STORE[doc_id] = {"file": path, "name": name, "ocr": ocr, "parser": parser,
                     "pages": pages, "chunks": chunks}
    path.with_suffix(".json").write_text(json.dumps(
        {"name": name, "ocr": ocr, "parser": parser, "pages": pages},
        ensure_ascii=False))
    index_doc(doc_id)
    return {"doc_id": doc_id, "name": name, "ocr": ocr, "parser": parser,
            "num_pages": len(pages), "num_chunks": len(chunks),
            "total_chars": sum(len(p) for p in pages)}


async def _extract_or_ocr(pdf_path: Path):
    """Trích text thường, không có chữ thì OCR (cho PDF scan)."""
    try:
        pages = [(p.extract_text() or "").strip()
                 for p in PdfReader(str(pdf_path)).pages]
    except Exception as e:
        raise HTTPException(400, f"Không đọc được PDF: {e}")
    if any(pages):
        return pages, False
    pages = await asyncio.to_thread(ocr_pages, pdf_path)
    if not any(pages):
        raise HTTPException(400, "OCR cũng không đọc được file này.")
    return pages, True


def _load(doc_id: str) -> bool:
    """doc_id có trong RAM, hoặc nạp lại từ data/ (sau khi restart server)."""
    if doc_id in STORE:
        return True
    if not re.fullmatch(r"[0-9a-f]{10}", doc_id):
        return False
    meta = DATA / f"{doc_id}.json"
    if not meta.exists():
        return False
    m = json.loads(meta.read_text())
    _index_pages(doc_id, m["name"], DATA / f"{doc_id}.pdf", m["pages"], m["ocr"],
                 m.get("parser", "pypdf"))
    return True


@app.post("/api/ingest_path")
async def ingest_path(req: IngestReq):
    """Nạp PDF từ ổ đĩa server (cho file lớn / thư viện có sẵn)."""
    src = Path(req.path).expanduser()
    if not src.exists() or src.suffix.lower() != ".pdf":
        raise HTTPException(400, f"Không thấy file PDF: {req.path}")
    doc_id = uuid.uuid4().hex[:10]
    dst = DATA / f"{doc_id}.pdf"
    import shutil
    shutil.copy2(src, dst)
    pages, ocr = await _extract_or_ocr(dst)
    return _index_pages(doc_id, src.name, dst, pages, ocr=ocr)


class ChatReq(BaseModel):
    doc_id: str
    question: str
    top_k: int = TOP_K
    model: str = LLM_MODEL  # client chọn: nhanh / chuẩn / hay
    history: list[dict] = []  # [{role: user|assistant, content}] các lượt trước


class WarmReq(BaseModel):
    model: str = LLM_MODEL


@app.post("/api/warm")
def warm(req: WarmReq):
    """Nạp model vào RAM trước (gọi ngầm khi user mở tài liệu)."""
    try:
        ollama_chat("Trả lời đúng 1 từ: OK", model=req.model)
        return {"ok": True, "model": req.model}
    except Exception as e:
        raise HTTPException(502, f"Ollama lỗi: {e}")


@app.post("/api/chat")
def chat(req: ChatReq):
    if not _load(req.doc_id):
        raise HTTPException(404, "doc_id không tồn tại (upload lại file).")
    hits, question = gather_context(req.doc_id, req.question, req.history, top_k=req.top_k)
    prompt = build_prompt(hits, question, req.history)
    t0 = time.time()
    try:
        answer = ollama_chat(prompt, model=req.model)
    except Exception as e:
        raise HTTPException(502, f"Ollama local lỗi: {e}")
    cites = sorted({h["page"] for h in hits})
    return {"answer": answer,
            "citations": cites,
            "sources": [{"page": h["page"], "score": round(h["score"], 3),
                         "snippet": h["text"][:220]} for h in hits],
            "elapsed_s": round(time.time() - t0, 1)}


@app.post("/api/chat_stream")
def chat_stream(req: ChatReq):
    """Chat streaming (SSE): token hiện dần, không phải chờ cả câu."""
    if not _load(req.doc_id):
        raise HTTPException(404, "doc_id không tồn tại (upload lại file).")
    hits, question = gather_context(req.doc_id, req.question, req.history, top_k=req.top_k)
    prompt = build_prompt(hits, question, req.history)
    cites = sorted({h["page"] for h in hits})

    def gen():
        t0 = time.time()
        try:
            with requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": req.model, "prompt": prompt, "stream": True,
                      "think": False,
                      "options": {"temperature": 0.2, "num_ctx": NUM_CTX}},
                stream=True, timeout=300,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except Exception:
                        continue
                    tok = o.get("response", "")
                    # lọc rò rỉ <think>
                    tok = re.sub(r"<think>.*?</think>", "", tok, flags=re.S)
                    if tok:
                        yield "data: " + json.dumps({"t": tok}) + "\n\n"
            yield ("data: " + json.dumps(
                {"done": True, "citations": cites,
                 "elapsed_s": round(time.time() - t0, 1)}) + "\n\n")
        except Exception as e:
            yield "data: " + json.dumps({"error": str(e)[:200]}) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/doc/{doc_id}")
def doc_info(doc_id: str):
    if not _load(doc_id):
        raise HTTPException(404, "doc_id không tồn tại.")
    d = STORE[doc_id]
    return {"doc_id": doc_id, "name": d["name"],
            "ocr": d.get("ocr", False), "parser": d.get("parser", "pypdf"),
            "num_pages": len(d["pages"]), "num_chunks": len(d["chunks"]),
            "file_url": f"/api/file/{doc_id}"}


@app.get("/api/file/{doc_id}")
def doc_file(doc_id: str):
    """Serve PDF GỐC để pane phải hiển thị nguyên bản."""
    if not _load(doc_id):
        raise HTTPException(404, "doc_id không tồn tại.")
    d = STORE[doc_id]
    return FileResponse(d["file"], media_type="application/pdf",
                        filename=d["name"], content_disposition_type="inline")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
