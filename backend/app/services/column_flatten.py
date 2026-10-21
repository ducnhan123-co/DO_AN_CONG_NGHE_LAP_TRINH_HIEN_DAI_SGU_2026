"""Chế độ "chuyển thành 1 cột đúng thứ tự đọc" cho PDF nhiều cột (2 hoặc 3 cột trên một trang).

Vì sao không nhờ MinerU tự đọc cả trang: với trang 3 cột nó có thể đọc xen kẽ theo hàng hoặc đảo cột.
Cách làm chắc chắn (cùng ý tưởng `column_split` của rag_toan cho tờ khung có đường kẻ):

    mỗi trang -> cắt theo rãnh trắng giữa các cột -> mỗi cột là 1 "dải" (1 trang PDF riêng, cao bằng cả trang)
    -> MinerU đọc từng dải như tài liệu 1 cột  -> ghép theo thứ tự  cột 1, cột 2, cột 3 của trang 1,
       rồi cột 1, 2, 3 của trang 2 ...  -> Word 1 cột, trang thường.

Bộ dò rãnh theo cùng nguyên lý `columns.detect_columns` của rag_toan (rãnh trắng dọc suốt chiều cao trang), nhưng
chịu được các thứ rất hay gặp ở tờ nhiều cột mà bản gốc làm nó "mù": dải nền màu / đường kẻ ngang / tiêu đề
trải ngang cả trang (các hàng gần như kín mực bị bỏ qua khi xét rãnh). Kết quả là "plan" CÙNG ĐỊNH DẠNG với
`column_split.plan_strips`, nên `build_strips_pdf` / `remap_content_list` dùng lại được.

Tờ có khung kẻ (cheat-sheet) vẫn đi đường `plan_strips` sẵn có (xem pipeline); module này lo phần còn lại.
Phụ thuộc: pymupdf, numpy.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

# Rãnh giữa cột chỉ cần rộng ~0,8% bề ngang trang (mặc định của detect_columns là 1,2%). Đủ nhạy để tách cột chữ
# khỏi một cột bìa/nền màu đứng sát (như tờ gấp 3 cột), mà vẫn không bắt nhầm khoảng trắng giữa các từ
# (rãnh phải trống SUỐT chiều cao trang).
MIN_GUTTER = 0.008
MIN_COL = 0.08          # như detect_columns: cột hẹp hơn 8% bề ngang không tính là cột
WIDE_ROW = 0.55         # hàng có > 55% bề ngang là mực = dải nền/đường kẻ/tiêu đề đặc -> bỏ qua khi xét rãnh
GUTTER_INK = 0.02       # rãnh được phép lẫn tới 2% số hàng có mực (chữ tiêu đề lọt qua); chữ trong cột thì >= ~10%
MIN_FILL = 0.30         # cột "dày chữ" = có mực ở >= 30% số hàng của trang. Cần >= 2 cột dày mới coi là trang nhiều cột
MAX_COLS = 6
DPI = 100


def detect_column_segments(gray, ink_thr: int = 170, min_gutter: float = MIN_GUTTER, min_col: float = MIN_COL,
                           wide_row: float = WIDE_ROW, gutter_ink: float = GUTTER_INK):
    """Các đoạn x (x0, x1) của từng cột trên 1 trang (ảnh xám numpy), dựa vào rãnh trắng dọc."""
    h, w = gray.shape
    lo, hi = int(.05 * h), int(.95 * h)
    ink = gray[lo:hi] < ink_thr
    if ink.shape[0] == 0:
        return []
    keep = ink.mean(axis=1) < wide_row
    if keep.sum() < 0.2 * ink.shape[0]:            # gần như cả trang là nền/ảnh đặc: không có gì để dò
        return []
    frac = ink[keep].mean(axis=0)
    empty = frac < gutter_ink
    segs, start, gap, last = [], None, 0, 0
    for x in range(w):
        if not empty[x]:
            if start is None:
                start = x
            gap, last = 0, x
        elif start is not None:
            gap += 1
            if gap >= min_gutter * w:
                segs.append((start, last))
                start = None
    if start is not None:
        segs.append((start, last))
    segs = [sg for sg in segs if (sg[1] - sg[0]) >= min_col * w]
    # Chống dò nhầm: trang THƯA (vài dòng giống cấu trúc nhau, bảng số thẳng hàng...) cũng có "rãnh" thẳng hàng.
    # Trang nhiều cột thật phải có >= 2 cột chữ dày; cột phụ thưa (bìa, ghi chú) vẫn được giữ nếu đứng cạnh chúng.
    rows_all = ink.shape[0]
    dense = sum(1 for (a, b) in segs if ink[:, a:b + 1].any(axis=1).sum() >= MIN_FILL * rows_all)
    return segs if dense >= 2 else []


def plan_whitespace_strips(pdf_path, dpi: int = DPI, min_gutter: float = MIN_GUTTER,
                           max_pages: int = 5000) -> Optional[dict]:
    """Plan {'pages','ncols','strips','bands','banners','page_pt','mode'} hoặc None nếu PDF không phải nhiều cột.

    Trang tìm được >= 2 cột -> 1 dải cho mỗi cột (từ trái sang phải). Trang 1 cột (bìa, trang hình...) -> 1 dải cả trang.
    Chỉ dùng plan khi >= 50% số trang là nhiều cột; ngược lại trả None (để MinerU đọc như thường)."""
    import numpy as np
    import pymupdf as fitz

    doc = fitz.open(str(pdf_path))
    n = min(len(doc), max_pages)
    strips: List[dict] = []
    bands: List[dict] = []
    per_page_cols: List[int] = []
    for pno in range(n):
        page = doc[pno]
        r = page.rect
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
        segs = detect_column_segments(gray, min_gutter=min_gutter)
        if not (2 <= len(segs) <= MAX_COLS):
            segs = []
        per_page_cols.append(len(segs))

        k = max(1, len(segs))
        if segs:                                   # ranh giới = giữa rãnh trắng của 2 cột liền kề
            cuts = [(segs[i][1] + segs[i + 1][0]) / 2.0 for i in range(len(segs) - 1)]
            bounds_px = [0.0] + cuts + [float(pix.width)]
        else:
            bounds_px = [0.0, float(pix.width)]
        sx = r.width / pix.width
        bounds = [r.x0 + b * sx for b in bounds_px]
        bd = {"page": pno, "ncols": k, "widths": [bounds[i + 1] - bounds[i] for i in range(k)],
              "banner": False, "first": True, "strips": []}
        bands.append(bd)
        for ci in range(k):
            strips.append({"idx": len(strips), "page": pno, "band": len(bands) - 1, "col": ci, "ncols": k,
                           "rect": [bounds[ci], r.y0, bounds[ci + 1], r.y1]})
            bd["strips"].append(len(strips) - 1)

    multi = sum(1 for c in per_page_cols if c >= 2)
    if n == 0 or multi < 0.5 * n:
        return None
    dominant = Counter(c for c in per_page_cols if c >= 2).most_common(1)[0][0]
    return {"pages": n, "ncols": dominant, "strips": strips, "bands": bands, "banners": {},
            "page_pt": [doc[0].rect.width, doc[0].rect.height], "mode": "whitespace"}


_BAND_MARK = re.compile(r"^ZZBAND\d+ZZ$", re.M)


def strip_layout_markers(E, md: str) -> str:
    """Bỏ các dấu bố cục (ngắt cột/ngắt trang/ZZBANDnZZ) mà `content_list_to_docx_md` chèn cho chế độ GIỮ cột,
    để chữ chảy liền thành 1 cột."""
    cs = E.column_split
    for mark in (cs.COL_BREAK, cs.PAGE_BREAK):
        md = md.replace(mark, "")
    md = _BAND_MARK.sub("", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
