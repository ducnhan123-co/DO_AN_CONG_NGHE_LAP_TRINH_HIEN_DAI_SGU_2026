"""Giữ KHUNG + tiêu đề mục khi PDF là dạng "tờ khung nhiều cột" (cheat sheet, tờ công thức...).

Bổ sung cho src/columns.py (columns.py chỉ chia cột + ngắt cột, không có khung/viền/tiêu đề mục).

  detect_frame_layout(pdf)  -> dict profile nếu PDF có khung + nhiều cột, ngược lại None
  apply_frame_layout(docx, profile) -> sửa DOCX tại chỗ:
        viền trang, N cột có kẻ dọc, tiêu đề lặp thành banner đầu mỗi trang,
        tiêu đề mục (nằm giữa 2 đường kẻ ngang trong PDF) thành thanh tô xám.

Không viết cứng chuỗi nào: số cột, tiêu đề, tên mục đều dò từ chính PDF (hình học đường kẻ).
PDF thường (sách, bài giảng 1 cột, không khung) -> trả None, pipeline chạy y như cũ.
Phụ thuộc: pymupdf, lxml.
"""
import copy
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from collections import Counter

import pymupdf as fitz
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
def q(t): return "{%s}%s" % (W, t)

# ---------------------------------------------------------------- 1. phân tích PDF
# --------------------------------------------------------------------------
def _norm(s): return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()   # NFKC: "ﬁ" -> "fi"

def _is_bold(span):
    n = span["font"].lower()
    return bool(span["flags"] & 16) or any(k in n for k in ("bold", "black", "heavy", "bx", "-bd"))

def _rules(page):
    """Các đường kẻ (vẽ bằng đường thẳng HOẶC hình chữ nhật rất mỏng) -> (ngang, dọc)."""
    hs, vs = [], []   # ngang: (y, x0, x1) ; dọc: (x, y0, y1)
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                if r.height <= 2.5 and r.width > 8: hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width <= 2.5 and r.height > 8: vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
            elif it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) <= 2 and abs(a.x - b.x) > 8: hs.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) <= 2 and abs(a.y - b.y) > 8: vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
    return hs, vs

def analyze_page(page):
    pw, ph = page.rect.width, page.rect.height
    info = {"w": pw, "h": ph, "frame": False, "ncols": 1, "title": None, "heads": []}
    hs, vs = _rules(page)

    # --- khung trang: >=2 đường ngang dài + >=2 đường dọc ở hai mép
    long_h = [h for h in hs if h[2] - h[1] > 0.8 * pw]
    if len(long_h) >= 2 and vs:
        left = min(v[0] for v in vs); right = max(v[0] for v in vs)
        if right - left > 0.8 * pw: info["frame"] = True
        # --- số cột: các x bên trong khung, tổng chiều dài dọc đủ lớn
        inner = {}
        for x, y0, y1 in vs:
            if left + 8 < x < right - 8:
                k = round(x / 8)
                inner[k] = inner.get(k, 0) + (y1 - y0)
        info["ncols"] = 1 + sum(1 for L in inner.values() if L > 0.25 * ph)

    # --- text theo dòng
    lines = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0: continue
        for l in b["lines"]:
            txt = _norm("".join(s["text"] for s in l["spans"]))
            if txt: lines.append((l["bbox"], txt, all(_is_bold(s) for s in l["spans"] if s["text"].strip()),
                                  max(s["size"] for s in l["spans"])))
    lines.sort(key=lambda t: (t[0][1], t[0][0]))
    if lines and lines[0][0][1] < 0.15 * ph and lines[0][2]: info["title"] = lines[0][1]

    # --- tiêu đề mục: dòng ngắn nằm GIỮA hai đường kẻ ngang sát nhau, căn giữa theo đường kẻ
    for bb, txt, bold, sz in lines:
        if txt == info["title"] or not (3 <= len(txt) <= 40): continue
        if sum(c.isalpha() for c in txt) < 0.6 * len(txt) or txt[0].isdigit(): continue
        cx = (bb[0] + bb[2]) / 2
        above = [h for h in hs if bb[1] - 12 <= h[0] <= bb[1] + 2 and h[1] <= cx <= h[2]]
        below = [h for h in hs if bb[3] - 2 <= h[0] <= bb[3] + 12 and h[1] <= cx <= h[2]]
        if not above or not below: continue
        a, b = max(above, key=lambda h: h[0]), min(below, key=lambda h: h[0])
        if b[0] - a[0] > 26: continue
        # biên ô chứa dòng: đường dọc gần nhất bên trái/phải (nếu không có thì dùng đầu/cuối đường ngang)
        cy = (bb[1] + bb[3]) / 2
        lefts = [v[0] for v in vs if v[0] < bb[0] and v[1] - 3 <= cy <= v[2] + 3]
        rights = [v[0] for v in vs if v[0] > bb[2] and v[1] - 3 <= cy <= v[2] + 3]
        lo = max(lefts) if lefts else max(a[1], b[1])
        hi = min(rights) if rights else min(a[2], b[2])
        if hi - lo < 40 or abs(cx - (lo + hi) / 2) > 0.12 * (hi - lo): continue
        # ô tiêu đề chỉ chứa đúng dòng này (không có chữ khác cùng dải ngang, cùng ô)
        band = (a[0], b[0])
        others = [t for t in lines if t[1] != txt and lo <= (t[0][0] + t[0][2]) / 2 <= hi
                  and band[0] - 1 <= (t[0][1] + t[0][3]) / 2 <= band[1] + 1]
        if others: continue
        info["heads"].append(txt)
    return info

