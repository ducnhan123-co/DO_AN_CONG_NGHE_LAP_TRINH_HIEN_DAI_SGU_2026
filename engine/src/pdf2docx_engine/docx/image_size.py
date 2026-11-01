"""Đặt kích thước ảnh trong DOCX = kích thước ảnh đó trong PDF gốc.

MinerU cắt mỗi hình từ trang PDF được render ở 200 dpi (đã đo bằng khớp mẫu ảnh lên trang PDF:
8/8 ảnh BacDaihoc và 3/3 ảnh Toan11 khớp tốt nhất ở 200 dpi). Vì vậy:

    kích thước thật (inch) = số pixel / 200

Ảnh trong Markdown không mang thông tin DPI nên Pandoc tự đoán (thường 96 dpi) -> ảnh to gấp ~2 lần
so với PDF. Hàm dưới thêm thuộc tính `{width=..in}` cho từng ảnh (Pandoc tôn trọng thuộc tính này);
chiều cao tự theo tỉ lệ. Ảnh đã có thuộc tính sẵn thì giữ nguyên.
"""
from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from PIL import Image

MINERU_CROP_DPI = 200

_IMG = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)(?!\{)")


def _pixel_size(ref: str, base_dir: Path):
    ref = ref.strip().strip("<>")
    try:
        if ref.startswith("data:image"):
            payload = ref.split(",", 1)[1]
            return Image.open(io.BytesIO(base64.b64decode(payload))).size
        if ref.startswith(("http://", "https://")):
            return None
        p = (base_dir / ref)
        if p.exists():
            return Image.open(p).size
    except Exception:
        return None
    return None


def apply_pdf_image_sizes(md: str, base_dir: Path, dpi: float = MINERU_CROP_DPI,
                          scale: float = 1.0) -> tuple[str, int]:
    """Trả (md_mới, số ảnh đã đặt kích thước). `scale` để thu/phóng đồng loạt (1.0 = đúng như PDF)."""
    n = 0

    def sub(m):
        nonlocal n
        size = _pixel_size(m.group(2), base_dir)
        if not size:
            return m.group(0)
        w_in = size[0] / dpi * scale
        n += 1
        return f"![{m.group(1)}]({m.group(2)}){{width={w_in:.3f}in}}"

    return _IMG.sub(sub, md), n