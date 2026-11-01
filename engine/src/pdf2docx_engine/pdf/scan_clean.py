"""Tiền xử lý PDF scan/chụp ảnh sách TRƯỚC khi đưa vào MinerU.

Vấn đề (LoiCanSua.docx, lỗi 3 "lấy trang bên kia"): ảnh chụp sách để lộ một dải trang kế bên
ngay sau rãnh gáy. MinerU OCR luôn dải đó -> chèn các dòng cụt như "rc có dạng", "4, biểu thức A"
vào giữa đề bài.

Cách xử lý: tìm rãnh gáy (cột tối, hẹp, mà phía ngoài nó SÁNG hơn hẳn = có trang khác) ở mỗi bên rìa
và tô trắng toàn bộ phần phía ngoài rãnh. Chỉ tác động khi chắc chắn; trang không có rãnh -> giữ nguyên.

GIỚI HẠN ĐÃ BIẾT: chỉ bắt được trường hợp có rãnh gáy tối (đã thử trên 95 trang Toan11: 47 trang bị che,
kiểm tra bằng mắt trên 4 trang mẫu). Chữ "lộ qua giấy" ở mép KHÔNG có rãnh tối (vd mép phải các trang lẻ
của Toan11) gần như đậm bằng chữ chính, không có khoảng trống ngăn cách -> chưa tách được bằng heuristic
đơn giản; cần bbox của MinerU (middle.json) để lọc sau OCR.

Chỉ chạy cho PDF dạng ảnh (không có text layer). Cần: pymupdf, numpy, pillow (đã có / cài kèm).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

try:
    import pymupdf as fitz  # tên mới (PyMuPDF >= 1.24.3)
except ImportError:  # pragma: no cover
    try:
        import fitz  # tên cũ
    except ImportError:
        fitz = None


def is_image_pdf(pdf_path: Path, sample_pages: int = 8, min_chars: int = 40) -> bool:
    """True nếu các trang mẫu gần như không có text layer (PDF scan)."""
    doc = fitz.open(str(pdf_path))
    n = min(sample_pages, len(doc))
    if n == 0:
        return False
    idxs = np.linspace(0, len(doc) - 1, n).astype(int)
    txt = sum(len(doc[int(i)].get_text("text").strip()) for i in idxs)
    return txt < min_chars * n


def _smooth(a: np.ndarray, k: int) -> np.ndarray:
    k = max(3, k | 1)
    pad = k // 2
    return np.convolve(np.pad(a, pad, mode="edge"), np.ones(k) / k, mode="valid")


def find_gutter_cuts(gray: np.ndarray, *, edge_frac: float = 0.30, depth: float = 0.72,
                     outer_gain: float = 1.25, min_off: float = 0.02):
    """Trả (left_cut_px | None, right_cut_px | None). Phần x < left_cut và x > right_cut sẽ bị tô trắng.

    Điều kiện nhận một rãnh gáy ở rìa trái (đối xứng cho rìa phải):
      - cực tiểu độ sáng cột nằm trong `edge_frac` ngoài cùng, cách mép ít nhất `min_off`;
      - tối hơn vùng giữa trang ít nhất (1-depth) (valley < depth * median giữa);
      - phía ngoài rãnh sáng hơn rãnh >= outer_gain lần (tức có một trang/giấy khác ngoài đó,
        chứ không phải chỉ là nền bàn tối) -> mới đáng che.
    """
    h, w = gray.shape
    band = gray[int(h * 0.08): int(h * 0.92)]
    col = _smooth(band.mean(axis=0), max(5, w // 90))
    mid = float(np.median(col[int(w * 0.30): int(w * 0.70)]))
    lim = int(w * edge_frac)
    off = max(2, int(w * min_off))
    left = right = None

    # trái
    seg = col[:lim]
    x = int(np.argmin(seg))
    if x >= off and seg[x] < depth * mid:
        outer = float(seg[:x].mean()) if x > 0 else 0.0
        if outer >= outer_gain * float(seg[x]):
            left = x + max(2, w // 200)
    # phải
    seg = col[w - lim:]
    x = int(np.argmin(seg))
    xr = w - lim + x
    if (w - 1 - xr) >= off and seg[x] < depth * mid:
        outer = float(col[xr + 1:].mean()) if xr + 1 < w else 0.0
        if outer >= outer_gain * float(seg[x]):
            right = xr - max(2, w // 200)
    return left, right


def clean_scan_pdf(pdf_path: Path, out_pdf: Path, dpi: int = 200, jpeg_quality: int = 88,
                   report_path: Path | None = None) -> tuple[Path, dict]:
    """Dựng PDF mới (mỗi trang là ảnh đã che trang bên cạnh). Trả (out_pdf, thống kê)."""
    if fitz is None:
        raise RuntimeError("Cần `pip install pymupdf`")
    from PIL import Image

    src = fitz.open(str(pdf_path))
    dst = fitz.open()
    cut_pages = []
    for pno in range(len(src)):
        page = src[pno]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        gray = np.asarray(img.convert("L"), dtype=float)
        left, right = find_gutter_cuts(gray)
        if left is not None or right is not None:
            arr = np.asarray(img).copy()
            # tô bằng màu giấy (phân vị 90 độ sáng vùng giữa) thay vì trắng tuyệt đối, tránh viền gắt
            h, w = gray.shape
            paper = np.percentile(arr[int(h * .1):int(h * .9), int(w * .3):int(w * .7)].reshape(-1, 3), 90, axis=0)
            if left is not None:
                arr[:, :left] = paper
            if right is not None:
                arr[:, right:] = paper
            img = Image.fromarray(arr.astype("uint8"))
            cut_pages.append({"page": pno + 1, "left_px": left, "right_px": right, "width_px": w})
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality)
        new = dst.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(out_pdf), deflate=True, garbage=3)
    stats = {"pages": len(src), "pages_masked": len(cut_pages), "masked": cut_pages}
    if report_path:
        import json
        report_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_pdf, stats