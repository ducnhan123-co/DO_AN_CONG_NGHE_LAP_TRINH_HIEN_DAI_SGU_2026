"""Tiền xử lý PDF scan độ phân giải thấp/nhòe trước khi đưa MinerU (OCR + nhận dạng công thức).

Đã đo (Apple M5, 8 trang toán, F1 từ so với lớp chữ gốc):
  scan 150dpi hơi nhòe/nghiêng   không xử lý 0.25  ->  phóng to 2400px + làm nét 0.81
  ảnh 100dpi                     không xử lý 0.64  ->  0.90
  scan 150dpi tốt / sách cổ      0.911 / 0.860     ->  0.912 / 0.859 (không hại)
Làm nét mạnh, khử nhiễu median, nhị phân hoá đều làm TỆ hơn (xem docs). Chỉ xử lý trang là MỘT ảnh toàn trang, không có chữ,
độ phân giải hiệu dụng < 250dpi; trang khác (có chữ thật) được chép nguyên.
"""
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIN_DPI = 250        # >= mức này thì ảnh đủ nét, bỏ qua
TARGET_W = 2400      # ~290dpi trên khổ A4


def _page_scan_image(page):
    """Ảnh nhúng nếu trang là một ảnh phủ gần hết trang và không có chữ; None nếu không phải trang scan."""
    import fitz
    if len(page.get_text().strip()) >= 20:
        return None
    imgs = page.get_images(full=True)
    if len(imgs) != 1:
        return None
    xref = imgs[0][0]
    rects = page.get_image_rects(xref)
    if not rects or rects[0].width * rects[0].height < 0.7 * page.rect.width * page.rect.height:
        return None
    pix = fitz.Pixmap(page.parent, xref)
    if pix.n - pix.alpha != 3 and pix.n - pix.alpha != 1:      # CMYK/khác -> về RGB
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if pix.alpha:
        pix = fitz.Pixmap(pix, 0)
    return pix


def _enhance_bytes(mode: str, size: tuple, samples: bytes) -> bytes:
    from PIL import Image, ImageFilter
    im = Image.frombytes(mode, size, samples)
    if im.width < TARGET_W:
        k = TARGET_W / im.width
        im = im.resize((TARGET_W, int(im.height * k)), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.6, percent=110, threshold=3))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=93)
    return out.getvalue()


def enhance_if_needed(pdf_path: Path, dst_dir: Path, min_dpi: int = MIN_DPI) -> Path:
    """Trả về PDF đã nâng chất lượng (cùng tên file để tên output MinerU không đổi) hoặc chính pdf_path nếu không cần."""
    import fitz
    try:
        src = fitz.open(str(pdf_path))
    except Exception:  # noqa: BLE001
        return pdf_path
    todo = {}
    for i, page in enumerate(src):
        pix = _page_scan_image(page)
        if pix is not None and pix.width / (page.rect.width / 72) < min_dpi:
            todo[i] = (("RGB" if pix.n == 3 else "L"), (pix.width, pix.height), pix.samples)
    if not todo:
        return pdf_path
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / pdf_path.name
    if dst.exists() and dst.stat().st_mtime >= pdf_path.stat().st_mtime:
        return dst
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {i: ex.submit(_enhance_bytes, *a) for i, a in todo.items()}
        out = fitz.open()
        for i, page in enumerate(src):
            if i in futs:
                np_ = out.new_page(width=page.rect.width, height=page.rect.height)
                np_.insert_image(np_.rect, stream=futs[i].result())
            else:
                out.insert_pdf(src, from_page=i, to_page=i)
    out.save(str(dst), deflate=True)
    print(f"[MinerU] {len(todo)}/{len(src)} trang scan độ phân giải thấp -> phóng to + làm nét: {dst}")
    return dst
