"""Bước 5-7 notebook: chuẩn hoá ảnh + Markdown -> DOCX Equation thật via Pandoc."""
import re
import subprocess
from pathlib import Path

from .config import PANDOC_FROM


def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path) -> Path:
    image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text)
    print("Image references trong Markdown:", len(image_refs))
    work_text = markdown_text
    for ref in sorted(set(image_refs), key=len, reverse=True):
        clean = ref.strip().strip("<>")
        if clean.startswith(("http://", "https://")):
            continue
        candidate = (md_path.parent / clean).resolve()
        if candidate.exists():
            work_text = work_text.replace(ref, str(candidate))
    work_md.write_text(work_text, encoding="utf-8")
    print("Working Markdown:", work_md)
    return work_md


def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path) -> Path:
    cmd = [
        "pandoc",
        str(work_md),
        "-o", str(docx_path),
        f"--from={PANDOC_FROM}",
        "--resource-path", str(resource_dir),
        "--standalone",
        "--toc",
    ]
    print("Running Pandoc...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("Pandoc tạo DOCX thất bại.")
    assert docx_path.exists() and docx_path.stat().st_size > 0, "DOCX rỗng."
    print(f"Đã tạo DOCX: {docx_path} ({docx_path.stat().st_size} bytes)")
    return docx_path
