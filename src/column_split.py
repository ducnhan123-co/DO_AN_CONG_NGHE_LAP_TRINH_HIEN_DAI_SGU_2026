"""Tách PDF dạng "tờ khung nhiều cột" thành từng DẢI CỘT trước khi đưa vào MinerU.

Vì sao cần:
  MinerU đọc cả trang cheat-sheet như MỘT bảng lớn (<table rowspan=...>), nên mất thứ tự đọc theo cột,
  công thức dồn vào một ô, không biết chỗ ngắt cột. Chữa tận gốc: cho MinerU đọc từng cột như một tài
  liệu 1 cột bình thường, rồi ghép lại theo đúng thứ tự cột -> ngắt cột chính xác, không cần OCR đoán.

Không viết cứng gì cho một file cụ thể. Mọi thứ dò từ hình học PDF (đường kẻ dọc/ngang):
  - Đường kẻ dọc nằm trong khung và dài gần bằng đường dài nhất  => đường phân cột.
    (đường kẻ ngắn hơn là lưới bảng bên trong 1 cột -> KHÔNG tách, để MinerU đọc thành bảng)
  - Phần nằm trên đầu các đường phân cột (băng tiêu đề trải ngang) => banner, lấy chữ thẳng từ lớp chữ PDF.
  - Trang không có khung / không có đường phân cột => giữ nguyên cả trang là 1 dải (hành vi cũ).

API:
  plan_strips(pdf)                              -> plan (dict) hoặc None nếu PDF không có cột kẻ
  build_strips_pdf(pdf, out_pdf, plan)          -> ghi PDF mới, mỗi trang = 1 dải cột
  remap_content_list(raw, plan)                 -> sửa page_idx về trang gốc (cho structured/RAG)
  content_list_to_docx_md(raw, plan, title)     -> Markdown theo thứ tự cột, có ngắt cột / ngắt trang
Phụ thuộc: pymupdf.
"""
import copy
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

import pymupdf as fitz

from .frame_layout import _rules          # dùng lại bộ dò đường kẻ đã có

