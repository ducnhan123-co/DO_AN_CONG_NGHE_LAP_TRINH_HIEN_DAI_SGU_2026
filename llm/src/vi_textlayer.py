"""Sửa chữ Việt của MinerU bằng lớp chữ thật của PDF (PDF sinh từ Word, không phải scan).

MinerU OCR lại dòng có công thức chen giữa -> rụng dấu ("lu ý thay chu k ph đi đng"), và nhận chữ có dấu
như công thức (`$\\acute{y}$`). Lớp chữ PDF vẫn đúng nên dùng làm chuẩn. Chỉ SỬA, không bịa: từ đúng phải
chứa từ hỏng như một dãy con (sau khi bỏ dấu), trong cửa sổ vài từ quanh vị trí đang đọc.
"""
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import List, Optional

_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+\$)", re.S)
_ACCENT_WORD = re.compile(r"\\(?:acute|grave|hat|tilde|breve|check|dot)\b")
_WINDOW = 6


def strip(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if c.isalpha() and not unicodedata.combining(c))


def _subseq(a: str, b: str) -> bool:
    it = iter(b)
    return all(ch in it for ch in a)


def _is_latin(s: str) -> bool:
    """Chữ Latin/Việt (không Hy Lạp...): ký hiệu công thức như ω, φ không được là ứng viên sửa."""
    return all(ord(c) < 0x250 or 0x1E00 <= ord(c) <= 0x1EFF for c in s)


def _letters(tok: str) -> str:
    return "".join(c for c in tok if c.isalpha())


def _is_accent_math(m: str) -> bool:
    """`$...$` chỉ gồm chữ + lệnh dấu LaTeX (không =, ^, _, \\frac...) -> thực chất là 1 từ/chữ có dấu."""
    body = m.strip("$")
    if not _ACCENT_WORD.search(body) or re.search(r"[=^_+*/<>]|\\(?:frac|sqrt|sum|int|left|prime)", body):
        return False
    return len(strip(re.sub(r"\\[A-Za-z]+", "", body))) <= 6


def _math_letters(m: str) -> str:
    body = re.sub(r"\\(?:acute|grave|hat|tilde|breve|check|dot|mathrm|mathbf|bf|it|boldsymbol)\b", "", m.strip("$"))
    return strip(body)


def _find(cands: List[str], j: int, ok) -> Optional[int]:
    for k in range(j, min(j + _WINDOW, len(cands))):
        if ok(cands[k]):
            return k
    return None


def repair_text(text: str, cands: List[str]) -> str:
    """Sửa các từ không-công-thức của `text` theo danh sách từ chuẩn `cands` (đúng thứ tự đọc)."""
    out, j = [], 0
    for i, part in enumerate(_MATH.split(text)):
        if i % 2:                                              # phần công thức
            if _is_accent_math(part):
                letters = _math_letters(part)
                k = _find(cands, j, lambda c: letters and strip(c) != "" and _subseq(letters, strip(c)))
                if k is not None:
                    out.append(cands[k]); j = k + 1
                    continue
            out.append(part)
            continue
        toks = re.split(r"(\s+)", part)
        for t in range(len(toks)):
            w = toks[t]
            core = _letters(w)
            if not core or w.isspace():
                continue
            k = _find(cands, j, lambda c: c.lower() == core.lower())
            if k is not None:                                  # đã đúng
                j = k + 1
                continue
            sc = strip(core)
            k = _find(cands, j, lambda c: c.lower() != core.lower() and len(sc) <= len(strip(c)) <= len(sc) + 3 and _subseq(sc, strip(c))
                       and c.lower().count("đ") >= core.lower().count("đ")
                       and c[:1].isupper() == core[:1].isupper()           # "làm" không thành "Flàm"
                       and (len(sc) > 1 or (len(strip(c)) <= 3 and c.lower() != strip(c))))  # chữ đơn: chỉ "k"->"kỳ"
            if k is not None:
                fixed = cands[k]
                if core[0].isupper():
                    fixed = fixed[0].upper() + fixed[1:]
                toks[t] = w.replace(core, fixed, 1)
                j = k + 1
        out.append("".join(toks))
    return "".join(out)


def page_words(page, bbox, convert) -> List[str]:
    """Từ chữ (chuẩn) trong bbox 0-1000 của trang, theo thứ tự đọc; bỏ ký hiệu không có chữ cái."""
    import fitz
    r = page.rect
    clip = fitz.Rect(bbox[0] / 1000 * r.width, bbox[1] / 1000 * r.height,
                     bbox[2] / 1000 * r.width, bbox[3] / 1000 * r.height)
    words = (w[4] for w in page.get_text("words", clip=clip))
    return [x for x in (_letters(convert(w)) for w in words) if x and _is_latin(x)]


def strip_footers(md: str, min_repeat: int = 20) -> str:
    """Bỏ dòng ngắn không-công-thức lặp >= min_repeat lần (chân trang/đầu trang), kể cả khi dính đầu đoạn;
    nối lại câu bị chân trang cắt đôi (đoạn trước chưa kết câu + đoạn sau bắt đầu chữ thường)."""
    lines = [l.strip() for l in md.split("\n") if 0 < len(l.strip()) < 120 and "$" not in l]
    rep = [l for l, n in Counter(lines).items() if n >= min_repeat and not l.startswith("#")]
    if not rep:
        return md
    out: List[str] = []
    for para in md.split("\n\n"):
        glued = False
        for f in rep:
            if f in para.strip()[len(f):]:                     # nằm giữa đoạn (đoạn không bắt đầu bằng nó)
                para = re.sub(r"\s*" + re.escape(f) + r"\s*", " ", para)
            st = para.strip()
            if st == f:
                para, glued = "", True
            elif st.startswith(f):
                para, glued = st[len(f):].lstrip(), True
        if not para.strip():
            continue
        if glued and out and out[-1].rstrip()[-1:] not in ".?!:;)$" and para[:1].islower():
            out[-1] = out[-1].rstrip() + " " + para
        else:
            out.append(para)
    return "\n\n".join(out)


def repair_markdown(md: str, items: List[dict], pdf_path: Path, convert) -> str:
    """Áp repair_text lên từng block text của content_list và thay đúng đoạn đó trong md."""
    import fitz
    doc = fitz.open(str(pdf_path))
    for it in items:
        old = it.get("text")
        if it.get("type") != "text" or not isinstance(old, str) or not it.get("bbox"):
            continue
        try:
            new = repair_text(old, page_words(doc[it.get("page_idx", 0)], it["bbox"], convert))
        except Exception:                                       # noqa: BLE001 - chỉ là nâng chất lượng
            continue
        if new != old:
            it["text"] = new
            md = md.replace(old.strip(), new.strip(), 1)
    return md
