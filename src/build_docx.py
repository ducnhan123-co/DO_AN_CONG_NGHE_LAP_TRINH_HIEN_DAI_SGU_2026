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


def fix_broken_double_prime(markdown_text: str) -> str:
    """MinerU OCR công thức đôi khi đọc nhầm ký hiệu đạo hàm cấp 2 (dấu double
    prime ″, ví dụ trong f''_{x^2}) thành một dấu ngoặc kép " (hoặc " ") do
    hai glyph trông giống nhau. Kết quả: `f _ {x^2} ^ {"}` thay vì
    `f _ {x^2} ^ {\\prime\\prime}`. Pandoc/texmath không hiểu `"` trong số mũ
    của math mode -> công thức bị bỏ qua, rớt về text thô `$...$` trong DOCX
    thay vì thành Equation đúng (mất luôn dấu đạo hàm cấp 2).
    Fix: đổi `^ {"}` / `^ {"}` / `^ {"}` -> `^ {\\prime \\prime}` trước khi
    đưa vào Pandoc."""
    prev = None
    while prev != markdown_text:
        prev = markdown_text
        markdown_text = re.sub(
            r'\^\s*\{\s*["“”]\s*\}', r"^ {\\prime \\prime}", markdown_text)
    return markdown_text


FORMULA_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)",
    re.DOTALL)


def find_unbalanced_left_right(markdown_text: str) -> list:
    """Quét mọi công thức ($...$, $$...$$, \\[...\\], \\(...\\)) và báo công
    thức nào có số \\left khác số \\right. MinerU OCR thỉnh thoảng lồng sai
    \\left\\{ ... \\right. khi có nhiều tầng hệ phương trình lồng nhau -> Pandoc
    không parse được, công thức rớt về text thô thay vì Equation thật.
    Trả về list các dict {formula, n_left, n_right, pos} để log/báo cho người
    dùng tự sửa lại Markdown gốc (khó auto-sửa an toàn khi lồng sai vị trí,
    chỉ đúng số lượng không đảm bảo đúng cấu trúc)."""
    problems = []
    for m in FORMULA_RE.finditer(markdown_text):
        formula = m.group(0)
        n_left = len(re.findall(r"\\left(?![a-zA-Z])", formula))
        n_right = len(re.findall(r"\\right(?![a-zA-Z])", formula))
        if n_left != n_right:
            problems.append({
                "formula": formula,
                "n_left": n_left,
                "n_right": n_right,
                "pos": m.start(),
            })
    return problems


def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path) -> Path:
    markdown_text = fix_legacy_tex_bf(markdown_text)
    markdown_text = fix_broken_double_prime(markdown_text)
    problems = find_unbalanced_left_right(markdown_text)
    if problems:
        print(f"[CẢNH BÁO] {len(problems)} công thức lệch \\left/\\right "
              f"(sẽ không thành Equation, rớt về text thô):")
        for p in problems:
            snippet = p["formula"][:80].replace("\n", " ")
            print(f"  - vị trí ký tự {p['pos']}: left={p['n_left']} "
                  f"right={p['n_right']} | {snippet}...")
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


def set_font(docx_path: Path, font_name: str = "Times New Roman") -> Path:
    """Đổi toàn bộ font chữ trong DOCX (trừ công thức toán/Equation - giữ
    nguyên Cambria Math để hiển thị đúng ký hiệu) sang font_name.
    Áp dụng cho: style Normal + mọi style khác, mọi đoạn văn, bảng, header/footer."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def _apply_rfonts(rPr_owner):
        rPr = rPr_owner.get_or_add_rPr() if hasattr(rPr_owner, "get_or_add_rPr") else rPr_owner
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is None:
            rFonts = OxmlElement("w:rFonts")
            rPr.append(rFonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rFonts.set(qn(attr), font_name)

    def _set_run_font(run):
        run.font.name = font_name
        _apply_rfonts(run._element)

    doc = Document(str(docx_path))

    # Style mặc định (Normal, Heading...) - để text mới gõ thêm cũng theo font này
    for style in doc.styles:
        try:
            style.font.name = font_name
            _apply_rfonts(style.element)
        except Exception:
            continue

    def _walk_paragraphs(paragraphs):
        for p in paragraphs:
            for r in p.runs:
                _set_run_font(r)

    _walk_paragraphs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _walk_paragraphs(cell.paragraphs)
    for section in doc.sections:
        _walk_paragraphs(section.header.paragraphs)
        _walk_paragraphs(section.footer.paragraphs)

    doc.save(str(docx_path))
    print(f"Đã đổi font sang {font_name}: {docx_path}")
    return docx_path


def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path,
                number_pages: bool = True, font_name: str = "Times New Roman") -> Path:
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
    if font_name:
        set_font(docx_path, font_name)
    if number_pages:
        add_page_numbers(docx_path)
    return docx_path