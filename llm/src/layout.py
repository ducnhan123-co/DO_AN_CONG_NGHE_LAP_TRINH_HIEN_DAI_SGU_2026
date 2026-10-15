"""Dựng lại BỐ CỤC của PDF trong DOCX từ tọa độ MinerU (bbox chuẩn hoá 0-1000) + thông tin trang PDF.

MinerU chỉ cho nội dung theo thứ tự đọc nên pandoc ra văn bản chảy 1 cột. Ở đây:
  - đoán số cột từng trang (cụm cạnh trái x0 của các khối hẹp) -> chèn ngắt cột Word đúng chỗ PDF ngắt cột,
  - tài liệu có trang nhiều cột: mỗi trang PDF = 1 section Word (khổ giấy, lề, các cột đúng toạ độ PDF),
  - mọi tài liệu: khổ giấy + lề + cỡ chữ gốc cho section cuối, kích thước ảnh theo bbox.
Công thức vẫn là Equation Word thật (đi qua pandoc như cũ). Marker là raw openxml của pandoc (```{=openxml}).
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

KEEP = {"text", "table", "image", "equation"}
TWIP = 20  # 1pt = 20 twips


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def estimate_font_pt(items: List[dict], dims: Dict[int, tuple], pdf: Optional[str]) -> float:
    """Cỡ chữ thân bài: ưu tiên chữ thật trong PDF (median theo số ký tự); PDF ảnh/vẽ nét thì ước lượng từ diện tích khối."""
    sizes: Dict[float, int] = {}
    if pdf:
        try:
            import fitz
            for pg in fitz.open(pdf):
                for b in pg.get_text("dict")["blocks"]:
                    for ln in (b.get("lines") or []):
                        for sp in ln["spans"]:
                            n = len(sp["text"].strip())
                            if n:
                                k = round(sp["size"] * 2) / 2
                                sizes[k] = sizes.get(k, 0) + n
        except Exception:  # noqa: BLE001
            pass
    if sum(sizes.values()) >= 2000:
        return max(sizes, key=sizes.get)
    est = []
    for it in items:
        if it.get("type") != "text" or not it.get("bbox"):
            continue
        txt = re.sub(r"\$[^$]*\$", "", it.get("text") or "")
        L = len(txt.strip())
        w, h = dims.get(it.get("page_idx", 0), (595, 842))
        b = it["bbox"]
        area = (b[2] - b[0]) / 1000 * w * (b[3] - b[1]) / 1000 * h
        if L >= 100 and area > 0:
            est.append((area / (0.85 * L)) ** 0.5)
    if sizes and sum(sizes.values()) >= 300:
        est.append(max(sizes, key=sizes.get))
    est.sort()
    return round(est[len(est) // 2] * 2) / 2 if est else 11.0


def _columns(blocks: List[dict]) -> List[List[float]]:
    """[[x0, x1], ...] theo thứ tự trái->phải. Cụm theo cạnh trái x0 của các khối hẹp (<60% trang); cột = cụm có >=3 khối."""
    narrow = sorted((b for b in blocks if b["bbox"][2] - b["bbox"][0] < 600), key=lambda b: b["bbox"][0])
    groups: List[List[dict]] = []
    for b in narrow:
        if groups and b["bbox"][0] - groups[-1][-1]["bbox"][0] <= 120:
            groups[-1].append(b)
        else:
            groups.append([b])
    cols = [[min(x["bbox"][0] for x in g), max(x["bbox"][2] for x in g)] for g in groups if len(g) >= 3]
    return cols


def analyze_layout(items: List[dict], pdf: Optional[str]) -> dict:
    import fitz
    doc = fitz.open(pdf) if pdf else None
    n = (len(doc) if doc else 1 + max([it.get("page_idx", 0) for it in items] or [0]))
    pages, dims = {}, {}
    for pg in range(n):
        r = doc[pg].rect if doc else fitz.Rect(0, 0, 595, 842)
        W, H = r.width, r.height
        dims[pg] = (W, H)
        bl = [it for it in items if it.get("page_idx") == pg and it.get("type") in KEEP and it.get("bbox")]
        if bl:
            x0 = min(b["bbox"][0] for b in bl); x1 = max(b["bbox"][2] for b in bl)
            y0 = min(b["bbox"][1] for b in bl); y1 = max(b["bbox"][3] for b in bl)
        else:
            x0, x1, y0, y1 = 80, 920, 80, 920
        cols = _columns(bl) if bl else []
        if len(cols) < 2:
            cols = [[x0, x1]]
        else:
            x0, x1 = cols[0][0], cols[-1][1]
        clamp = lambda v: max(18.0, min(v, 140.0))
        pages[pg] = {"w": W, "h": H,
                     "ml": clamp(x0 / 1000 * W), "mr": clamp((1000 - x1) / 1000 * W),
                     "mt": clamp(y0 / 1000 * H), "mb": clamp((1000 - y1) / 1000 * H),
                     "cols": [[round(a, 1), round(b, 1)] for a, b in cols]}
    img_w = {}
    for it in items:
        if it.get("bbox") and it.get("img_path"):
            W = dims.get(it.get("page_idx", 0), (595, 0))[0]
            img_w[Path(it["img_path"]).name] = round((it["bbox"][2] - it["bbox"][0]) / 1000 * W, 1)
    return {"pages": pages, "font_pt": estimate_font_pt(items, dims, pdf), "img_width_pt": img_w,
            # tài liệu nhiều cột = ĐA SỐ trang có >=2 cột (sách thường có vài trang bảng đặt cạnh nhau: không tính)
            "multi_col": sum(len(p["cols"]) > 1 for p in pages.values()) >= max(1, len(pages) / 2)}


def _col_of(layout_page: dict, bbox: list) -> int:
    cols = layout_page["cols"]
    if bbox[2] - bbox[0] >= 600:
        return -1
    return min(range(len(cols)), key=lambda i: abs(cols[i][0] - bbox[0]))


def _sectpr(lp: dict, first: bool) -> str:
    tw = lambda pt: int(round(pt * TWIP))
    cols = lp["cols"]
    if len(cols) > 1:
        gaps = [tw((cols[i + 1][0] - cols[i][1]) / 1000 * lp["w"]) for i in range(len(cols) - 1)] + [0]
        cx = "".join(f'<w:col w:w="{tw((c[1] - c[0]) / 1000 * lp["w"])}" w:space="{max(gaps[i], 0)}"/>' for i, c in enumerate(cols))
        colxml = f'<w:cols w:num="{len(cols)}" w:equalWidth="0">{cx}</w:cols>'
    else:
        colxml = '<w:cols w:num="1"/>'
    land = ' w:orient="landscape"' if lp["w"] > lp["h"] else ""
    return ("<w:sectPr>" + ("" if first else '<w:type w:val="nextPage"/>')
            + f'<w:pgSz w:w="{tw(lp["w"])}" w:h="{tw(lp["h"])}"{land}/>'
            + f'<w:pgMar w:top="{tw(lp["mt"])}" w:right="{tw(lp["mr"])}" w:bottom="{tw(lp["mb"])}" w:left="{tw(lp["ml"])}" '
              'w:header="360" w:footer="360" w:gutter="0"/>' + colxml + "</w:sectPr>")


_TINY = '<w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>'


def _raw(xml: str) -> str:
    return "\n\n```{=openxml}\n" + xml + "\n```\n\n"


def insert_layout_markers(md: str, items: List[dict], layout: dict, column_breaks: bool = True) -> str:
    """Chèn ngắt cột / ngắt section (raw openxml) trước khối đầu mỗi cột/trang mới. Chỉ dùng khi tài liệu có trang nhiều cột."""
    found, pos = [], 0
    for it in items:
        if it.get("type") not in KEEP or not it.get("bbox"):
            continue
        t = it["type"]
        if t == "image" and it.get("img_path"):
            rx = re.escape(it["img_path"])
        elif t == "table" and it.get("table_body"):
            rx = re.escape(it["table_body"][:40])
        else:
            tok = _plain(re.sub(r"^\$\$|\$\$$", "", (it.get("text") or "").strip()))[:25].split()
            if not tok or len(" ".join(tok)) < 4:
                continue
            rx = r"\s+".join(re.escape(x) for x in tok)
        m = re.compile(rx).search(md, pos)
        if m:
            at = md.rfind("\n", 0, m.start()) + 1
            if md.count("$$", 0, at) % 2 == 0:       # không bao giờ chèn vào GIỮA khối công thức $$...$$ (làm vỡ công thức)
                found.append((at, it))
            pos = m.end()
    ins, cur_pg, cur_col, pages = [], None, 0, layout["pages"]
    for at, it in found:
        pg = it.get("page_idx", 0)
        lp = pages[str(pg)] if str(pg) in pages else pages[pg]
        col = _col_of(lp, it["bbox"])
        if cur_pg is None:
            cur_pg, cur_col = pg, max(col, 0)
            continue
        if pg != cur_pg:
            prev = pages[str(cur_pg)] if str(cur_pg) in pages else pages[cur_pg]
            ins.append((at, _raw(f'<w:p><w:pPr>{_TINY}{_sectpr(prev, cur_pg == min(map(int, pages)))}</w:pPr></w:p>')))
            cur_pg, cur_col = pg, max(col, 0)
        elif column_breaks and col > cur_col:
            ins.append((at, _raw(f'<w:p><w:pPr>{_TINY}</w:pPr><w:r><w:br w:type="column"/></w:r></w:p>')))
            cur_col = col
    for at, xml in sorted(ins, key=lambda x: -x[0]):
        md = md[:at] + xml + md[at:]
    return md


def apply_image_widths(md: str, widths: Dict[str, float]) -> str:
    """![](.../abc.jpg) -> ![](.../abc.jpg){width=NNpt} theo bbox (pandoc đọc DPI của ảnh nên hay sai kích thước)."""
    def sub(m):
        name = Path(m.group(1)).name
        w = widths.get(name)
        return f"![]({m.group(1)}){{width={w}pt}}" if w and w >= 8 else m.group(0)
    return re.sub(r"!\[\]\(([^)\n]+)\)(?!\{)", sub, md)


def apply_layout(docx_path: Path, layout: dict) -> None:
    """Section cuối (body sectPr): khổ giấy/lề/cột trang cuối; cỡ chữ thân bài = cỡ chữ PDF."""
    from docx import Document
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    doc = Document(str(docx_path))
    pages = layout["pages"]
    last = dict(pages[max(pages, key=lambda k: int(k))])
    if not layout["multi_col"]:      # 1 cột: một bộ lề chung cho cả tài liệu (trung vị các trang) thay vì lề của riêng trang cuối
        import statistics
        for k in ("ml", "mr", "mt", "mb"):
            last[k] = statistics.median(p[k] for p in pages.values())
    body = doc.element.body
    sect = body.find(qn("w:sectPr"))
    if sect is not None:
        keep_hdr = [e for e in sect if e.tag in (qn("w:headerReference"), qn("w:footerReference"))]
        new = parse_xml(_sectpr(last, not layout["multi_col"]).replace("<w:sectPr>", f"<w:sectPr {nsdecls('w')}>", 1))
        for e in list(sect):
            sect.remove(e)
        for e in keep_hdr + list(new):
            sect.append(e)
    half = int(round(layout["font_pt"] * 2))
    st = doc.styles.element
    dd = st.find(qn("w:docDefaults"))
    if dd is not None:
        for sz in dd.iter(qn("w:sz")):
            sz.set(qn("w:val"), str(half))
        for sz in dd.iter(qn("w:szCs")):
            sz.set(qn("w:val"), str(half))
    from docx.shared import Pt
    base = layout["font_pt"]
    # pandoc: tiêu đề 14-20pt + đoạn cách 9pt -> tràn cột/trang so với PDF. Co theo cỡ chữ thân bài của PDF.
    for name, mult in (("Normal", 1), ("Body Text", 1), ("First Paragraph", 1), ("Compact", 1), ("Block Text", 1),
                       ("Heading 1", 1.4), ("Heading 2", 1.25), ("Heading 3", 1.15), ("Heading 4", 1.1),
                       ("Heading 5", 1.05), ("Heading 6", 1.0), ("Title", 1.5)):
        try:
            stl = doc.styles[name]
        except KeyError:
            continue
        stl.font.size = Pt(round(base * mult * 2) / 2)
        pf = stl.paragraph_format
        pf.line_spacing = 1.0
        head = name.startswith(("Heading", "Title"))
        pf.space_before = Pt(base * 0.5 if head else 0)
        pf.space_after = Pt(base * (0.25 if head else 0.3))
    doc.save(str(docx_path))
