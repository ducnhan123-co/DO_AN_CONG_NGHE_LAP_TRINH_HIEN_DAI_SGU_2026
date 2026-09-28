"""Bước 5-7 notebook: chuẩn hoá ảnh + Markdown -> DOCX Equation thật via Pandoc."""
import re
import subprocess
from pathlib import Path    
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE

try:
    from .config import PANDOC_FROM
except ImportError:
    from config import PANDOC_FROM


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


# Một số đoạn trong PDF gốc được gõ bằng font Việt kiểu cũ (VNI-Times/TCVN3)
# thay vì Unicode, nên khi trích xuất text bị "mojibake" (ví dụ: đó -> ñoù,
# đóng -> ñoùng, không -> khoâng, Nếu -> Neáu...). Lỗi này KHÔNG đều trong
# toàn tài liệu (cùng một chữ chỗ đúng chỗ sai), nên không dùng một bảng mã
# tổng quát để convert (dễ làm hỏng ngược những chỗ đang đúng). Thay vào đó,
# đây là danh sách các từ đã XÁC NHẬN bị lỗi trong tài liệu, thay đúng từng
# từ. Nếu gặp thêm từ lỗi mới không có trong bảng này, cần bổ sung thủ công.
LEGACY_VN_MOJIBAKE_MAP = {
    "Neáu": "Nếu", "neáu": "nếu", "neú": "nếu",
    "ñoù": "đó", "ñoùng": "đóng", "ñöôøng": "đường", "ñònh": "định",
    "chaën": "chặn", "khoâng": "không", "daãm": "dẫm", "leân": "lên",
    "laø": "là", "vaø": "và", "vaøo": "vào",
    "maët": "mặt", "daøi": "dài", "nöõa": "nữa",
    "vaønh": "vành", "troøn": "tròn", "chöùa": "chứa",
    "caùc": "các", "giaù": "giá", "giôùi": "giới",
    "khaên": "khăn", "caàu": "cầu",
    "thuoäc": "thuộc", "laáy": "lấy", "phaân": "phân", "dieän": "diện",
    "vvuông": "vuông", "hhoàn": "hoàn",
}


# Các cụm cần thay theo NGUYÊN CỤM (không phải từng từ đơn), vì từ bị lỗi
# trùng với một từ tiếng Việt hợp lệ khác trong ngữ cảnh chung (ví dụ "bò"
# nghĩa là con bò, nhưng trong cụm "ñoùng, bò chaën" thì đó là lỗi font của
# "bị chặn"). Áp dụng các cụm này TRƯỚC bảng từ đơn ở trên.
LEGACY_VN_MOJIBAKE_PHRASE_MAP = {
    "bò chaën": "bị chặn",
    "bò chặn": "bị chặn",  # phòng khi chaën đã được thay trước đó
    # OCR vừa lỗi font vừa lỡ tách rời/nhập chữ với ký hiệu đứng cạnh
    "ha ïn": "hạn",
    "ca ùc": "các",
    "ma ëtΩ": "mặt Ω",
    "maëtΩ": "mặt Ω",
    "ma ët": "mặt",
    "bôûi": "bởi",
}


def fix_legacy_vietnamese_mojibake(markdown_text: str) -> str:
    """Thay các từ/cụm tiếng Việt bị lỗi font cũ (xem
    LEGACY_VN_MOJIBAKE_PHRASE_MAP và LEGACY_VN_MOJIBAKE_MAP) bằng dạng
    Unicode đúng. Chỉ thay khớp nguyên từ/cụm (word boundary), không đụng
    tới các từ đang đúng khác trong tài liệu."""
    for bad, good in LEGACY_VN_MOJIBAKE_PHRASE_MAP.items():
        markdown_text = markdown_text.replace(bad, good)
    for bad, good in LEGACY_VN_MOJIBAKE_MAP.items():
        markdown_text = re.sub(
            r'(?<![\wàáâãèéêìíòóôõùúýăđĩũơưẠ-ỹ])' + re.escape(bad) +
            r'(?![\wàáâãèéêìíòóôõùúýăđĩũơưẠ-ỹ])',
            good, markdown_text)
    return markdown_text


_ARROW_RE = (r"(?:\\Longleftrightarrow|\\Leftrightarrow|\\Longrightarrow"
             r"|\\Rightarrow|\\Leftarrow)")
_DELIM_RE = (r"(?:\\langle|\\rangle|\\lceil|\\rceil|\\lfloor|\\rfloor"
             r"|\\\{|\\\}|[.\(\)\[\]\{\}\|])")
_CHAIN_TOKEN_RE = re.compile(
    r"(?P<left>\\left\s*" + _DELIM_RE + r")"
    r"|(?P<right>\\right\s*" + _DELIM_RE + r")"
    r"|(?P<endarr>\\end\{array\})(?P<sep>\s*)(?P<arrow>" + _ARROW_RE + r")"
)


