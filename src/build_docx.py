# """Bước 5-7 notebook: chuẩn hoá ảnh + Markdown -> DOCX Equation thật via Pandoc."""
# import re
# import subprocess
# from pathlib import Path

# from .config import PANDOC_FROM


# def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path) -> Path:
#     image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text)
#     print("Image references trong Markdown:", len(image_refs))
#     work_text = markdown_text
#     for ref in sorted(set(image_refs), key=len, reverse=True):
#         clean = ref.strip().strip("<>")
#         if clean.startswith(("http://", "https://", "data:")):
#             # URL từ xa hoặc ảnh nhúng base64 (data URI): pandoc đọc thẳng
#             # được, không phải path trên đĩa -> không được đưa vào resolve(),
#             # trên Windows base64 dài sẽ vỡ "path too long".
#             continue
#         try:
#             candidate = (md_path.parent / clean).resolve()
#         except (OSError, ValueError):
#             # path lạ/quá dài mà không phải data URI -> bỏ qua, giữ nguyên ref
#             continue
#         if candidate.exists():
#             work_text = work_text.replace(ref, str(candidate))
#     work_md.write_text(work_text, encoding="utf-8")
#     print("Working Markdown:", work_md)
#     return work_md


# def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path) -> Path:
#     cmd = [
#         "pandoc",
#         str(work_md),
#         "-o", str(docx_path),
#         f"--from={PANDOC_FROM}",
#         "--resource-path", str(resource_dir),
#         "--standalone",
#         "--toc",
#     ]
#     print("Running Pandoc...")
#     result = subprocess.run(cmd, capture_output=True, text=True,
#                             encoding="utf-8", errors="replace")
#     print(result.stdout)
#     if result.returncode != 0:
#         print(result.stderr)
#         raise RuntimeError("Pandoc tạo DOCX thất bại.")
#     assert docx_path.exists() and docx_path.stat().st_size > 0, "DOCX rỗng."
#     print(f"Đã tạo DOCX: {docx_path} ({docx_path.stat().st_size} bytes)")
#     return docx_path


"""Bước 5-7 notebook: chuẩn hoá ảnh + Markdown -> DOCX Equation thật via Pandoc."""
import re
import subprocess
from pathlib import Path

from .config import PANDOC_FROM


def fix_legacy_tex_bf(markdown_text: str) -> str:
    """MinerU OCR công thức đôi khi xuất `{ \\bf x }` (font-switch cũ) thay vì
    `\\mathbf{x}`. Pandoc/texmath KHÔNG hiểu `\\bf` trong math mode -> công thức
    đó bị bỏ qua, giữ nguyên dạng text thô `$...$` trong DOCX thay vì thành
    Equation. Fix: đổi `{ \\bf X }` -> `\\mathbf{X}` trước khi đưa vào Pandoc.
    Đã verify bằng pandoc thật: không còn `\\bf` -> ra m:oMath đầy đủ."""
    prev = None
    while prev != markdown_text:
        prev = markdown_text
        markdown_text = re.sub(
            r"\{\s*\\bf\s+([^{}]+?)\s*\}", r"\\mathbf{\1}", markdown_text)
    return markdown_text


def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path) -> Path:
    markdown_text = fix_legacy_tex_bf(markdown_text)
    image_refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown_text)
    print("Image references trong Markdown:", len(image_refs))
    work_text = markdown_text
    for ref in sorted(set(image_refs), key=len, reverse=True):
        clean = ref.strip().strip("<>")
        if clean.startswith(("http://", "https://", "data:")):
            # URL từ xa hoặc ảnh nhúng base64 (data URI): pandoc đọc thẳng
            # được, không phải path trên đĩa -> không được đưa vào resolve(),
            # trên Windows base64 dài sẽ vỡ "path too long".
            continue
        try:
            candidate = (md_path.parent / clean).resolve()
        except (OSError, ValueError):
            # path lạ/quá dài mà không phải data URI -> bỏ qua, giữ nguyên ref
            continue
        if candidate.exists():
            work_text = work_text.replace(ref, str(candidate))
    work_md.write_text(work_text, encoding="utf-8")
    print("Working Markdown:", work_md)
    return work_md


def add_page_numbers(docx_path: Path, align: str = "center") -> Path:
    """Chèn số trang (field code PAGE) vào footer của mọi section trong DOCX.
    Word sẽ tự cập nhật số trang khi in/xem, không phải text tĩnh."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    align_map = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }

    def _add_page_field(paragraph):
        run = paragraph.add_run()
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = "PAGE"
        fld_separate = OxmlElement("w:fldChar")
        fld_separate.set(qn("w:fldCharType"), "separate")
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        run._r.append(fld_begin)
        run._r.append(instr)
        run._r.append(fld_separate)
        run._r.append(fld_end)

    doc = Document(str(docx_path))
    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False
        # Xoá nội dung cũ (nếu có) rồi chèn field PAGE
        paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        for r in list(paragraph.runs):
            r._r.getparent().remove(r._r)
        paragraph.alignment = align_map.get(align, WD_ALIGN_PARAGRAPH.CENTER)
        _add_page_field(paragraph)

    doc.save(str(docx_path))
    print(f"Đã đánh số trang: {docx_path}")
    return docx_path


def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path,
                number_pages: bool = True) -> Path:
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
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("Pandoc tạo DOCX thất bại.")
    assert docx_path.exists() and docx_path.stat().st_size > 0, "DOCX rỗng."
    print(f"Đã tạo DOCX: {docx_path} ({docx_path.stat().st_size} bytes)")
    if number_pages:
        add_page_numbers(docx_path)
    return docx_path