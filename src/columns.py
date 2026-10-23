"""Giữ bố cục NHIỀU CỘT khi chuyển PDF -> Word.

Pandoc luôn xuất 1 cột. Muốn có cột trong Word cần 2 việc:
  1. Đặt section của DOCX thành N cột + đúng khổ giấy của PDF  -> apply_section_columns()
  2. Chèn "ngắt cột" đúng chỗ mỗi cột của PDF kết thúc          -> insert_column_breaks()

Cách tìm chỗ ngắt cột (không cần toạ độ của MinerU, chạy được cả khi PDF không có lớp chữ):
  - render từng trang thành ảnh, tìm các "rãnh trắng" dọc -> biết trang có mấy cột
  - OCR từng cột (tesseract)
  - duyệt các đoạn Markdown theo thứ tự đọc, đoạn nào nằm ở cột nào thì khi chuyển cột -> chèn 1 ngắt cột
Phụ thuộc (tuỳ chọn): pypdfium2 hoặc pdftoppm, opencv-python, numpy, pytesseract + tesseract.
Thiếu cái nào thì tự rơi về chế độ "chia cột liên tục" (không ngắt cột), không báo lỗi.
"""
import copy
import re
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BREAK_MARK = '```{=openxml}\n<w:p><w:r><w:br w:type="column"/></w:r></w:p>\n```'
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# ------------------------------------------------------------ render + cột
def n_pages(pdf_path: Path) -> int:
    try:
        import pypdfium2 as pdfium
        return len(pdfium.PdfDocument(str(pdf_path)))
    except ImportError:
        out = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True).stdout
        return int(re.search(r"Pages:\s+(\d+)", out).group(1))


def render_pages(pdf_path: Path, dpi: int = 200, pages: Optional[List[int]] = None):
    """-> (list ảnh xám numpy, (w_pt, h_pt) trang đầu được render). pages: chỉ số 0-based, None = tất cả."""
    import numpy as np
    imgs = []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(pdf_path))
        for i in (pages if pages is not None else range(len(pdf))):
            imgs.append(np.array(pdf[i].render(scale=dpi / 72).to_pil().convert("L")))
    except ImportError:
        import cv2
        for i in (pages if pages is not None else range(n_pages(pdf_path))):
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", "-f", str(i + 1),
                                "-l", str(i + 1), str(pdf_path), str(Path(td) / "p")],
                               check=True, capture_output=True)
                f = next(Path(td).glob("p-*.png"))
                imgs.append(cv2.imread(str(f), cv2.IMREAD_GRAYSCALE))
    h, w = imgs[0].shape
    return imgs, (w * 72 / dpi, h * 72 / dpi)


def detect_columns(gray, ink_thr: int = 170, min_gutter: float = 0.012,
                   min_col: float = 0.08) -> List[Tuple[int, int]]:
    """Các đoạn x (x0, x1) của từng cột, dựa vào rãnh trắng dọc."""
    import numpy as np
    h, w = gray.shape
    band = gray[int(.05 * h):int(.95 * h)] < ink_thr
    ink_frac = band.mean(axis=0)
    empty = ink_frac < 0.01
    segs, start, gap = [], None, 0
    for x in range(w):
        if not empty[x]:
            if start is None:
                start = x
            gap = 0
            last = x
        elif start is not None:
            gap += 1
            if gap >= min_gutter * w:
                segs.append((start, last)); start = None
    if start is not None:
        segs.append((start, last))
    return [s for s in segs if (s[1] - s[0]) >= min_col * w]


def _ocr(gray_crop, lang: str) -> str:
    import pytesseract
    return pytesseract.image_to_string(gray_crop, lang=lang, config="--psm 4")


def drop_ocr_details(md: str) -> str:
    """Bỏ khối <details>...</details> (chữ OCR trong hình, mermaid đoán từ ảnh) khỏi MD dùng cho DOCX;
    ảnh gốc vẫn còn nên không mất thông tin."""
    return re.sub(r"<details>.*?</details>\s*", "", md, flags=re.S)


# ----------------------------------------------------------- khớp đoạn <-> cột
def _norm(s: str) -> str:
    s = re.sub(r"\$[^$]*\$", " ", s)
    return re.sub(r"[^0-9a-zà-ỹ]", "", s.lower())


