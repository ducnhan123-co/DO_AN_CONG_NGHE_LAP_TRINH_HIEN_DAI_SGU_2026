"""Sửa lỗi OCR + công thức trên Markdown của MinerU, TRƯỚC khi đưa vào Pandoc.

Chạy được hoàn toàn offline, thuần regex/thống kê, không cần GPU. Gồm 4 bước:

1. merge_fragmented_math   : `x$^{7}$`, `(1+x)$^{11}$`, `x$^{5}$y$^{8}$`  ->  `$x^{7}$`, `$(1+x)^{11}$`, `$x^{5}y^{8}$`
   (MinerU nhận "x" là chữ thường nhưng số mũ là công thức => Word hiện "x   ⁷" có khoảng trống,
   lệch font so với các công thức khác.)
2. fix_problem_labels       : "nǐ 52", "Bai 52", "Pai 54"  ->  "Bài 53.", "Bài 52.", "Bài 54."
   (dựa vào dãy số thứ tự liên tiếp của đề bài + dạng chữ gần giống "Bài")
3. fix_diacritics_by_context: "Tím hệ số" -> "Tìm hệ số" (bỏ phiếu theo ngữ cảnh toàn tài liệu + từ điển toán)
4. promote_tall_inline_math : công thức inline có hệ/ma trận nhiều dòng -> display math
   (Word cắt mất dòng đầu / góc ngoặc nhọn của hệ phương trình khi nó nằm inline trong dòng chữ.)

Hàm chính: repair_markdown(md) -> (md_moi, report_dict)
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

# ----------------------------------------------------------------------------
# Tiện ích: tách phần "ngoài công thức" để regex không chạm vào LaTeX
# ----------------------------------------------------------------------------
_MATH_SPLIT = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)


def _map_text_only(md: str, fn):
    """Áp fn cho các đoạn NGOÀI công thức; đoạn trong $...$ / $$...$$ giữ nguyên."""
    parts = _MATH_SPLIT.split(md)
    for i in range(0, len(parts), 2):
        parts[i] = fn(parts[i])
    return "".join(parts)


# ----------------------------------------------------------------------------
# 1. Gộp công thức bị MinerU chẻ vụn
# ----------------------------------------------------------------------------
# base: chữ/số đứng sát ngay trước `$^{..}$` hoặc `$_{..}$`, hoặc cụm (...)/[...] không lồng
_SUP = r"\$\s*([\^_])\s*\{([^{}$]*)\}\s*\$"
_BASE_PAREN = r"(\((?:[^()$\n]|\$[^$\n]*\$)*\)|\[(?:[^\[\]$\n])*\])"
_BASE_ATOM = r"([A-Za-z]{1,6}|[0-9]+)"


def merge_fragmented_math(md: str) -> tuple[str, int]:
    n = 0

    def sub_paren(m):
        nonlocal n
        n += 1
        inner = m.group(1).replace("$", "")
        return f"${inner}{m.group(2)}{{{m.group(3)}}}$"

    _FUNCS = {"sin", "cos", "tan", "cot", "ln", "log", "lim", "max", "min", "arcsin", "arccos", "arctan"}

    def sub_atom(m):
        nonlocal n
        n += 1
        base, op, exp = m.group(1), m.group(2), m.group(3)
        if base.lower() in _FUNCS:
            base = "\\" + base.lower()
        if op == "^" and exp.strip() in ("0", "o", "\\circ") and base.isdigit():
            exp = "\\circ"                       # 90$^{0}$ -> 90^{\circ}
        return f"${base}{op}{{{exp}}}$"

    # (x^3 - xy)$^{15}$ -> $(x^3 - xy)^{15}$     (chỉ khi cặp ngoặc nằm ngoài công thức)
    md = re.sub(_BASE_PAREN + _SUP, sub_paren, md)
    # x$^{7}$ -> $x^{7}$
    md = re.sub(r"(?<![\\\w$])" + _BASE_ATOM + _SUP, sub_atom, md)

    # $x^{5}$y$^{8}$  hoặc  $x^{5}$y  -> gộp các mảnh dính sát nhau thành 1 công thức
    glue = re.compile(r"\$([^$\n]+?)\$(?=[A-Za-z0-9(]?\$)")  # chỉ để dò, gộp bên dưới

    def merge_adjacent(text: str) -> str:
        nonlocal n
        # $A$ + (0-1 ký tự chữ/số) + $B$  ->  $A c B$   (không khoảng trắng giữa => cùng 1 biểu thức)
        pat = re.compile(r"\$([^$\n]+?)\$([A-Za-z0-9]?)\$([^$\n]+?)\$")
        prev = None
        while prev != text:
            prev = text

            def j(m):
                nonlocal n
                if m.group(2) == "" and not (m.group(1).rstrip()[-1:] in "}" and m.group(3).lstrip()[:1] in "^_"):
                    return m.group(0)       # hai công thức liền nhau không phải mảnh vỡ -> để yên
                n += 1
                return f"${m.group(1)}{m.group(2)}{m.group(3)}$"

            text = pat.sub(j, text)
        return text

    md = merge_adjacent(md)
    # $\sin^{2}$x  ->  $\sin^{2}x$   (biến đơn đứng sát sau hàm lượng giác)
    md = re.sub(r"\$(\\(?:sin|cos|tan|cot|ln|log|arcsin|arccos|arctan)\^\{[^{}]*\})\$([A-Za-z])(?![A-Za-z])",
                r"$\1 \2$", md)
    md = re.sub(r"\$(\\(?:sin|cos|tan|cot|ln|log)\^\{[^{}]*\})\$ ([A-Za-z])(?![A-Za-z])", r"$\1 \2$", md)
    return md, n


# ----------------------------------------------------------------------------
# 2. Nhãn "Bài N." bị OCR sai
# ----------------------------------------------------------------------------
_LABEL_WORD = ("bài", "bai")


def _strip(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def _looks_like_bai(tok: str) -> bool:
    """'Bai','Pai','nǐ','Bi','Bài','Ba1','Bãi'... - gần giống 'Bài' (khoảng cách ≤ 2 trên dạng bỏ dấu)."""
    t = _strip(tok)
    if not 1 <= len(t) <= 4:
        return False
    if t in ("bai", "ba", "bi"):
        return True
    # lệch 1 ký tự so với "bai" (pai, bal, ba1, nai...) hoặc "ni"/"ni" từ "nǐ"
    def lev1(a, b):
        if abs(len(a) - len(b)) > 1:
            return False
        if len(a) == len(b):
            return sum(x != y for x, y in zip(a, b)) <= 1
        s, l = (a, b) if len(a) < len(b) else (b, a)
        return any(l[:i] + l[i + 1:] == s for i in range(len(l)))
    return lev1(t, "bai") or t in ("ni", "ai")


_LABEL_LINE = re.compile(r"^(?P<lead>\s*(?:\*\*)?)(?P<tok>[^\W\d_]{1,4})\.?\s*(?P<num>\d{1,3})(?P<tail>\s*[.:,)]?\s*(?:\*\*)?\s*)(?P<rest>.*)$")


def fix_problem_labels(md: str) -> tuple[str, list]:
    """Sửa nhãn đề bài dựa trên dãy số liên tiếp: Bài 51, [nǐ 52], Bai 52, Pai 54  ->  51, 52?, ..."""
    lines = md.split("\n")
    # 1) thu các dòng "Bài <số>." chuẩn để biết dãy
    std = re.compile(r"^\s*(?:\*\*)?Bài\s+(\d{1,3})\s*[.:)]")
    seq = []
    for i, l in enumerate(lines):
        m = std.match(l)
        if m:
            seq.append((i, int(m.group(1))))
    fixes = []
    if len(seq) < 5:
        return md, fixes
    # 2) dòng ứng viên: token gần giống "Bài" + số, nhưng KHÔNG phải nhãn chuẩn
    for i, l in enumerate(lines):
        if std.match(l):
            continue
        m = _LABEL_LINE.match(l)
        if not m or not _looks_like_bai(m.group("tok")):
            continue
        # láng giềng chuẩn gần nhất phía trước/sau
        prev = max(((j, v) for j, v in seq if j < i), default=None, key=lambda t: t[0])
        nxt = min(((j, v) for j, v in seq if j > i), default=None, key=lambda t: t[0])
        read = int(m.group("num"))
        expect = None
        if prev and nxt and nxt[1] - prev[1] == 2:
            expect = prev[1] + 1                     # chỉ có đúng 1 số hợp lệ ở giữa
        elif prev and abs(read - prev[1]) <= 1:
            expect = prev[1] + 1 if read != prev[1] + 1 else read
        else:
            expect = read
        # Tránh hồi tố sai: nếu số đọc được đã nằm trong dãy chuẩn ở chỗ khác (trùng) và ta không suy ra được chỗ -> dùng expect
        new = f"{m.group('lead')}Bài {expect}.{' ' if m.group('rest') else ''}{m.group('rest')}"
        new = new.replace("**Bài", "**Bài")
        fixes.append({"line": i + 1, "old": l[:60], "new": new[:60]})
        lines[i] = new
        seq.append((i, expect))
        seq.sort()
    # 3) nhãn "Bai N" (thiếu dấu) có dạng chuẩn hơn nhưng sai dấu
    for i, l in enumerate(lines):
        m = re.match(r"^(\s*(?:\*\*)?)(Bai|Bài|Bãi|Bải|Bái|Bại)(\s+\d{1,3}\s*[.:)])", l)
        if m and m.group(2) != "Bài":
            fixes.append({"line": i + 1, "old": l[:40], "new": "Bài" + l[len(m.group(1)) + len(m.group(2)):][:36]})
            lines[i] = m.group(1) + "Bài" + l[len(m.group(1)) + len(m.group(2)):]
    return "\n".join(lines), fixes


# ----------------------------------------------------------------------------
# 3. Sửa dấu tiếng Việt: CHỈ khớp nguyên cụm đặc trưng của đề toán
# ----------------------------------------------------------------------------
# Bài học rút ra khi thử trên dữ liệu thật: sửa theo từng từ / từng cặp từ gây lỗi MỚI
# ("chữ số hàng nghìn" -> "hạng nghìn", "gia tốc" -> "giá tốc", "đánh số từ 1" -> "tự").
# Vì vậy chỉ thay khi TOÀN BỘ cụm (>= 2 từ, có từ không có từ đồng âm hợp lệ) khớp sau khi bỏ dấu.
_GOLD_PHRASES = [
    "tìm hệ số", "tìm tập xác định", "tìm giá trị lớn nhất", "tìm giá trị nhỏ nhất", "tìm giá trị",
    "khai triển", "nhị thức", "chứng minh", "giải phương trình", "giải bất phương trình",
    "giải hệ phương trình", "hệ phương trình", "bất phương trình", "tính đạo hàm", "tính tích phân",
    "cho hàm số", "biết rằng", "số nguyên dương", "số tự nhiên", "tập nghiệm", "sai lầm",
    "giá trị lớn nhất", "giá trị nhỏ nhất", "phương trình", "một số sai lầm", "tập xác định",
]
# Từ mở đầu câu mà OCR hay đọc sai và KHÔNG có nghĩa khác trong đề toán: chỉ sửa ở đầu dòng / sau nhãn "Bài N." "Câu N."
_SENT_START_FIX = {"tím": "Tìm", "tîm": "Tìm", "tỉm": "Tìm", "tĩm": "Tìm", "tim": "Tìm"}
_TOKEN = re.compile(r"[^\W\d_]+", re.U)
_EQUIV = {"thỏa": ("thoả",), "thoả": ("thỏa",), "hòa": ("hoà",), "hoà": ("hòa",)}
_LEAD = re.compile(r"^\s*(?:\*\*)?(?:(?:Bài|Câu|Ví dụ)\s*\d*\s*[.:)]?\s*(?:\*\*)?\s*|[a-hA-H][.)]\s*|\d{1,3}[.)]\s*)?")


def _words(text: str):
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def fix_diacritics_by_context(md: str, **_ignored) -> tuple[str, list]:
    phrases = [(tuple(_strip(w) for w in ph.split()), ph.split()) for ph in _GOLD_PHRASES]
    phrases.sort(key=lambda t: -len(t[0]))            # cụm dài trước
    fixes = []

    def fix_line(text: str, is_line_start: bool) -> str:
        ws = _words(text)
        repl = []                                         # (start, end, new)
        taken = set()
        for k in range(len(ws)):
            for key, ph in phrases:
                L = len(key)
                if k + L > len(ws) or any((k + j) in taken for j in range(L)):
                    continue
                if tuple(_strip(ws[k + j][0]) for j in range(L)) != key:
                    continue
                # các từ phải sát nhau, chỉ cách bằng khoảng trắng
                if any(text[ws[k + j][2]:ws[k + j + 1][1]].strip() for j in range(L - 1)):
                    continue
                for j in range(L):
                    w, st, en = ws[k + j]
                    new = ph[j]
                    if new in _EQUIV.get(w.lower(), ()) or new == w.lower():
                        continue
                    if j == 0 and w[:1].isupper():
                        new = new[:1].upper() + new[1:]
                    repl.append((st, en, new)); fixes.append({"old": w, "new": new})
                    taken.add(k + j)
                taken.update(range(k, k + L))
                break
        # từ đầu câu hay bị đọc sai "Tìm"
        if is_line_start and ws:
            lead = _LEAD.match(text)
            for w, st, en in ws[:3]:
                if st >= lead.end() and w.lower() in _SENT_START_FIX and (st, en) not in [(r[0], r[1]) for r in repl]:
                    repl.append((st, en, _SENT_START_FIX[w.lower()])); fixes.append({"old": w, "new": _SENT_START_FIX[w.lower()]})
                    break
                if st >= lead.end():
                    break
        for st, en, new in sorted(repl, reverse=True):
            text = text[:st] + new + text[en:]
        return text

    # áp theo từng dòng, chỉ trên phần ngoài công thức
    out_lines = []
    for ln in md.split("\n"):
        parts = _MATH_SPLIT.split(ln)
        for i in range(0, len(parts), 2):
            parts[i] = fix_line(parts[i], is_line_start=(i == 0))
        out_lines.append("".join(parts))
    return "\n".join(out_lines), fixes


# ----------------------------------------------------------------------------
# 4. Công thức inline có hệ/ma trận nhiều dòng -> display
# ----------------------------------------------------------------------------
_TALL_ENV = re.compile(r"\\begin\{(array|cases|matrix|pmatrix|bmatrix|vmatrix|aligned|gathered)\}")


def promote_tall_inline_math(md: str) -> tuple[str, int]:
    """`- $A \\Leftrightarrow \\left\\{\\begin{array}...\\\\...\\end{array}\\right.$ tail`
    -> đoạn riêng + $$A \\Leftrightarrow ...$$ + đoạn riêng. Display math không bị cắt dòng trong Word.
    Bỏ qua dòng bảng (|), tiêu đề (#) và dòng đã là display math."""
    n = 0
    out = []
    inline = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)")
    marker_only = re.compile(r"^(?:\\?[-*•+]|\d{1,2}[.)]|[a-hA-H][.)])$")
    in_display = False
    for line in md.split("\n"):
        st = line.strip()
        if st.count("$$") % 2 == 1:
            in_display = not in_display
            out.append(line)
            continue
        if in_display or st.startswith(("|", "#", "$$")) or "$" not in line:
            out.append(line)
            continue
        hit = None
        for m in inline.finditer(line):
            body = m.group(1)
            if _TALL_ENV.search(body) and body.count("\\\\") >= 1:
                hit = m
                break
        if not hit:
            out.append(line)
            continue
        n += 1
        before = line[: hit.start()].rstrip()
        after = line[hit.end():].strip()
        body = hit.group(1).strip()
        if before and marker_only.match(before):      # chỉ là dấu đầu dòng -> đưa vào trong công thức
            body = "\\text{" + before.lstrip("\\") + "}\\ \\ " + body
            before = ""
        if before:
            out.append(before + "\n")
        out.append("$$\n" + body + "\n$$\n")
        if after:
            out.append(after)
    return "\n".join(out), n


