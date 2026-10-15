"""Hậu xử lý Markdown của MinerU, TỰ NHẬN DẠNG loại tài liệu (không viết cứng theo 1 PDF).

clean_markdown() chọn 1 trong 3 profile:
  structured : MinerU đã cho >=2 cấp tiêu đề (sách có mục lục) -> giữ nguyên tiêu đề.
  cheatsheet : tiêu đề phẳng + dày (>= 1 tiêu đề / KB chữ): leaflet, bảng công thức, tóm tắt.
  plain      : còn lại (đề thi, bài ngắn) -> chỉ làm sạch nhẹ, không đụng cấu trúc.

Cấp tiêu đề của cheatsheet được suy ra theo thứ tự ưu tiên:
  1. Cỡ chữ + độ đậm đọc từ lớp chữ của PDF (nếu PDF có lớp chữ, khớp được tiêu đề)
  2. File ghi đè tuỳ chọn  input/<ten_pdf>.profile.json  ({"profile": "...", "top_titles": [...]})
  3. Quy tắc dự phòng: tiêu đề kết thúc bằng ':' và tên thuật toán đứng trước 'Step 1' -> cấp sâu hơn
"""
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

B64_IMG = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)?")
DETAILS = re.compile(r"<details>\s*<summary>(.*?)</summary>(.*?)</details>", re.S)
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
STEP1 = re.compile(r"^\s*Step\s*1\b|^\s*Bước\s*1\b", re.I)
URL_MAIL = re.compile(r"https?://\S+|www\.\S+|\b[\w.-]+@[\w-]+\.[\w.]+")
LEGAL = re.compile(r"©|\(c\)\s*\d{4}|copyright|all rights reserved|creative ?commons", re.I)
MIN_DENSITY = 1.0          # tiêu đề / 1000 ký tự chữ để coi là cheatsheet


# ---------------------------------------------------------------- tiện ích
def _norm(s: str) -> str:
    s = re.sub(r"\$[^$]*\$", "", s)
    return re.sub(r"[^0-9a-zà-ỹ]", "", s.lower())


def _paragraphs(md: str) -> List[str]:
    return re.split(r"\n\s*\n", md)


# ------------------------------------------------------------- làm sạch chung
def replace_images(md: str) -> str:
    """Bỏ base64; khối <details> (OCR hình) -> 1 dòng mô tả ngắn, tìm kiếm được."""
    md = B64_IMG.sub("", md)

    def det(m):
        kind, body = m.group(1).strip(), m.group(2)
        if kind == "text_image":
            labels = [l.strip() for l in body.splitlines() if l.strip()]
            return f"[Hình minh hoạ; nhãn: {', '.join(labels)}]"
        return "[Hình minh hoạ]"       # flowchart/mermaid do MinerU đoán từ ảnh thường sai
    return DETAILS.sub(det, md)


def normalize_latex(s: str) -> str:
    s = re.sub(r"([_^])\s*\{([^{}]*)\}",
               lambda m: f"{m.group(1)}{{{re.sub(r'(?<=\w)\s+(?=\w)', '', m.group(2))}}}", s)
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)             # "2 1" -> "21"
    s = re.sub(r"(\d)\.\s+(?=\d)", r"\1.", s)          # "0. 21" -> "0.21"
    s = re.sub(r"\\left\|\s*(\^\s*\{[^}]*\}\s*C)", r"\1", s)
    s = re.sub(r"\s*\\right\.", "", s)
    return s


def fix_tables(md: str) -> str:
    out = []
    for ln in md.splitlines():
        if ln.lstrip().startswith("|"):
            ln = ln.replace("$$", "$ ; $")             # 2 công thức dính nhau trong 1 ô
        out.append(ln)
    return "\n".join(out)


def fix_known_ocr(md: str) -> str:
    # bảng "P xor Q": MinerU hay đọc ⊻ thành ∨
    return re.sub(r"(xor\s*\$?\s*Q\$?\s*\n+\|[^\n]*?)\\lor", r"\1\\veebar", md, flags=re.I)


def promote_algorithm_titles(md: str, level: int) -> str:
    """Dòng ngắn đứng ngay trước 'Step 1' = tên thuật toán -> tiêu đề."""
    lines, out = md.splitlines(), []
    for i, ln in enumerate(lines):
        nxt = next((l for l in lines[i + 1:] if l.strip()), "")
        m = HEAD.match(ln)
        if m and STEP1.match(nxt):
            out.append("#" * level + " " + m.group(2).rstrip(":").strip())
        elif (ln.strip() and not m and len(ln) < 200
                and STEP1.match(nxt) and not STEP1.match(ln)):
            out.append("#" * level + " " + ln.strip().rstrip(":"))
        else:
            out.append(ln)
    return "\n".join(out)


