"""Bước 2 notebook: chạy MinerU + tìm Markdown/JSON/Images.

MỚI (fix lỗi #1 tuần 2 — "lấy nhầm dữ liệu cũ"):
- Mỗi PDF có run dir riêng: runs/<ten_file>_<doc_id>/mineru/
  doc_id = hash nội dung PDF, nên cùng file luôn ra cùng ID, PDF khác nhau
  không bao giờ trộn output với nhau.
- run_mineru() bỏ qua chạy lại nếu output đã có, trừ khi force=True.

Giữ nguyên chữ ký find_mineru_outputs() như bản gốc (trả 3 giá trị) để không
vỡ các đoạn code debug thủ công trong HUONG_DAN_CHAY_CHI_TIET.md.
"""
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple


def compute_doc_id(pdf_path: Path) -> str:
    """ID ổn định theo NỘI DUNG file PDF (không phải theo tên)."""
    h = hashlib.sha1()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:10]


def prepare_run_dir(pdf_path: Path, runs_dir: Path) -> Tuple[str, Path]:
    """Tạo (nếu chưa có) và trả về (doc_id, run_dir) riêng cho PDF này."""
    doc_id = compute_doc_id(pdf_path)
    run_dir = runs_dir / f"{pdf_path.stem}_{doc_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return doc_id, run_dir


def find_content_list(mineru_dir: Path) -> Optional[Path]:
    """File *_content_list.json của MinerU: có type/page_idx/text_level cho từng block."""
    cands = [p for p in mineru_dir.rglob("*_content_list.json")]
    return max(cands, key=lambda p: p.stat().st_size) if cands else None


_SKIP = {"header", "footer", "page_number", "aside_text", "page_footnote"}


def kit_to_content_list(structured: dict) -> List[dict]:
    """structured_content.json của `mineru-kit` (4.x) -> danh sách phẳng kiểu *_content_list.json
    (page_idx/type/text/text_level) để structured.normalize_blocks và Library ingest đọc như cũ."""
    out: List[dict] = []
    as_list = lambda v: [x if isinstance(x, str) else str(x) for x in (v or [])]
    for page in structured.get("pages", []):
        for b in page.get("blocks", []):
            t, c = b.get("type"), b.get("content") or ""
            item = {"page_idx": page.get("page_idx", 0), "bbox": b.get("bbox")}
            if t in _SKIP:
                continue
            if t in ("text", "doc_title", "paragraph_title"):
                item.update(type="text", text=c)
                if b.get("level"):
                    item["text_level"] = b["level"]
            elif t == "equation":
                item.update(type="equation", text=f"$$\n{c}\n$$", img_path=b.get("image_source"))
            elif t == "table":
                item.update(type="table", table_body=c, table_caption=as_list(b.get("captions")),
                            table_footnote=as_list(b.get("footnotes")), img_path=b.get("image_source"))
            elif t in ("image", "chart"):
                item.update(type="image", image_caption=as_list(b.get("captions")), img_path=b.get("image_source"))
            elif t == "code":
                item.update(type="code", code_body=c)
            elif c:
                item.update(type="text", text=c)
            else:
                continue
            out.append(item)
    return out


def _run_kit(kit: str, pdf_path: Path, out_dir: Path, tier: str) -> None:
    """mineru-kit 4.x: parse ra zip (markdown + ảnh + structured_content), giải nén và dựng content_list."""
    tmp = out_dir / "_kit"
    shutil.rmtree(tmp, ignore_errors=True)
    cmd = [kit, "parse", str(pdf_path), "-o", str(tmp), "--tier", tier, "-f", "zip"]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    zips = list(tmp.glob("*.zip"))
    if result.returncode != 0 or not zips:
        print(result.stderr[-2000:])
        raise RuntimeError("MinerU (mineru-kit parse) thất bại; thử --tier advanced hoặc xem `mineru-kit --help`.")
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(out_dir)
    shutil.rmtree(tmp, ignore_errors=True)
    stem = pdf_path.stem
    (out_dir / "markdown.md").replace(out_dir / f"{stem}.md")
    structured = json.loads((out_dir / "structured_content.json").read_text(encoding="utf-8"))
    (out_dir / f"{stem}_content_list.json").write_text(
        json.dumps(kit_to_content_list(structured), ensure_ascii=False), encoding="utf-8")


