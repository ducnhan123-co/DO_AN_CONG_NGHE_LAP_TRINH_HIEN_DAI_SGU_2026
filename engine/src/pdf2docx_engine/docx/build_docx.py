# Cách 2
"""Bước 5-7 notebook: chuẩn hoá ảnh + Markdown -> DOCX Equation thật via Pandoc."""
import re
import subprocess
from pathlib import Path

from ..config import PANDOC_FROM


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


# ---------------------------------------------------------------------------
# FIX TRANG "ĐÁP SỐ" (bảng đáp số nhiều cột)
# ---------------------------------------------------------------------------
# PDF gốc trình bày đáp số thành lưới ~5 cột. MinerU đọc theo thứ tự "zig-zag"
# nên: (1) thứ tự bị xáo (1a,1b,1f,1g,1c,1e...), (2) MỖI ô thành một khối
# $$...$$ riêng -> mỗi đáp số một dòng, chữ nghiêng kiểu công thức.
# Cách sửa: gom các khối $$ liền nhau sau tiêu đề "ĐÁP SỐ", tách từng mục
# (nhãn + giá trị), SẮP XẾP lại theo (số câu, chữ cái), rồi dựng lại thành
# bảng 5 cột (mỗi câu một hàng, hàng dài thì tự xuống hàng).
ANSWER_HEADING_RE = re.compile(r"^#{1,6}\s*ĐÁP\s*SỐ\s*$", re.IGNORECASE)
_GREEK = {"": 0, "\\alpha": 1, "\\beta": 2, "\\gamma": 3}
_ANS_LABEL_RE = re.compile(
    r"(?P<num>\d(?:\s?\d)?)\s*(?P<let>[a-z])?\s*(?P<greek>\\alpha|\\beta|\\gamma|α|β|γ)?\s*\)")
_GREEK_UNI = {"α": "\\alpha", "β": "\\beta", "γ": "\\gamma"}


def _clean_answer_block(body: str) -> str:
    """Bỏ các lớp bọc rác do OCR (\\underline, \\left|..\\right|, \\text,
    \\mathbf, \\mathrm, \\begin{array}...) để chỉ còn 'nhãn) giá trị'."""
    b = body.strip()
    b = re.sub(r"\\begin\{array\}\{[^}]*\}|\\end\{array\}", " ", b)
    b = re.sub(r"\\left\s*[|.]|\\right\s*[|.]", " ", b)
    b = re.sub(r"\\(quad|qquad)|\\\\|&", " ", b)
    for _ in range(3):  # bóc lồng nhau: \underline{{ ... }}
        b = re.sub(r"\\(?:underline|text|mathbf|mathrm|textbf)\s*\{([^{}]*)\}",
                   r"\1", b)
        b = re.sub(r"\{\{([^{}]*)\}\}", r"\1", b)
    return b.strip()


def _parse_answer_entries(body: str) -> list:
    """Một khối có thể chứa 1 hoặc nhiều mục (vd '2d) ... 2e) ...')."""
    b = _clean_answer_block(body)
    # "(6aα)" bọc ngoặc ngoài -> bỏ ngoặc mở thừa trước nhãn
    b = re.sub(r"^\(\s*(?=\d)", "", b)
    # Chỉ nhận một "nhãn" khi phần giá trị đứng trước nó có ngoặc cân bằng;
    # nếu không, ')' đó chỉ là ngoặc đóng của biểu thức, vd '(\\sqrt{2} - 1)'.
    ms, last_end = [], 0
    for m in _ANS_LABEL_RE.finditer(b):
        if m.start() < last_end:
            continue
        before = b[last_end:m.start()]
        if before.count("(") != before.count(")"):
            continue
        ms.append(m)
        last_end = m.end()
    entries = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(b)
        value = b[m.end():end].strip()
        num = re.sub(r"\s", "", m.group("num"))
        let = m.group("let") or ""
        greek = m.group("greek") or ""
        greek = _GREEK_UNI.get(greek, greek)  # 'α' -> '\\alpha'
        if not let and len(num) == 2 and num[1] == "1":
            num, let = num[0], "l"  # OCR đọc '3l)' thành '3 1)'
        if not let or not value:
            continue
        if value.count("\\right") > value.count("\\left"):   # \right dư do OCR: '...\right\}'
            value = re.sub(r"\\right\s*(?:\\[{}|]|[.|)\]])?\s*$", "", value)
        value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)  # '1 1 \\pi / 3 2' -> '11 \\pi / 32'
        entries.append({"num": int(num), "let": let, "greek": greek,
                        "value": value.lstrip(" \t").rstrip(" .\t\\")})
    return entries


