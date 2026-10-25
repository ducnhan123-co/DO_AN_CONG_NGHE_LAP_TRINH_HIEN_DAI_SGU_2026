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
# 2. Nhãn "Bài N." / "Câu N." bị OCR sai - TỰ HỌC nhãn từ chính tài liệu
# ----------------------------------------------------------------------------
# Ý tưởng (không ghi cứng chữ "Bài"): trong một tài liệu bài tập, có một "từ đầu dòng" lặp đi lặp lại
# trước một dãy số TĂNG DẦN 1,2,3,... Từ nào có dãy như vậy chính là nhãn (Bài / Câu / Ví dụ / Problem...).
# Sau khi biết nhãn, dòng nào bắt đầu bằng một "chữ gần giống nhãn" + số khớp chỗ đang thiếu trong dãy
# thì được hiểu là nhãn bị OCR sai ("Bi 57", "Ba i 57", "B à i 57", "Rài 57" -> "Bài 57.").
# Hai tín hiệu phải cùng đúng: (1) chữ gần giống nhãn đã học, (2) số hợp lý với dãy xung quanh.
def _strip(s: str) -> str:
    """Bỏ dấu tiếng Việt + hạ chữ thường: 'Bài' -> 'bai', 'Đề' -> 'de'."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


_HEAD_LINE = re.compile(
    r"^(?P<lead>\s*(?:\*\*)?)(?P<head>[^\W\d_]{1,8}(?:[ \t][^\W\d_]{1,3}){0,3})[ \t]*[.:]?[ \t]*"
    r"(?P<num>\d{1,3})(?P<tail>[ \t]*[.:,)]?[ \t]*(?:\*\*)?[ \t]*)(?P<rest>.*)$")


def _collapse(head: str) -> str:
    """'B à i' / 'Bài' / 'Bãi' -> 'bai' (bỏ khoảng trắng, dấu, hoa/thường)."""
    return re.sub(r"\s+", "", _strip(head))


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _learn_labels(lines, min_count: int = 5, min_seq: float = 0.6):
    """Trả {dạng_gộp: {"surface": chữ hay gặp nhất, "items": [(dòng, số)]}} cho các từ đầu dòng
    có dãy số tăng dần (>= min_seq số cặp liền kề cách đúng 1)."""
    groups: dict[str, dict] = {}
    for i, l in enumerate(lines):
        m = _HEAD_LINE.match(l)
        if not m:
            continue
        key = _collapse(m.group("head"))
        if len(key) < 2:
            continue
        g = groups.setdefault(key, {"items": [], "surfaces": Counter()})
        g["items"].append((i, int(m.group("num")), m.group("head").strip()))
        g["surfaces"][m.group("head").strip()] += 1
    learned = {}
    for key, g in groups.items():
        items = g["items"]
        if len(items) < min_count:
            continue
        nums = [n for _, n, _ in items]
        ok = sum(1 for x, y in zip(nums, nums[1:]) if y == x + 1)
        if ok / max(1, len(nums) - 1) >= min_seq:
            # chọn dạng viết có dấu đầy đủ & hay gặp nhất (không có khoảng trắng chen giữa)
            surf = max(g["surfaces"].items(), key=lambda kv: (" " not in kv[0], kv[1]))[0]
            share = g["surfaces"][surf] / sum(g["surfaces"].values())
            learned[key] = {"surface": surf, "items": list(items), "share": share}
    return learned


def fix_problem_labels(md: str, max_dist: int = 2) -> tuple[str, list]:
    lines = md.split("\n")
    learned = _learn_labels(lines)
    fixes = []
    if not learned:
        return md, fixes
    all_keys = set(learned)                      # "bai", "cau", "buoc"... đều là nhãn THẬT, không được đổi lẫn nhau
    for key, info in learned.items():
        if info["share"] < 0.7:                   # không có dạng viết áp đảo -> không đủ tin để chuẩn hoá
            continue
        # dãy "sạch" = các dòng viết ĐÚNG dạng phổ biến nhất; dòng cùng dạng gộp nhưng viết lạ
        # ("Ba i", "Bai", "B à i") không được dùng làm mốc, mà chính là đối tượng cần chuẩn hoá
        seq = sorted((i, n) for i, n, raw in info["items"] if raw == info["surface"])
        clean_lines = {i for i, _ in seq}
        for i, l in enumerate(lines):
            if i in clean_lines:
                continue
            m = _HEAD_LINE.match(l)
            if not m:
                continue
            head, read = m.group("head"), int(m.group("num"))
            ck = _collapse(head)
            if len(ck) < 2:                                # "A." "B." "C." = đáp án trắc nghiệm, không phải nhãn
                continue
            if ck != key and ck in all_keys:               # "Câu" không bao giờ bị đổi thành "Bài"
                continue
            dist = _edit_distance(ck, key)
            if dist > max_dist or dist >= len(key):        # quá khác nhãn (vd "Cho" vs "Bài") -> bỏ qua
                continue
            if len(ck) > len(key) + 2:
                continue
            prev = max(((j, v) for j, v in seq if j < i), default=None)
            nxt = min(((j, v) for j, v in seq if j > i), default=None)
            expect = None
            if prev and nxt and nxt[1] - prev[1] == 2:
                expect = prev[1] + 1                       # chỉ còn đúng 1 số hợp lệ ở giữa
            elif prev and nxt and prev[1] < read < nxt[1]:
                expect = read
            elif prev and read in (prev[1], prev[1] + 1):
                expect = prev[1] + 1
            elif nxt and read in (nxt[1], nxt[1] - 1):
                expect = nxt[1] - 1 if read == nxt[1] else read
            exact_gap = bool(prev and nxt and nxt[1] - prev[1] == 2 and expect == prev[1] + 1)
            if dist == 2 and not exact_gap:                # lệch 2 ký tự chỉ chấp nhận khi dãy số chỉ còn đúng 1 chỗ trống
                continue
            if expect is None:
                if dist == 0:                              # chỉ sai dấu/khoảng trắng của chữ nhãn
                    expect = read
                else:
                    continue
            rest = m.group("rest")
            if rest.startswith(("(", ")")) and not rest.startswith("("):
                pass
            new = f"{m.group('lead')}{info['surface']} {expect}.{' ' if rest else ''}{rest}"
            if new != l:
                fixes.append({"line": i + 1, "old": l[:60], "new": new[:60], "label": info["surface"]})
                lines[i] = new
                seq.append((i, expect))
                seq.sort()
                clean_lines.add(i)
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
_B64 = re.compile(r"\]\(data:image/[^)]*\)")


def repair_markdown(md: str, *, promote_tall: bool = True) -> tuple[str, dict]:
    """Ảnh nhúng base64 (hàng triệu ký tự) được cất ra trước khi sửa rồi trả lại sau:
    không cất thì các regex phải quét qua chúng -> chậm hàng chục giây và vô ích."""
    stash: list[str] = []

    def _hide(m):
        stash.append(m.group(0))
        return f"](@@IMG{len(stash) - 1}@@)"

    md = _B64.sub(_hide, md)
    md, report = _repair_markdown(md, promote_tall=promote_tall)
    if stash:
        md = re.sub(r"\]\(@@IMG(\d+)@@\)", lambda m: stash[int(m.group(1))], md)
    return md, report


def _repair_markdown(md: str, *, promote_tall: bool = True) -> tuple[str, dict]:
    report: dict = {}
    md, report["degenerate_removed"] = strip_degenerate_formulas(md)
    md, report["merged_math_fragments"] = merge_fragmented_math(md)
    md, report["label_fixes"] = fix_problem_labels(md)
    md, report["diacritic_fixes"] = fix_diacritics_by_context(md)
    if promote_tall:
        md, report["tall_inline_promoted"] = promote_tall_inline_math(md)
    return md, report