def _fix_chained_systems_in_one_formula(formula: str) -> str:
    """Chạy trên ĐÚNG một công thức (một khối $$...$$ / \\[...\\] / $...$).
    MinerU OCR hay in một chuỗi hệ phương trình tương đương kiểu:
        \\left\\{ \\begin{array}{l} ... \\end{array} \\Leftrightarrow
        \\left\\{ \\begin{array}{l} ... \\end{array} \\right. \\Leftrightarrow ...
    và thỉnh thoảng làm rớt mất \\right. ngay sau \\end{array} của một vài hệ
    ở giữa chuỗi (trong khi các hệ khác trong CÙNG chuỗi vẫn có \\right. đầy
    đủ) -> \\left mở ra không đóng đúng chỗ, và phần \\right. bị thiếu đó
    thường trôi dạt thành một \\right. thừa/lạc chỗ ở cuối công thức (không
    đứng trước \\Leftrightarrow/\\Rightarrow nào).
    Cách xử lý (dựa trên số dư \\left đang mở, tính từ đầu ĐẾN CUỐI công thức
    này - không tính sang công thức khác):
      - Gặp \\end{array} rồi tới ngay mũi tên (⇔/⇒/⇐) mà đang có \\left chưa
        đóng -> chèn \\right. vào giữa.
      - Gặp \\right... khi không có \\left nào đang mở (số dư = 0) -> đây là
        \\right thừa do lỗi kiểu trên dạt tới, bỏ hẳn đi.
    Không đổi gì nếu công thức đã cân bằng sẵn."""
    if formula.count("\\left") == formula.count("\\right"):
        return formula  # đã cân bằng, không đụng vào

    out = []
    last = 0
    balance = 0
    changed = False
    for m in _CHAIN_TOKEN_RE.finditer(formula):
        out.append(formula[last:m.start()])
        if m.group("left"):
            balance += 1
            out.append(m.group("left"))
        elif m.group("right"):
            if balance > 0:
                balance -= 1
                out.append(m.group("right"))
            else:
                changed = True  # bỏ \right thừa/lạc chỗ
        else:
            out.append(m.group("endarr"))
            if balance > 0:
                out.append(r" \right.")
                balance -= 1
                changed = True
            out.append(m.group("sep"))
            out.append(m.group("arrow"))
        last = m.end()
    out.append(formula[last:])
    fixed = "".join(out)
    # Chỉ nhận kết quả nếu sau khi sửa công thức thực sự cân bằng và có thay
    # đổi thật; nếu không (ví dụ lệch \\left/\\right do lý do khác, không
    # phải mẫu chuỗi hệ phương trình này) thì giữ nguyên bản gốc để tránh
    # sửa sai, và find_unbalanced_left_right() vẫn sẽ báo cho người dùng.
    if changed and fixed.count("\\left") == fixed.count("\\right"):
        return fixed
    return formula


def fix_missing_right_in_chained_systems(markdown_text: str) -> str:
    """Áp dụng _fix_chained_systems_in_one_formula cho từng công thức riêng
    lẻ trong toàn bộ tài liệu (dùng FORMULA_RE để tách đúng phạm vi $$...$$,
    \\[...\\], $...$ - KHÔNG đếm \\left/\\right dồn xuyên suốt cả file, vì
    lỗi lệch ngoặc ở công thức này không được phép ảnh hưởng tới công thức
    khác)."""
    return FORMULA_RE.sub(
        lambda m: _fix_chained_systems_in_one_formula(m.group(0)),
        markdown_text)


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
    markdown_text = fix_legacy_vietnamese_mojibake(markdown_text)
    markdown_text = fix_missing_right_in_chained_systems(markdown_text)
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


def justify_paragraphs(docx_path: Path) -> Path:
    """Căn đều hai lề (justify) cho toàn bộ đoạn văn trong DOCX: nội dung
    chính, các cell trong bảng, header/footer. Bỏ qua các đoạn đã được
    Pandoc căn giữa/phải chủ đích (heading canh giữa, hình ảnh, mục lục,
    v.v.) để không phá layout của những phần đó."""


    SKIP_ALIGNMENTS = {WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.RIGHT}

    doc = Document(str(docx_path))

    # Style mặc định (Normal...) - để đoạn mới gõ thêm cũng tự căn đều
    for style in doc.styles:
        if style.type == WD_STYLE_TYPE.PARAGRAPH:
            try:
                if style.paragraph_format.alignment not in SKIP_ALIGNMENTS:
                    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            except Exception:
                continue

    def _walk_paragraphs(paragraphs):
        for p in paragraphs:
            if p.alignment in SKIP_ALIGNMENTS:
                continue
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    _walk_paragraphs(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                _walk_paragraphs(cell.paragraphs)
    for section in doc.sections:
        _walk_paragraphs(section.header.paragraphs)
        _walk_paragraphs(section.footer.paragraphs)

    doc.save(str(docx_path))
    print(f"Đã căn đều hai lề: {docx_path}")
    return docx_path


def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path,
                number_pages: bool = True, font_name: str = "Times New Roman",
                justify: bool = True) -> Path:
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
    if justify:
        justify_paragraphs(docx_path)
    if number_pages:
        add_page_numbers(docx_path)
    return docx_path