def _entries_to_table(entries: list, ncols: int = 5) -> str:
    entries = sorted(entries, key=lambda e: (e["num"], e["let"], _GREEK.get(e["greek"], 9)))
    rows, cur_num, cur = [], None, []
    for e in entries:
        if cur_num is not None and e["num"] != cur_num:
            rows.append(cur)
            cur = []
        cur_num = e["num"]
        cur.append(e)
    if cur:
        rows.append(cur)
    lines = ["| " + " | ".join([" "] * ncols) + " |",
             "|" + "|".join(["---"] * ncols) + "|"]
    for group in rows:
        for i in range(0, len(group), ncols):  # câu >5 ý (vd câu 1, 3) xuống hàng
            chunk = group[i:i + ncols]
            cells = []
            for e in chunk:
                label = f"{e['num']}{e['let']}"
                if e["greek"]:
                    label += {"\\alpha": "α", "\\beta": "β", "\\gamma": "γ"}[e["greek"]]
                v = e["value"]
                cells.append(f"{label}) ${v}$" if re.search(r"[A-Za-z0-9]", v) else f"{label}) {v}")
            cells += [" "] * (ncols - len(cells))
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


ANSWER_TAB = "§TAB§"  # không dùng @ vì Pandoc coi là citation
ANSWER_STYLE = "DapSo"


def _entries_to_tabbed(entries: list, ncols: int = 5) -> str:
    """Không dùng bảng: mỗi câu là 1 đoạn văn, các đáp số cách nhau bằng
    placeholder TAB (sau đó format_answer_key_paragraphs đổi thành tab thật)."""
    entries = sorted(entries, key=lambda e: (e["num"], e["let"], _GREEK.get(e["greek"], 9)))
    paras, cur_num, cur = [], None, []
    for e in entries:
        if cur_num is not None and e["num"] != cur_num:
            paras.append(cur)
            cur = []
        cur_num = e["num"]
        cur.append(e)
    if cur:
        paras.append(cur)
    out = ['::: {custom-style="%s"}' % ANSWER_STYLE]
    for group in paras:
        for i in range(0, len(group), ncols):
            items = []
            for e in group[i:i + ncols]:
                label = f"{e['num']}{e['let']}"
                if e["greek"]:
                    label += {"\\alpha": "α", "\\beta": "β", "\\gamma": "γ"}[e["greek"]]
                v = e["value"]
                items.append(f"{label}) ${v}$" if re.search(r"[A-Za-z0-9]", v) else f"{label}) {v}")
            out.append((" " + ANSWER_TAB + " ").join(items))
            out.append("")
    out.append(":::")
    return "\n".join(out)


_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _parse_pipe_table_entries(table_lines: list) -> list:
    """MinerU đôi khi nhận diện sẵn trang đáp số thành bảng markdown
    `| 1a) 4/3 | 1b) 3/2 | ... |`. Tách từng ô, bỏ dấu $ bọc ngoài, rồi parse
    như các khối $$ (mỗi ô là một hoặc nhiều mục 'nhãn) giá trị')."""
    entries = []
    for ln in table_lines:
        ln = ln.strip()
        if _TABLE_SEP_RE.match(ln):
            continue
        for cell in ln.strip("|").split("|"):
            cell = cell.replace("$", " ").strip()
            if cell:
                entries.extend(_parse_answer_entries(cell))
    return entries