def _anchors(par: str) -> List[str]:
    p = par.strip()
    if not p or p.startswith(("$$", "![", "<details", "```", "[Hình")):
        return []
    if p.startswith("|"):
        p = " ".join(c for c in p.splitlines()[0].split("|"))
    n = _norm(re.sub(r"^#+\s*", "", p))
    if len(n) < 6:
        return []
    return [n[:14]] + ([n[14:28]] if len(n) >= 28 else [])


def layout_of(pdf_path: Path, lang: str = "eng", dpi: int = 200, max_pages: int = 40) -> Optional[dict]:
    """{'n_cols', 'page_pt', 'cells': [(page, col, ocr_chuẩn_hoá)]} hoặc None nếu tài liệu 1 cột.
    Thăm dò ~6 trang ở 100 dpi trước (rẻ); chỉ OCR toàn bộ khi thật sự nhiều cột và <= max_pages trang."""
    try:
        total = n_pages(pdf_path)
        probe = sorted({round(i * (total - 1) / 5) for i in range(6)}) if total > 6 else list(range(total))
        pimgs, _ = render_pages(pdf_path, 100, probe)
        pc = Counter(len(detect_columns(g)) for g in pimgs)
        pc.pop(0, None)
        n_cols = pc.most_common(1)[0][0] if pc else 1
        if n_cols < 2 or pc[n_cols] < 0.5 * len(pimgs):
            return None
        imgs, page_pt = render_pages(pdf_path, dpi)
        per_page = [detect_columns(g) for g in imgs]
    except Exception as e:
        print(f"[columns] Không render/nhận dạng cột được ({e}).")
        return None
    if total > max_pages:
        print(f"[columns] {total} trang > {max_pages}: chỉ chia {n_cols} cột liên tục, không OCR để ngắt cột.")
        return {"n_cols": n_cols, "page_pt": page_pt, "cells": []}
    cells = []
    try:
        for pi, (g, cols) in enumerate(zip(imgs, per_page)):
            if len(cols) != n_cols:        # trang có số cột khác: chia đều theo bề rộng
                w = g.shape[1]
                cols = [(int(i * w / n_cols), int((i + 1) * w / n_cols) - 1) for i in range(n_cols)]
            for ci, (x0, x1) in enumerate(cols):
                pad = 6
                cells.append((pi, ci, _norm(_ocr(g[:, max(0, x0 - pad):x1 + pad], lang))))
    except Exception as e:
        print(f"[columns] OCR không chạy được ({e}) -> chỉ chia cột liên tục, không ngắt cột.")
        return {"n_cols": n_cols, "page_pt": page_pt, "cells": []}
    return {"n_cols": n_cols, "page_pt": page_pt, "cells": cells}


def insert_column_breaks(md: str, layout: Optional[dict]) -> str:
    """Chèn ngắt cột vào Markdown tại chỗ đoạn chuyển sang cột kế tiếp (theo thứ tự đọc)."""
    if not layout or not layout["cells"]:
        return md
    cells = layout["cells"]
    pars = re.split(r"\n\s*\n", md)
    ptr, out, n_breaks = 0, [], 0
    for par in pars:
        anc = _anchors(par)
        if anc:
            hit = next((j for j in range(ptr, min(ptr + 2, len(cells)))
                        if any(a in cells[j][2] for a in anc)), None)
            if hit is not None:
                for _ in range(hit - ptr):
                    out.append(BREAK_MARK); n_breaks += 1
                ptr = hit
        out.append(par)
    print(f"[columns] Chèn {n_breaks} ngắt cột ({layout['n_cols']} cột/trang, "
          f"{len(cells) // layout['n_cols']} trang PDF).")
    return "\n\n".join(out)


# ------------------------------------------------------------- sửa DOCX
def _merge_break_paragraphs(root) -> int:
    """Đoạn chỉ chứa ngắt cột -> chuyển ngắt vào đầu đoạn kế tiếp (khỏi dòng trống đầu cột)."""
    q = lambda t: f"{{{W}}}{t}"
    n = 0
    for p in list(root.iter(q("p"))):
        kids = [k for k in p if k.tag != q("pPr")]
        if len(kids) == 1 and kids[0].tag == q("r") and \
                kids[0].find(q("br")) is not None and kids[0].find(q("br")).get(q("type")) == "column":
            nxt = p.getnext()
            while nxt is not None and nxt.tag in (q("bookmarkStart"), q("bookmarkEnd")):
                nxt = nxt.getnext()
            if nxt is not None and nxt.tag == q("p"):
                run = copy.deepcopy(kids[0])
                ppr = nxt.find(q("pPr"))
                nxt.insert(1 if ppr is not None else 0, run)
                p.getparent().remove(p); n += 1
    return n