def analyze_pdf(path, max_pages=40):
    doc = fitz.open(path)
    pages = [analyze_page(doc[i]) for i in range(min(len(doc), max_pages))]
    n = len(pages)
    framed = sum(p["frame"] for p in pages) / n
    cols_per_page = [p["ncols"] for p in pages]
    cols = Counter(cols_per_page).most_common(1)[0][0]
    multi = sum(c >= 2 for c in cols_per_page) / n
    titles = Counter(p["title"] for p in pages if p["title"])
    title = None
    if titles:
        t, c = titles.most_common(1)[0]
        if c / n >= 0.6 and n >= 2: title = t          # lặp ở đa số trang => header thật
    heads = Counter(h for p in pages for h in p["heads"])
    heads = {h for h, c in heads.items() if h != title}
    kind = "framed_columns" if (framed >= 0.6 and multi >= 0.5) else "linear"
    return {"kind": kind, "pages": n, "framed_ratio": round(framed, 2), "multi_col_ratio": round(multi, 2),
            "cols": max(cols, 2) if kind == "framed_columns" else 1,
            "landscape": pages[0]["w"] > pages[0]["h"], "page_w_pt": pages[0]["w"], "page_h_pt": pages[0]["h"],
            "title": title, "headings": sorted(heads)}

# --------------------------------------------------------------------------

# ---------------------------------------------------------------- 2. ghi vào DOCX
def _pgsz(profile):
    w, h = int(profile["page_w_pt"] * 20), int(profile["page_h_pt"] * 20)   # pt -> dxa
    return w, h

def _sectpr(profile, cols, kind, refs=()):
    w, h = _pgsz(profile)
    orient = ' w:orient="landscape"' if w > h else ""
    mar, gap = 720, 360
    b = "".join('<w:%s w:val="single" w:sz="12" w:space="18" w:color="000000"/>' % s
                for s in ("top", "left", "bottom", "right"))
    if cols == 1:
        c = '<w:cols w:num="1"/>'
    else:   # ghi RÕ độ rộng từng cột: Word/LibreOffice đều chia đều, không phụ thuộc cách tự suy luận
        cw = int((w - 2 * mar - (cols - 1) * gap) / cols)
        inner = "".join('<w:col w:w="%d" w:space="%d"/>' % (cw, gap) for _ in range(cols - 1)) + '<w:col w:w="%d"/>' % cw
        c = '<w:cols w:num="%d" w:sep="1" w:equalWidth="0" w:space="%d">%s</w:cols>' % (cols, gap, inner)
    xml = ('<w:sectPr xmlns:w="%s"><w:type w:val="%s"/><w:pgSz w:w="%d" w:h="%d"%s/>'
           '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="360" w:footer="360" w:gutter="0"/>'
           '<w:pgBorders w:offsetFrom="page">%s</w:pgBorders>%s</w:sectPr>') % (W, kind, w, h, orient, mar, mar, mar, mar, b, c)
    sp = etree.fromstring(xml)
    for i, r in enumerate(refs):            # giữ headerReference/footerReference (số trang)
        sp.insert(i, copy.deepcopy(r))
    return sp

def _p(xml): return etree.fromstring('<w:p xmlns:w="%s">%s</w:p>' % (W, xml))
def _esc(s): return s.replace("&", "&amp;").replace("<", "&lt;")

def _title_p(t):
    return _p('<w:pPr><w:keepNext/><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="1" w:color="000000"/></w:pBdr>'
              '<w:spacing w:before="0" w:after="60"/><w:jc w:val="center"/></w:pPr>'
              '<w:r><w:rPr><w:b/><w:sz w:val="26"/></w:rPr><w:t>%s</w:t></w:r>' % _esc(t))