def fix_answer_key_tables(markdown_text: str, layout: str = "tabs") -> str:
    """Tìm mục 'ĐÁP SỐ', gom các khối $$..$$ liền kề, sắp xếp lại và dựng bảng."""
    lines = markdown_text.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        out.append(lines[i])
        if ANSWER_HEADING_RE.match(lines[i].strip()):
            # Trường hợp 1: MinerU xuất sẵn BẢNG markdown ngay sau tiêu đề
            t = i + 1
            while t < n and not lines[t].strip():
                t += 1
            if t < n and lines[t].lstrip().startswith("|"):
                u = t
                while u < n and lines[u].lstrip().startswith("|"):
                    u += 1
                entries = _parse_pipe_table_entries(lines[t:u])
                if len(entries) >= 3:
                    out.append("")
                    out.append(_entries_to_tabbed(entries) if layout == "tabs"
                               else _entries_to_table(entries))
                    out.append("")
                    i = u
                    continue
            # Trường hợp 2: các khối $$...$$ rời rạc
            j, blocks = i + 1, []
            while j < n:
                if not lines[j].strip():
                    j += 1
                    continue
                if lines[j].strip() == "$$":
                    k = j + 1
                    while k < n and lines[k].strip() != "$$":
                        k += 1
                    if k >= n:
                        break
                    blocks.append("\n".join(lines[j + 1:k]))
                    j = k + 1
                    continue
                break
            entries = [e for b in blocks for e in _parse_answer_entries(b)]
            if len(entries) >= 3:
                out.append("")
                out.append(_entries_to_tabbed(entries) if layout == "tabs"
                           else _entries_to_table(entries))
                out.append("")
                i = j
                continue
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# TƯƠNG THÍCH TEXMATH + PHÂN LOẠI CÔNG THỨC CANH GIỮA / CANH TRÁI
# ---------------------------------------------------------------------------
# Pandoc dùng texmath, KHÔNG hiểu một số cú pháp MinerU hay xuất ra. Khi đó
# công thức rớt về chữ LaTeX thô trong DOCX. Các lỗi gặp thực tế:
#   \begin{array}{l l}  (khoảng trắng trong cột)  -> \begin{array}{ll}
#   \hline, \boxed{..}, \displaylimits, \tt, \bf{x}
#   \dot \mathbf{Y} / \vec \mathbf{F}  (accent không có {})
#   \hat{a} nằm trong \text{..}, và \right dư ở cuối.
def _unwrap_command(tex: str, cmd: str) -> str:
    """Bỏ lệnh `\\cmd{...}` nhưng giữ nội dung (có đếm ngoặc lồng)."""
    pat = re.compile(r"\\" + cmd + r"\s*\{")
    while True:
        m = pat.search(tex)
        if not m:
            return tex
        i, depth = m.end(), 1
        while i < len(tex) and depth:
            depth += {"{": 1, "}": -1}.get(tex[i], 0)
            i += 1
        tex = tex[:m.start()] + tex[m.end():i - 1] + tex[i:]


def fix_texmath_compat_one(tex: str) -> str:
    t = tex
    t = re.sub(r"\\begin\{array\}\s*\{([^}]*)\}",
               lambda m: "\\begin{array}{" + re.sub(r"\s+", "", m.group(1)) + "}", t)
    t = re.sub(r"\\hline\b", " ", t)
    nb = len(re.findall(r"\\begin\{array\}", t))
    ne = len(re.findall(r"\\end\{array\}", t))
    while ne > nb:                                   # OCR dư \end{array}
        k = t.rfind("\\end{array}")
        t = t[:k] + t[k + len("\\end{array}"):]
        ne -= 1
    if nb > ne:                                      # OCR thiếu \end{array}
        t = t + " \\end{array}" * (nb - ne)
    t = _unwrap_command(t, "boxed")
    t = t.replace("\\displaylimits", "")
    for _ in range(3):
        t = re.sub(r"\\bf\s*\{\s*([^{}]*?)\s*\}", r"\\mathbf{\1}", t)
        t = re.sub(r"\{\s*\\(?:tt|rm|it)\s+([^{}]+?)\s*\}", r"\\mathrm{\1}", t)
    t = re.sub(r"\\boldsymbol\b", r"\\mathbf", t)
    # accent không ngoặc: \dot \mathbf{Y} -> \dot{\mathbf{Y}}
    t = re.sub(r"\\(dot|ddot|vec|hat|bar|tilde|overline)\s*(\\mathbf\s*\{[^{}]*\}|\\[A-Za-z]+|[A-Za-z0-9])",
               r"\\\1{\2}", t)
    # accent trong \text{...}: \text{c\hat{a}u} -> \text{câu}
    acc = {"hat": "\u0302", "check": "\u030c", "tilde": "\u0303", "acute": "\u0301", "grave": "\u0300"}
    def _text_fix(m):
        body = re.sub(r"\\(hat|check|tilde|acute|grave)\s*\{(\w)\}",
                      lambda k: k.group(2) + acc[k.group(1)], m.group(1))
        return "\\text{" + body + "}"
    t = re.sub(r"\\text\s*\{((?:[^{}]|\{[^{}]*\})*)\}", _text_fix, t)
    if t.count("\\right") > t.count("\\left"):      # \right dư ở cuối
        t = re.sub(r"\\right\s*[.|]?\s*$", "", t)
    return t


