"""Bước 2 notebook: chạy MinerU + tìm Markdown/JSON/Images."""
import subprocess
from pathlib import Path


def run_mineru(pdf_path: Path, out_dir: Path, backend: str = "pipeline") -> None:
    cmd = ["mineru", "-p", str(pdf_path), "-o", str(out_dir), "-b", backend]
    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(
            "MinerU thất bại. Nếu backend mặc định lỗi trên Colab, "
            "dùng -b pipeline (đã là mặc định ở config)."
        )


def find_mineru_outputs(mineru_dir: Path):
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
            "Không tìm thấy Markdown của MinerU. Kiểm tra log cell MinerU."
        )
    # Chọn file lớn nhất để tránh file phụ
    md_path = max(md_files, key=lambda p: p.stat().st_size)
    print("\nMarkdown được chọn:", md_path)
    return md_path, json_files, image_files