def drop_link_paragraphs(md: str) -> str:
    """Đoạn NGẮN chỉ toàn URL/email/bản quyền (footer, bản quyền) -> bỏ. Không đụng toán/bảng."""
    keep = []
    for p in _paragraphs(md):
        s = p.strip()
        if s and len(s) < 200 and "$" not in s and not s.startswith("|") and \
                (LEGAL.search(s) or len(URL_MAIL.sub("", s).strip()) < 0.5 * len(s)):
            continue
        keep.append(p)
    return "\n\n".join(keep)


# ------------------------------------------------------- nhận dạng profile
def detect_profile(md: str) -> str:
    heads = [len(m.group(1)) for l in md.splitlines() if (m := HEAD.match(l))]
    text_kb = max(len(md), 1) / 1000
    if len(set(heads)) >= 2:
        return "structured"
    if heads and len(heads) / text_kb >= MIN_DENSITY:
        return "cheatsheet"
    return "plain"


# -------------------------------------------- cheatsheet: cấp tiêu đề từ PDF
def _pdf_line_styles(pdf_path: Path, max_pages: int = 60) -> List[tuple]:
    """[(text, size, bold_ratio)] từ lớp chữ của PDF; [] nếu không đọc được/không có lớp chữ."""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    except ImportError:
        return []
    rows = []
    try:
        for pg in extract_pages(str(pdf_path), laparams=LAParams(), maxpages=max_pages):
            for box in pg:
                if not isinstance(box, LTTextContainer):
                    continue
                for ln in box:
                    if not isinstance(ln, LTTextLine):
                        continue
                    ch = [c for c in ln if isinstance(c, LTChar)]
                    t = ln.get_text().strip()
                    if t and ch:
                        bold = sum(any(k in c.fontname.lower() for k in ("bold", "heavy", "black"))
                                   for c in ch) / len(ch)
                        rows.append((t, round(max(c.size for c in ch), 1), bold))
    except Exception:
        return []
    return rows


def levels_from_pdf(headings: List[str], pdf_path: Optional[Path]) -> Dict[str, int]:
    """Map tiêu đề -> cấp (2..6) theo (cỡ chữ, đậm). Trả {} nếu PDF không có lớp chữ khớp được."""
    if not pdf_path or not Path(pdf_path).exists():
        return {}
    rows = _pdf_line_styles(Path(pdf_path))
    if len(rows) < 20:
        return {}
    idx = {}
    for t, s, b in rows:
        idx.setdefault(_norm(t), (s, b >= 0.6))
    found = {}
    for h in headings:
        k = _norm(h)
        if not k:
            continue
        st = idx.get(k) or next((v for kk, v in idx.items()
                                 if len(kk) > 3 and (kk.startswith(k) or k.startswith(kk))), None)
        if st:
            found[h] = st
    if len(found) < max(3, 0.4 * len(headings)):       # khớp quá ít -> không tin
        return {}
    body = Counter()
    for t, s, _ in rows:
        body[s] += len(t)
    body_size = body.most_common(1)[0][0]
    styles = sorted({st for st in found.values() if st[0] >= body_size},
                    key=lambda st: (-st[0], not st[1]))
    rank = {st: min(i + 2, 6) for i, st in enumerate(styles)}
    # tiêu đề không khớp: lấy cấp của tiêu đề gần nhất có CÙNG kiểu đánh số (A. / 1. / 1.1 / I.)
    # cùng kiểu đánh số (A. / 1. / 1.1 / I.) thì dùng cấp phổ biến nhất trong số tiêu đề đã khớp
    by_kind: Dict[str, List[int]] = {}
    for h in headings:
        if h in found and found[h] in rank:
            by_kind.setdefault(_num_kind(h), []).append(rank[found[h]])
    out = {}
    for h in headings:
        k = _num_kind(h)
        if k != "none" and k in by_kind:
            out[h] = Counter(by_kind[k]).most_common(1)[0][0]
        elif h in found and found[h] in rank:
            out[h] = rank[found[h]]
    return out


def _num_kind(h: str) -> str:
    h = h.strip()
    for name, rx in (("dec", r"^\d+(\.\d+)+"), ("num", r"^\d+[.)]"), ("alpha", r"^[A-Z][.)]\s"),
                     ("roman", r"^[IVXL]+[.)]\s")):
        if re.match(rx, h):
            return name
    return "none"