_MATH_SPAN_RE = re.compile(r"\$\$.*?\$\$|(?<!\$)\$(?!\$)[^$\n]+?\$(?!\$)", re.S)


def fix_texmath_compat(markdown_text: str) -> str:
    def _sub(m):
        span = m.group(0)
        if span.startswith("$$"):
            return "$$" + fix_texmath_compat_one(span[2:-2]) + "$$"
        return "$" + fix_texmath_compat_one(span[1:-1]).strip() + "$"
    return _MATH_SPAN_RE.sub(_sub, markdown_text)


# --- Phân loại khối $$...$$: dòng chữ-có-nhãn (canh trái/2 lề) hay công thức thật (canh giữa)
MATH_LEFT_STYLE = "MathLeft"
_LABEL_START_RE = re.compile(
    r"^\s*(?:\\(?:mathrm|mathbf|text)\s*\{\s*)?(?:\d{1,2}\s*)?(?:\\(?:mathrm|mathbf|text)\s*\{\s*)?[A-Za-z]{1,2}\s*\}?\s*\}?\s*\)")
_BULLET_RE = re.compile(r"^\s*\\(?:bullet|cdot|circ)\b")


def _is_left_math_block(body: str) -> bool:
    """True nếu khối $$ thực chất là MỘT DÒNG VĂN BẢN có công thức (bài tập 'a) ∭ ...,
    Ω giới hạn bởi...', gạch đầu dòng, câu có chữ tiếng Việt) -> gốc canh trái/2 lề.
    False = công thức đứng riêng -> gốc canh giữa."""
    b = body.strip()
    if _LABEL_START_RE.match(b) or _BULLET_RE.match(b):
        return True
    if re.match(r"^\\text\s*\{", b):                  # mở đầu bằng chữ: 'Giải hệ {...'
        return True
    words = 0
    for t in re.findall(r"\\text\s*\{((?:[^{}]|\{[^{}]*\})*)\}", b):
        words += len(re.findall(r"[^\W\d_]{2,}", t))
    return words >= 6                                  # cả một câu dài -> dòng văn bản


def tag_left_math_blocks(markdown_text: str) -> str:
    """Bọc khối $$ kiểu 'dòng văn bản' trong div custom-style=MathLeft để
    post-process canh trái; khối còn lại giữ nguyên (Pandoc canh giữa)."""
    def _sub(m):
        body = m.group(1)
        if _is_left_math_block(body):
            return f'\n::: {{custom-style="{MATH_LEFT_STYLE}"}}\n$${body}$$\n:::\n'
        return m.group(0)
    return re.sub(r"(?<!:)\$\$(.*?)\$\$", _sub, markdown_text, flags=re.S)