# ----------------------------------------------------------------------------
# 5. Công thức suy biến (MinerU kẹt vòng lặp: \\left.\\left.\\left. ... hàng chục nghìn ký tự)
# ----------------------------------------------------------------------------
_DEGEN = re.compile(r"(\\[A-Za-z]+\.?)\1{7,}|(\\left\.|\\right\.){8,}")


def strip_degenerate_formulas(md: str) -> tuple[str, list]:
    removed = []

    def drop(m):
        body = m.group(0)
        if _DEGEN.search(body):
            removed.append(len(body))
            return ""
        return body

    md = re.sub(r"\\\((?:.|\n)*?\\\)", drop, md)          # \( ... \)
    md = re.sub(r"\$\$(?:.|\n)*?\$\$", drop, md)            # $$ ... $$
    md = re.sub(r"(?<!\$)\$(?!\$)[^$\n]+?\$(?!\$)", drop, md)
    # công thức bị cắt cụt (không có dấu đóng): bỏ phần lặp đến hết dòng
    def cut_line(line: str) -> str:
        m = _DEGEN.search(line)
        if not m or len(line) < 300:
            return line
        start = max(line.rfind("\\(", 0, m.start()), line.rfind("$", 0, m.start()))
        removed.append(len(line) - max(start, 0))
        return line[:max(start, 0)]

    md = "\n".join(cut_line(l) for l in md.split("\n"))
    return md, removed


# ----------------------------------------------------------------------------
def repair_markdown(md: str, *, promote_tall: bool = True) -> tuple[str, dict]:
    report: dict = {}
    md, report["degenerate_removed"] = strip_degenerate_formulas(md)
    md, report["merged_math_fragments"] = merge_fragmented_math(md)
    md, report["label_fixes"] = fix_problem_labels(md)
    md, report["diacritic_fixes"] = fix_diacritics_by_context(md)
    if promote_tall:
        md, report["tall_inline_promoted"] = promote_tall_inline_math(md)
    return md, report