# ------------------------------------------ cheatsheet: dọn bìa/footer, tiêu đề rỗng
def drop_junk_regions(md: str) -> str:
    """Vùng (tiêu đề + đoạn tới tiêu đề kế) mà >=50% đoạn là rác (URL/email/bản quyền/
    tên thương hiệu suy ra từ chính các URL đó) và không có toán/bảng -> bỏ (trang bìa)."""
    brands = set()
    for m in URL_MAIL.finditer(md):
        for part in re.split(r"[./@:-]", m.group(0).lower()):
            if len(part) >= 5 and part not in ("https", "www", "http"):
                brands.add(part)
    brands = {b for b in brands if md.lower().count(b) <= 12 and not re.fullmatch(r"\d+", b)}

    def is_junk(p: str) -> bool:
        s = p.strip()
        return bool(URL_MAIL.search(s) or LEGAL.search(s) or any(b in s.lower() for b in brands))

    regions, cur = [], []
    for ln in md.split("\n"):
        if HEAD.match(ln) and cur:
            regions.append("\n".join(cur)); cur = []
        cur.append(ln)
    regions.append("\n".join(cur))

    kept = []
    for r in regions:
        body = [p for p in _paragraphs(r) if p.strip() and not HEAD.match(p.strip().split("\n")[0])
                and not p.strip().startswith("[Hình")]
        has_math = any("$" in p or p.lstrip().startswith("|") for p in body)
        if body and not has_math and sum(map(is_junk, body)) / len(body) >= 0.5:
            while kept and not [p for p in _paragraphs(kept[-1])[1:] if p.strip()] \
                    and HEAD.match(kept[-1].strip().split("\n")[0]):
                kept.pop()              # tiêu đề bìa đứng trơ trọi ngay trước vùng rác
            continue
        kept.append("\n\n".join(p for p in _paragraphs(r)
                                if not (p.strip() and not HEAD.match(p.strip()) and "$" not in p
                                        and is_junk(p) and len(p) < 200)) if brands else r)
    return "\n".join(kept)


def apply_levels(md: str, level_of: Dict[str, int], top_titles: List[str]) -> str:
    top = {_norm(t) for t in top_titles}
    out = []
    for ln in md.splitlines():
        m = HEAD.match(ln)
        if not m:
            out.append(ln); continue
        title = m.group(2)
        clean = title.rstrip(":").strip()
        if level_of.get(title):
            lv = level_of[title]
        elif top:
            lv = 2 if _norm(clean) in top else 3
        else:
            lv = len(m.group(1)) + (1 if title.endswith(":") else 0)   # dự phòng: chỉ theo dấu ':'
        out.append("#" * min(lv, 6) + " " + clean)
    return "\n".join(out)


# ------------------------------------------------------------------ cổng vào
def load_sidecar(path: Optional[Path]) -> dict:
    if path and Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[postprocess] Không đọc được {path}: {e}")
    return {}


def clean_markdown(md: str, pdf_path: Optional[Path] = None, profile: str = "auto",
                   sidecar_path: Optional[Path] = None, verbose: bool = True) -> str:
    side = load_sidecar(sidecar_path)
    md = replace_images(md)
    md = re.sub(r"\$\$(.*?)\$\$", lambda m: "$$" + normalize_latex(m.group(1)) + "$$", md, flags=re.S)
    md = fix_tables(md)
    md = fix_known_ocr(md)

    prof = side.get("profile") or (detect_profile(md) if profile == "auto" else profile)
    if verbose:
        print(f"[postprocess] profile = {prof}")

    if prof == "cheatsheet":
        md = drop_junk_regions(md)        # trước drop_link_paragraphs: cần URL để suy ra thương hiệu
    md = drop_link_paragraphs(md)
    if prof == "cheatsheet":
        heads = [m.group(2) for l in md.splitlines() if (m := HEAD.match(l))]
        level_of = levels_from_pdf(heads, pdf_path)
        if verbose:
            print(f"[postprocess] cấp tiêu đề từ PDF: {'có' if level_of else 'không (dùng quy tắc dự phòng)'}"
                  f"{' + top_titles từ sidecar' if side.get('top_titles') else ''}")
        md = apply_levels(md, level_of, side.get("top_titles", []))
        md = promote_algorithm_titles(md, level=4 if level_of else 3)
    else:
        md = promote_algorithm_titles(md, level=3)
    return md