def apply_math_alignment(docx_path: Path) -> Path:
    """Giữ công thức đứng riêng CANH GIỮA như bản gốc; chỉ các đoạn style
    MathLeft (dòng văn bản có công thức) mới đưa về canh trái/2 lề."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    doc = Document(str(docx_path))
    try:
        st = doc.styles[MATH_LEFT_STYLE]
        st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    except KeyError:
        st = None
    n_left = n_center = 0
    for p in doc.element.body.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        from docx.text.paragraph import Paragraph
        para = Paragraph(p, doc)
        is_left = para.style is not None and para.style.name == MATH_LEFT_STYLE
        for jc in p.iter(f"{{{MATH_NS}}}jc"):
            if is_left:
                jc.set(f"{{{MATH_NS}}}val", "left"); n_left += 1
            else:
                n_center += 1
        if is_left:
            para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.save(str(docx_path))
    print(f"Công thức: {n_center} canh giữa (như gốc), {n_left} canh trái/2 lề: {docx_path}")
    return docx_path


def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path) -> Path:
    markdown_text = fix_answer_key_tables(markdown_text)
    markdown_text = fix_legacy_tex_bf(markdown_text)
    markdown_text = fix_texmath_compat(markdown_text)
    markdown_text = tag_left_math_blocks(markdown_text)
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


def justify_math_paragraphs(docx_path: Path) -> Path:
    """Công thức đứng riêng 1 dòng ($$...$$) được Pandoc tự gắn
    `<m:oMathParaPr><m:jc m:val="center"/></m:oMathParaPr>` -> Word CĂN GIỮA
    công thức đó bất kể đoạn văn chứa nó có justify hay không, vì đây là
    thuộc tính căn chỉnh RIÊNG của Equation, nằm ngoài w:pPr/w:jc mà
    justify_paragraphs() chỉnh. Đổi toàn bộ "center" -> "left" để khớp lề
    trái của phần còn lại (equation 1 dòng thì left với justify nhìn như
    nhau, chỉ khác center mới lệch hẳn vào giữa trang)."""
    from docx import Document
 
    MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    doc = Document(str(docx_path))
    n = 0
    for jc in doc.element.body.iter(f"{{{MATH_NS}}}jc"):
        if jc.get(f"{{{MATH_NS}}}val") == "center":
            jc.set(f"{{{MATH_NS}}}val", "left")
            n += 1
    doc.save(str(docx_path))
    print(f"Đã bỏ căn giữa {n} công thức đứng riêng dòng: {docx_path}")
    return docx_path
 
 
def justify_paragraphs(docx_path: Path) -> Path:
    """Căn đều hai lề (justify) cho toàn bộ đoạn văn trong DOCX: nội dung
    chính, các cell trong bảng, header/footer. Bỏ qua các đoạn đã được
    Pandoc căn giữa/phải chủ đích (heading canh giữa, hình ảnh, mục lục,
    v.v.) để không phá layout của những phần đó."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.style import WD_STYLE_TYPE

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


def format_answer_key_paragraphs(docx_path: Path, ncols: int = 5,
                                 col_width_in: float = 1.3) -> Path:
    """Đổi placeholder TAB thành tab thật + đặt tab stop cho style DapSo,
    bỏ căn đều, và cho công thức đứng thẳng (không nghiêng) như PDF gốc."""
    from copy import deepcopy
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt

    MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    doc = Document(str(docx_path))
    try:
        style = doc.styles[ANSWER_STYLE]
    except KeyError:
        print("Không có style DapSo (không có mục ĐÁP SỐ) - bỏ qua.")
        return docx_path
    pf = style.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf.space_before = Pt(0)
    pf.space_after = Pt(6)
    for k in range(1, ncols):
        pf.tab_stops.add_tab_stop(Inches(col_width_in * k))

    n_tab = 0
    for p in doc.paragraphs:
        if p.style.name != ANSWER_STYLE:
            continue
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for t in list(p._p.iter(qn("w:t"))):
            if t.text and ANSWER_TAB in t.text:
                parts = t.text.split(ANSWER_TAB)
                t.text = parts[0].rstrip()
                t.set(qn("xml:space"), "preserve")
                anchor = t
                for part in parts[1:]:
                    tab = OxmlElement("w:tab")
                    anchor.addnext(tab)
                    nt = OxmlElement("w:t")
                    nt.set(qn("xml:space"), "preserve")
                    nt.text = part.lstrip()
                    tab.addnext(nt)
                    anchor = nt
                    n_tab += 1
        # công thức đứng thẳng: <m:rPr><m:sty m:val="p"/></m:rPr>
        for r in p._p.iter(f"{{{MATH_NS}}}r"):
            rpr = r.find(f"{{{MATH_NS}}}rPr")
            if rpr is None:
                rpr = OxmlElement("m:rPr")
                r.insert(0, rpr)
            if rpr.find(f"{{{MATH_NS}}}sty") is None:
                sty = OxmlElement("m:sty")
                sty.set(f"{{{MATH_NS}}}val", "p")
                rpr.insert(0, sty)
    doc.save(str(docx_path))
    print(f"Đã dựng lại trang ĐÁP SỐ bằng tab stop ({n_tab} tab): {docx_path}")
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
        apply_math_alignment(docx_path)
    format_answer_key_paragraphs(docx_path)
    if number_pages:
        add_page_numbers(docx_path)
    return docx_path