COL_BREAK = '```{=openxml}\n<w:p><w:r><w:br w:type="column"/></w:r></w:p>\n```'
PAGE_BREAK = '```{=openxml}\n<w:p><w:r><w:br w:type="page"/></w:r></w:p>\n```'
SKIP_TYPES = {"header", "footer", "page_number", "aside_text", "page_footnote"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


# ----------------------------------------------------------------- 1. phân tích hình học
def _merge_vrules(vs, tol: float = 5.0, gap: float = 8.0) -> List[List[float]]:
    """Gộp các đoạn kẻ dọc cùng x (bị vẽ thành nhiều đoạn) -> [x, y0, y1]."""
    merged: List[List[float]] = []
    for x, y0, y1 in sorted(vs, key=lambda t: (t[0], t[1])):
        for m in merged:
            if abs(m[0] - x) <= tol and y0 <= m[2] + gap and y1 >= m[1] - gap:
                m[1], m[2] = min(m[1], y0), max(m[2], y1)
                break
        else:
            merged.append([x, y0, y1])
    return merged


def _is_grid_line(x, y0, y1, hs, tol: float = 3.0, min_rows: int = 3) -> bool:
    """Đường dọc là LƯỚI BẢNG (không phải đường phân cột) khi có >= min_rows đường ngang
    chạm vào nó từ CẢ HAI phía trong đoạn y của nó."""
    left = sum(1 for (y, a, b) in hs if y0 - tol <= y <= y1 + tol and abs(b - x) <= tol)
    right = sum(1 for (y, a, b) in hs if y0 - tol <= y <= y1 + tol and abs(a - x) <= tol)
    return left >= min_rows and right >= min_rows


def _whitespace_cuts(page, x0, x1, y0, y1, min_gap=12.0, edge=25.0, min_words=40, min_h=150.0):
    """Rãnh trắng dọc cắt qua toàn dải (cho dải KHÔNG có đường kẻ dọc)."""
    if y1 - y0 < min_h:
        return []
    words = [w for w in page.get_text("words") if y0 <= (w[1] + w[3]) / 2 <= y1 and w[0] >= x0 - 1 and w[2] <= x1 + 1]
    if len(words) < min_words:
        return []
    n = int(x1 - x0) + 1
    cov = [False] * n
    for w in words:
        for i in range(max(0, int(w[0] - x0) - 1), min(n, int(w[2] - x0) + 2)):
            cov[i] = True
    cuts, i = [], 0
    while i < n:
        if not cov[i]:
            j = i
            while j < n and not cov[j]:
                j += 1
            if j - i >= min_gap and i >= edge and n - j >= edge:
                cuts.append(x0 + (i + j) / 2)
            i = j
        else:
            i += 1
    keep, bounds = [], [x0] + cuts + [x1]
    for k in range(len(bounds) - 1):                      # mỗi cột phải có đủ chữ, nếu không bỏ cắt
        cnt = sum(1 for w in words if bounds[k] <= (w[0] + w[2]) / 2 < bounds[k + 1])
        if cnt < 0.1 * len(words) and k < len(cuts):
            continue
        if k < len(cuts):
            keep.append(cuts[k])
    return keep


def _merge_narrow(cuts, left, right, narrow: float = 100.0):
    """Hai cột hẹp liền nhau (vd 3 cột số của bảng nhỏ) là MỘT bảng -> bỏ đường cắt giữa chúng."""
    if not cuts:
        return cuts
    b = [left] + list(cuts) + [right]
    keep = list(cuts)
    for i in range(len(b) - 2):
        if (b[i + 1] - b[i]) < narrow and (b[i + 2] - b[i + 1]) < narrow:
            keep[i] = None
    return [x for x in keep if x is not None]


def _text_extent(page, x0, x1, y0, y1):
    ws = [w for w in page.get_text("words") if y0 <= (w[1] + w[3]) / 2 <= y1 and x0 - 1 <= w[0] and w[2] <= x1 + 1]
    return (max(w[2] for w in ws) - min(w[0] for w in ws)) if ws else 0.0


def _same_cuts(a, b, tol=4.0):
    return len(a) == len(b) and all(abs(p - q) <= tol for p, q in zip(a, b))


def _plan_page(page, thin_h: float = 30.0) -> Optional[dict]:
    """Trang -> {'frame', 'bands': [{'y0','y1','cuts':[x...],'banner':bool}]} hoặc None nếu không có khung."""
    pw, ph = page.rect.width, page.rect.height
    hs, vs = _rules(page)
    mv = _merge_vrules(vs)
    edges = [m for m in mv if (m[2] - m[1]) > 0.7 * ph]
    if len(edges) < 2:
        return None
    left, right = min(m[0] for m in edges), max(m[0] for m in edges)
    if right - left < 0.6 * pw:
        return None
    top, bottom = min(m[1] for m in edges), max(m[2] for m in edges)
    W_ = right - left

    # 1) cắt ngang bằng đường kẻ trải >= 90% bề rộng khung
    ys = sorted({round(y, 1) for (y, a, b) in hs if (min(b, right) - max(a, left)) >= 0.9 * W_})
    cy: List[float] = []
    for y in ys:
        if not cy or y - cy[-1] > 3:
            cy.append(y)
    # đầu/cuối của các đường dọc dài bên trong khung cũng là chỗ đổi cấu trúc cột (T-junction)
    for m in mv:
        if left + 8 < m[0] < right - 8 and (m[2] - m[1]) >= 100:
            for y in (m[1], m[2]):
                if top + 12 < y < bottom - 12 and all(abs(y - c0) > 12 for c0 in cy):
                    cy.append(y)
    cy = sorted(cy)
    cy = [y for y in cy if top - 1 <= y <= bottom + 1]
    if not cy or cy[0] - top > 3:
        cy.insert(0, top)
    if bottom - cy[-1] > 3:
        cy.append(bottom)
    raw = [(cy[i], cy[i + 1]) for i in range(len(cy) - 1) if cy[i + 1] - cy[i] > 4]

    # 2) cắt dọc cho từng dải
    bands = []
    for (y0, y1) in raw:
        cuts = []
        for m in sorted(mv):
            if not (left + 8 < m[0] < right - 8):
                continue
            ov = min(y1, m[2]) - max(y0, m[1])
            if ov >= 0.85 * (y1 - y0) and not _is_grid_line(m[0], m[1], m[2], hs):
                if not cuts or m[0] - cuts[-1] > 30:
                    cuts.append(m[0])
        if not cuts:
            cuts = _whitespace_cuts(page, left, right, y0, y1)
        cuts = _merge_narrow(cuts, left, right)
        bands.append({"y0": y0, "y1": y1, "cuts": cuts, "banner": False})

    # 3) dải mỏng không cột: đầu trang = banner; còn lại dính vào dải kế tiếp nếu dải đó có cột
    out = []
    for i, b in enumerate(bands):
        if i == 0 and (b["y1"] - b["y0"]) < thin_h and not b["cuts"]:
            b["banner"] = True
            out.append(b)
            continue
        if (out and out[-1]["y1"] - out[-1]["y0"] < thin_h and not out[-1]["cuts"] and not out[-1]["banner"]
                and b["cuts"] and _text_extent(page, left, right, out[-1]["y0"], out[-1]["y1"]) < 0.45 * W_):
            b["y0"] = out.pop()["y0"]      # thanh tiêu đề ngắn (vd "Recurrences") thuộc cột phía dưới
        out.append(b)
    # 4) gộp dải liền kề có cùng cách chia cột (vd hàng tiêu đề + thân)
    merged: List[dict] = []
    for b in out:
        if merged and not b["banner"] and not merged[-1]["banner"] and _same_cuts(merged[-1]["cuts"], b["cuts"]):
            merged[-1]["y1"] = b["y1"]
        else:
            merged.append(b)
    return {"frame": [left, top, right, bottom], "bands": merged}


def plan_strips(pdf_path, max_pages: int = 200) -> Optional[dict]:
    """Plan {'strips','bands','banners','ncols'} nếu >= 50% trang có khung và có chia cột; ngược lại None."""
    doc = fitz.open(str(pdf_path))
    n = min(len(doc), max_pages)
    strips, bands_out, banners, framed, multi = [], [], {}, 0, 0
    for pno in range(n):
        page = doc[pno]
        pp = _plan_page(page)
        if pp is None:                                    # trang thường: 1 dải = cả trang
            r = page.rect
            bands_out.append({"page": pno, "ncols": 1, "widths": [r.width], "banner": False,
                              "strips": [len(strips)], "first": True})
            strips.append({"idx": len(strips), "page": pno, "band": len(bands_out) - 1, "col": 0, "ncols": 1,
                           "rect": [r.x0, r.y0, r.x1, r.y1]})
            continue
        framed += 1
        left, top, right, bottom = pp["frame"]
        any_cols = False
        for bi, b in enumerate(pp["bands"]):
            bounds = [left] + b["cuts"] + [right]
            k = len(bounds) - 1
            any_cols |= k > 1
            bd = {"page": pno, "ncols": k, "widths": [bounds[i + 1] - bounds[i] for i in range(k)],
                  "banner": b["banner"], "first": bi == 0, "strips": []}
            if b["banner"]:
                banners[str(pno)] = _norm(page.get_text("text", clip=fitz.Rect(left, b["y0"], right, b["y1"])))
                bands_out.append(bd)
                continue
            bands_out.append(bd)
            for ci in range(k):
                strips.append({"idx": len(strips), "page": pno, "band": len(bands_out) - 1, "col": ci, "ncols": k,
                               "rect": [bounds[ci] + 1.5, b["y0"] + 0.5, bounds[ci + 1] - 1.5, b["y1"] - 0.5]})
                bd["strips"].append(len(strips) - 1)
        multi += any_cols
    if framed < 0.5 * n or multi < 0.5 * n:
        return None
    return {"pages": n, "ncols": max(b["ncols"] for b in bands_out), "strips": strips, "bands": bands_out,
            "banners": {k: v for k, v in banners.items() if v},
            "page_pt": [doc[0].rect.width, doc[0].rect.height]}


# ----------------------------------------------------------------- 2. PDF các dải cột
def build_strips_pdf(pdf_path, out_pdf, plan: dict, min_width_pt: float = 520.0) -> Path:
    """Mỗi dải cột -> 1 trang PDF riêng (giữ vector + lớp chữ). Dải hẹp được phóng lên cho MinerU dễ đọc."""
    src, out = fitz.open(str(pdf_path)), fitz.open()
    for s in plan["strips"]:
        r = fitz.Rect(*s["rect"])
        k = max(1.0, min_width_pt / r.width)
        pg = out.new_page(width=r.width * k, height=r.height * k)
        pg.show_pdf_page(pg.rect, src, s["page"], clip=r)
    out_pdf = Path(out_pdf)
    out.save(str(out_pdf))
    return out_pdf


# ----------------------------------------------------------------- 3. ghép lại
def remap_content_list(raw: List[Dict], plan: dict) -> List[Dict]:
    """page_idx của MinerU (= chỉ số dải) -> trang gốc. Thứ tự vẫn là thứ tự đọc theo cột."""
    pages = {s["idx"]: s["page"] for s in plan["strips"]}
    out = []
    for it in raw:
        it = dict(it)
        if isinstance(it.get("page_idx"), int):
            it["page_idx"] = pages.get(it["page_idx"], it["page_idx"])
        out.append(it)
    return out


def _math(text: str) -> str:
    t = (text or "").strip()
    if t.startswith(("$$", "\\[")):
        return t
    return "$$\n" + t.strip("$ \n") + "\n$$"


def _block_md(it: Dict) -> str:
    t = it.get("type", "text")
    if t in SKIP_TYPES:
        return ""
    if t == "text":
        txt = (it.get("text") or "").strip()
        if not txt:
            return ""
        lvl = it.get("text_level")
        return ("#" * min(int(lvl), 6) + " " + txt) if lvl else txt
    if t == "equation":
        return _math(it.get("text") or "") if (it.get("text") or "").strip() else ""
    if t == "table":
        cap = " ".join(it.get("table_caption") or [])
        body = (it.get("table_body") or "").strip()
        return "\n\n".join(x for x in (cap, body) if x)
    if t == "image":
        p = it.get("img_path")
        cap = " ".join(it.get("image_caption") or [])
        return f"![{cap}]({p})" if p else ""
    if t == "list":
        return "\n".join("- " + str(i).strip() for i in (it.get("list_items") or []) if str(i).strip())
    if t == "code":
        body = (it.get("code_body") or it.get("text") or "").strip()
        return f"```\n{body}\n```" if body else ""
    txt = (it.get("text") or "").strip()
    return txt


def common_title(plan: dict) -> Optional[str]:
    """Banner lặp ở >= 60% số trang = tiêu đề chạy đầu trang."""
    from collections import Counter
    cnt = Counter(plan.get("banners", {}).values())
    if cnt and plan["pages"] >= 2:
        t, k = cnt.most_common(1)[0]
        if k >= 0.6 * plan["pages"]:
            return t
    return None


def band_marker(i: int) -> str:
    return f"ZZBAND{i}ZZ"


def content_list_to_docx_md(raw: List[Dict], plan: dict) -> str:
    """Markdown cho DOCX theo thứ tự đọc thật: mỗi DẢI (band) = các cột, giữa 2 cột chèn ngắt cột.
    Sau mỗi dải có 1 đoạn đánh dấu ZZBANDnZZ; apply_band_layout() đổi nó thành section Word có đúng số cột."""
    by_strip: Dict[int, List[Dict]] = {}
    for it in raw:
        pi = it.get("page_idx")
        if isinstance(pi, int):
            by_strip.setdefault(pi, []).append(it)
    out: List[str] = []
    for bi, bd in enumerate(plan["bands"]):
        if bd["banner"]:
            out.append(plan["banners"].get(str(bd["page"]), ""))      # chữ lấy từ lớp chữ PDF, không qua OCR
        for k, sidx in enumerate(bd["strips"]):
            if k > 0:
                out.append(COL_BREAK)
            for it in by_strip.get(sidx, []):
                md = _block_md(it)
                if md:
                    out.append(md)
        out.append(band_marker(bi))
    return "\n\n".join(x for x in out if x)


def _carry_breaks(old, new):
    """Đoạn cũ có thể chứa ngắt cột/ngắt trang (columns._merge_break_paragraphs dồn vào đầu đoạn kế tiếp);
    khi thay bằng đoạn mới phải chuyển ngắt đó sang, nếu không cột bị lệch."""
    from .frame_layout import q
    ppr = new.find(q("pPr"))
    pos = 1 if ppr is not None else 0
    for r in old.findall(q("r")):
        br = r.find(q("br"))
        if br is not None and br.get(q("type")) in ("column", "page"):
            new.insert(pos, copy.deepcopy(r)); pos += 1
    return new


def apply_band_layout(docx_path, plan: dict, heads=(), margin_dxa: int = 720, gap_dxa: int = 360):
    """Đổi các đoạn ZZBANDnZZ thành section Word: số cột + độ rộng cột lấy từ PDF, viền trang, banner, thanh tiêu đề."""
    import copy, os, shutil, tempfile, zipfile
    from lxml import etree
    from .frame_layout import W, _head_p, _p, _tighten, _text, _title_p, q

    title, heads = common_title(plan), set(heads)
    w_dxa, h_dxa = int(plan["page_pt"][0] * 20), int(plan["page_pt"][1] * 20)
    text_w = w_dxa - 2 * margin_dxa
    borders = "".join('<w:%s w:val="single" w:sz="12" w:space="18" w:color="000000"/>' % s
                      for s in ("top", "left", "bottom", "right"))

    def sectpr(bd, kind, refs):
        k = bd["ncols"]
        if k == 1:
            cols = '<w:cols w:num="1"/>'
        else:
            usable = text_w - (k - 1) * gap_dxa
            tot = sum(bd["widths"])
            ws = [int(usable * x / tot) for x in bd["widths"]]
            inner = "".join('<w:col w:w="%d" w:space="%d"/>' % (x, gap_dxa) for x in ws[:-1]) + '<w:col w:w="%d"/>' % ws[-1]
            cols = '<w:cols w:num="%d" w:sep="1" w:equalWidth="0" w:space="%d">%s</w:cols>' % (k, gap_dxa, inner)
        xml = ('<w:sectPr xmlns:w="%s"><w:type w:val="%s"/><w:pgSz w:w="%d" w:h="%d"/>'
               '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="360" w:footer="360" w:gutter="0"/>'
               '<w:pgBorders w:offsetFrom="page">%s</w:pgBorders>%s</w:sectPr>') % (
            W, kind, w_dxa, h_dxa, margin_dxa, margin_dxa, margin_dxa, margin_dxa, borders, cols)
        sp = etree.fromstring(xml)
        for i, r in enumerate(refs):
            sp.insert(i, copy.deepcopy(r))
        return sp

    docx_path = str(docx_path)
    tmp = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(docx_path) as z:
            names = z.namelist()
            z.extractall(tmp)
        path = os.path.join(tmp, "word", "document.xml")
        tree = etree.parse(path)
        body = tree.getroot().find(q("body"))
        for sdt in body.findall(q("sdt")):                 # bỏ mục lục tự sinh của pandoc
            body.remove(sdt)
        old = body.find(q("sectPr"))
        refs = [e for e in (old if old is not None else []) if etree.QName(e).localname in ("headerReference", "footerReference")]
        if old is not None:
            body.remove(old)
        children = list(body)
        for ch in children:
            body.remove(ch)
        n_band = n_head = 0
        last = None
        for el in children:
            if el.tag == q("p"):
                t = _text(el)
                m = re.fullmatch(r"ZZBAND(\d+)ZZ", t)
                if m:
                    bd = plan["bands"][int(m.group(1))]
                    kind = "nextPage" if bd["first"] else "continuous"
                    p = _p('<w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr>')
                    p.find(q("pPr")).append(sectpr(bd, kind, refs))
                    body.append(p); n_band += 1; last = bd
                    continue
                if title and t == title:
                    body.append(_carry_breaks(el, _title_p(title))); continue
                if t in heads:
                    body.append(_carry_breaks(el, _head_p(t))); n_head += 1; continue
                _tighten(el)
            body.append(el)
        body.append(sectpr(last or plan["bands"][-1], "continuous", refs))
        tree.write(path, xml_declaration=True, encoding="UTF-8", standalone=True)
        out = docx_path + ".tmp"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in names:
                full = os.path.join(tmp, name)
                if os.path.isfile(full):
                    z.write(full, name)
        os.replace(out, docx_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"[bands] DOCX: {n_band} dải (mỗi dải = 1 section với số cột riêng) | {n_head} thanh tiêu đề mục")
    return docx_path


def save_plan(plan: dict, path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def preview(pdf_path, out_dir, plan: Optional[dict] = None, dpi: int = 70) -> List[Path]:
    """Vẽ khung các dải cột lên từng trang PDF -> PNG để kiểm tra bằng mắt trước khi chạy MinerU."""
    plan = plan or plan_strips(pdf_path)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    doc, outs = fitz.open(str(pdf_path)), []
    colors = [(1, 0, 0), (0, 0.5, 1), (0, 0.7, 0), (1, 0.5, 0), (0.6, 0, 0.8)]
    for pno in range(len(doc)):
        pg = doc[pno]
        for s in (plan["strips"] if plan else []):
            if s["page"] == pno:
                pg.draw_rect(fitz.Rect(*s["rect"]), color=colors[s["col"] % 5], width=1.6)
        f = out_dir / f"preview_p{pno + 1:02d}.png"
        pg.get_pixmap(dpi=dpi).save(str(f)); outs.append(f)
    return outs


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        sys.exit("Dùng: python -m src.column_split file.pdf thu_muc_preview")
    p = plan_strips(sys.argv[1])
    print("Không phải PDF nhiều cột có khung (pipeline sẽ chạy như cũ)." if p is None else
          f"{len(p['strips'])} dải cột / {p['pages']} trang, tối đa {p['ncols']} cột")
    print("\n".join(map(str, preview(sys.argv[1], sys.argv[2], p))))