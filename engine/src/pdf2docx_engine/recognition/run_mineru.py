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
import subprocess
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


def run_mineru(pdf_path: Path, out_dir: Path, backend: str = "pipeline",
               tier: str = "standard", force: bool = False) -> None:
    """Chạy MinerU bằng CLI mới của MinerU 4.0 (`mineru-kit parse`), giống notebook.

    Lệnh cũ `mineru -p ... -o ... -b <backend>` đã bị loại bỏ từ MinerU 4.0.
    Dùng lệnh cũ trên MinerU 4.x khiến bước parse PDF chạy sai/rơi vào nhánh
    khác kém chính xác hơn -> Markdown thiếu chữ, sai chữ, mất công thức,
    và lỗi đó lan xuống DOCX + RAG vì cả hai đều dựng từ Markdown này.
    `backend` được giữ lại trong chữ ký hàm để không vỡ code gọi cũ, nhưng
    không còn dùng nữa (mineru-kit tự chọn route theo --tier).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # tier advanced chỉ xuất .md (không có content_list.json) -> có .md cũng coi là đã chạy
    if not force and (find_content_list(out_dir) or next(out_dir.rglob("*.md"), None)):
        print(f"[MinerU] Đã có output cho PDF này, bỏ qua chạy lại: {out_dir}")
        print("         (dùng --force nếu muốn chạy lại MinerU)")
        return
    cmd = ["mineru-kit", "parse", str(pdf_path), "-o", str(out_dir), "--tier", tier]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(
            "MinerU (mineru-kit parse) thất bại. Thử --tier advanced nếu "
            "công thức toán ra không chuẩn với standard, hoặc kiểm tra "
            "`mineru-kit --help` để xem CLI có đổi tham số không."
        )


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