def _head_p(t):
    return _p('<w:pPr><w:keepNext/><w:pBdr><w:top w:val="single" w:sz="6" w:space="1" w:color="000000"/>'
              '<w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr>'
              '<w:shd w:val="clear" w:color="auto" w:fill="E7E6E6"/><w:spacing w:before="80" w:after="60"/><w:jc w:val="center"/></w:pPr>'
              '<w:r><w:rPr><w:b/><w:sz w:val="19"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r>' % _esc(t))

def _section_break_p(sect):
    p = _p('<w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr>')
    p.find(q("pPr")).append(sect)
    return p

_SP = '<w:spacing xmlns:w="%s" w:before="0" w:after="40" w:line="240" w:lineRule="auto"/>' % W
def _tighten(p):
    """Thu gọn khoảng cách đoạn + làm PHẲNG thụt lề danh sách (Markdown của MinerU hay thành
    danh sách lồng nhiều cấp -> chữ thụt sâu, cột hẹp hẳn). Đặt phần tử đúng thứ tự schema."""
    ppr = p.find(q("pPr"))
    if ppr is None:
        ppr = etree.Element(q("pPr")); p.insert(0, ppr)
    for tag in ("spacing", "ind"):
        for e in ppr.findall(q(tag)): ppr.remove(e)
    sp = etree.fromstring(_SP)
    for tag in ("ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
                "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"):
        el = ppr.find(q(tag))
        if el is not None:
            el.addprevious(sp); break
    else:
        ppr.append(sp)
    num = ppr.find(q("numPr"))
    if num is not None:
        lvl = num.find(q("ilvl"))
        if lvl is not None: lvl.set(q("val"), "0")                 # về cấp 0: bỏ thụt theo cấp lồng
        sp.addnext(etree.fromstring('<w:ind xmlns:w="%s" w:left="300" w:hanging="300"/>' % W))

def _text(p): return _norm("".join(t.text or "" for t in p.iter(q("t"))))

def detect_frame_layout(pdf_path):
    """Profile {'cols','title','headings','page_w_pt','page_h_pt',...} nếu PDF là tờ KHUNG nhiều cột, else None."""
    try:
        prof = analyze_pdf(str(pdf_path))
    except Exception as e:
        print(f"[frame] Không phân tích được PDF ({e}) -> bỏ qua khung.")
        return None
    print(f"[frame] loại={prof['kind']} | trang={prof['pages']} | khung={prof['framed_ratio']} | "
          f"nhiều cột={prof['multi_col_ratio']} | cột={prof['cols']} | tiêu đề lặp={prof['title']!r}")
    return prof if prof["kind"] == "framed_columns" else None


def apply_frame_layout(docx_path, profile):
    """Sửa DOCX tại chỗ theo profile. Giữ footer số trang, ngắt cột đã chèn bởi columns.py."""
    docx_path = str(docx_path)
    title, heads, n = profile["title"], set(profile["headings"]), profile["cols"]
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(docx_path) as z:
            names = z.namelist()
            z.extractall(tmp)
        path = os.path.join(tmp, "word", "document.xml")
        tree = etree.parse(path)
        body = tree.getroot().find(q("body"))

        # bỏ mục lục tự sinh của pandoc (--toc)
        for sdt in body.findall(q("sdt")):
            body.remove(sdt)
        old = body.find(q("sectPr"))
        refs = [e for e in (old if old is not None else []) if etree.QName(e).localname in ("headerReference", "footerReference")]
        if old is not None:
            body.remove(old)

        children = list(body)
        for c in children:
            body.remove(c)
        n_pages = n_heads = 0
        for el in children:
            if el.tag == q("p"):
                t = _text(el)
                if title and t == title:
                    if n_pages:   # đóng phần N cột của trang trước
                        body.append(_section_break_p(_sectpr(profile, n, "continuous", refs)))
                    body.append(_title_p(title))
                    body.append(_section_break_p(_sectpr(profile, 1, "nextPage", refs)))
                    n_pages += 1
                    continue
                if t in heads:
                    body.append(_head_p(t)); n_heads += 1
                    continue
                _tighten(el)
            body.append(el)
        body.append(_sectpr(profile, n, "continuous", refs))
        tree.write(path, xml_declaration=True, encoding="UTF-8", standalone=True)

        out = docx_path + ".tmp"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in names:                       # giữ nguyên thứ tự (content types đứng đầu)
                full = os.path.join(tmp, name)
                if os.path.isfile(full):
                    z.write(full, name)
        os.replace(out, docx_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"[frame] DOCX: {n} cột có kẻ dọc + viền trang | {n_pages} banner tiêu đề | {n_heads} thanh tiêu đề mục")
    return docx_path