_SECT_ORDER = ["headerReference", "footerReference", "footnotePr", "endnotePr", "type", "pgSz",
               "pgMar", "paperSrc", "pgBorders", "lnNumType", "pgNumType", "cols", "formProt",
               "vAlign", "noEndnote", "titlePg", "textDirection", "bidi", "rtlGutter", "docGrid"]


def apply_section_columns(docx_path: Path, n_cols: int, page_pt: Tuple[float, float],
                          margin_mm: float = 8, gap_mm: float = 6,
                          body_pt: Optional[float] = None, space_scale: float = 0.4,
                          img_max_frac: float = 0.75) -> Path:
    """Đặt khổ giấy = khổ PDF, N cột, co ảnh vừa bề rộng cột, (tuỳ chọn) đổi cỡ chữ nền."""
    from lxml import etree
    docx_path = Path(docx_path)
    w_tw, h_tw = round(page_pt[0] * 20), round(page_pt[1] * 20)
    mar, gap = round(margin_mm * 56.7), round(gap_mm * 56.7)
    col_w_emu = int((w_tw - 2 * mar - (n_cols - 1) * gap) / n_cols * 635)
    img_max = int(col_w_emu * img_max_frac)

    with zipfile.ZipFile(docx_path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    root = etree.fromstring(files["word/document.xml"])
    q = lambda t: f"{{{W}}}{t}"

    sect = root.find(f".//{q('body')}/{q('sectPr')}")
    if sect is None:
        sect = etree.SubElement(root.find(q("body")), q("sectPr"))
    for tag in ("pgSz", "pgMar", "cols"):
        for e in sect.findall(q(tag)):
            sect.remove(e)
    new = {
        "pgSz": {"w": str(w_tw), "h": str(h_tw), **({"orient": "landscape"} if w_tw > h_tw else {})},
        "pgMar": {"top": str(mar), "right": str(mar), "bottom": str(mar), "left": str(mar),
                  "header": "284", "footer": "284", "gutter": "0"},
        "cols": {"num": str(n_cols), "space": str(gap), "equalWidth": "1"},
    }
    for tag, attrs in new.items():
        el = etree.Element(q(tag), {q(k): v for k, v in attrs.items()})
        rank = _SECT_ORDER.index(tag)
        pos = len(sect)
        for i, ch in enumerate(sect):
            name = etree.QName(ch).localname
            if name in _SECT_ORDER and _SECT_ORDER.index(name) > rank:
                pos = i; break
        sect.insert(pos, el)

    n_merged = _merge_break_paragraphs(root)

    # co ảnh không vượt bề rộng cột
    WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    n_img = 0
    for inl in root.iter(f"{{{WP}}}inline"):
        ext = inl.find(f"{{{WP}}}extent")
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        if cx > img_max:
            k = img_max / cx
            ext.set("cx", str(int(cx * k))); ext.set("cy", str(int(cy * k)))
            for a in inl.iter(f"{{{A}}}ext"):
                a.set("cx", str(int(int(a.get("cx")) * k))); a.set("cy", str(int(int(a.get("cy")) * k)))
            n_img += 1
    files["word/document.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    if body_pt and "word/styles.xml" in files:
        st = etree.fromstring(files["word/styles.xml"])
        dflt = st.find(f".//{q('docDefaults')}//{q('sz')}")
        base = int(dflt.get(q("val"))) if dflt is not None else 24
        k = body_pt * 2 / base
        for tag in ("sz", "szCs"):
            for e in st.iter(q(tag)):
                e.set(q("val"), str(max(2, round(int(e.get(q("val"))) * k))))
        for e in st.iter(q("spacing")):                 # khoảng cách trước/sau đoạn co theo, mạnh hơn chữ
            for a in ("before", "after"):
                if e.get(q(a)) is not None:
                    e.set(q(a), str(round(int(e.get(q(a))) * k * space_scale)))
        files["word/styles.xml"] = etree.tostring(st, xml_declaration=True, encoding="UTF-8", standalone=True)

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    tmp.replace(docx_path)
    print(f"[columns] DOCX: {n_cols} cột, khổ {page_pt[0]:.0f}x{page_pt[1]:.0f}pt, "
          f"gộp {n_merged} ngắt cột, co {n_img} ảnh.")
    return docx_path