def has_extractable_text(pdf_path: Path, pages_to_check: int = 3,
                           min_chars_per_page: int = 50) -> bool:
    """PDF chữ (text-based) hay PDF scan? True = có chữ trích xuất được -> dùng
    `-m txt` để bỏ qua OCR, nhanh hơn nhiều. False = phải OCR."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        checked = 0
        for page in reader.pages[:max(1, pages_to_check)]:
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if len(text) >= min_chars_per_page:
                return True
            checked += 1
        return False
    except Exception:
        return False  # không đọc được -> để MinerU tự quyết (auto)


def run_mineru(pdf_path: Path, out_dir: Path, backend: str = "pipeline",
               tier: str = "standard", force: bool = False,
               method: str = "auto", lang: str = "latin", device: str = "cpu",
               formula: bool = True, table: bool = True) -> None:
    """Chạy MinerU. Có `mineru-kit` (MinerU 4.x) thì dùng — công thức LaTeX sạch hơn rõ rệt;
    không có thì rơi về CLI cũ `mineru -p -o -b pipeline` (2.x) để máy chưa nâng cấp vẫn chạy.

    method: 'auto' | 'txt' (PDF chữ, bỏ OCR — nhanh nhất) | 'ocr' (PDF scan).
    lang: mã ngôn ngữ cho OCR ('latin' hợp PDF tiếng Việt nhất; mặc định CLI là 'ch').
    device: 'cpu' ổn định nhất trên Mac; có CUDA thì đổi 'cuda:0'.
    formula/table: PDF toán GIỮ True (công thức Equation cần formula=True)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if not force and find_content_list(out_dir):
        print(f"[MinerU] Đã có output cho PDF này, bỏ qua chạy lại: {out_dir}")
        return
    kit = shutil.which("mineru-kit")
    if kit:
        _run_kit(kit, pdf_path, out_dir, tier)
        return
    cmd = ["mineru", "-p", str(pdf_path), "-o", str(out_dir), "-b", backend,
           "-m", method, "-l", lang, "-d", device,
           "-f", "true" if formula else "false",
           "-t", "true" if table else "false"]
    print("Running (legacy):", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        print(result.stderr[-2000:])
        raise RuntimeError("MinerU thất bại (không có mineru-kit; CLI cũ `mineru` cũng lỗi).")


def find_mineru_outputs(mineru_dir: Path):
    """CHỈ quét trong mineru_dir của run hiện tại (không quét thư mục dùng chung
    của nhiều PDF — đây chính là lỗi cũ đã fix). Trả về (md_path, json_files, image_files)."""
    all_files = [p for p in mineru_dir.rglob("*") if p.is_file()]
    md_files = [p for p in all_files if p.suffix.lower() == ".md"]
    json_files = [p for p in all_files if p.suffix.lower() == ".json"]
    image_files = [
        p for p in all_files
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
    ]
    print(f"Markdown: {len(md_files)}")
    for p in md_files:
        print("  ", p)
    print(f"\nJSON: {len(json_files)}")
    for p in json_files[:20]:
        print("  ", p)
    print(f"\nImages: {len(image_files)}")
    for p in image_files[:20]:
        print("  ", p)
    if not md_files:
        raise FileNotFoundError(
            "Không tìm thấy Markdown của MinerU trong run dir này. "
            "Kiểm tra log cell MinerU."
        )
    # Chọn file lớn nhất để tránh file phụ (giữ logic gốc)
    md_path = max(md_files, key=lambda p: p.stat().st_size)
    print("\nMarkdown được chọn:", md_path)
    return md_path, json_files, image_files
