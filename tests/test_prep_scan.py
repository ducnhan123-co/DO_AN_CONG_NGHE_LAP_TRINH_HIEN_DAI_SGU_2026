import io

import pytest

fitz = pytest.importorskip("fitz")
from PIL import Image

from llm.src.prep_scan import enhance_if_needed


def _pdf(tmp_path, px, with_text=False, name="s.pdf"):
    im = Image.new("RGB", (px, int(px * 1.414)), "white")
    b = io.BytesIO()
    im.save(b, "JPEG")
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_image(pg.rect, stream=b.getvalue())
    if with_text:
        pg.insert_text((50, 50), "Day la trang co lop chu that, khong phai scan thuan.")
    p = tmp_path / name
    doc.save(str(p))
    return p


def test_low_dpi_scan_is_upscaled_and_keeps_name(tmp_path):
    src = _pdf(tmp_path, 800)                                   # ~97dpi
    out = enhance_if_needed(src, tmp_path / "enh")
    assert out != src and out.name == src.name
    pg = fitz.open(str(out))[0]
    assert fitz.Pixmap(pg.parent, pg.get_images()[0][0]).width >= 2400
    assert round(pg.rect.width) == 595                          # kích thước trang (toạ độ bbox) không đổi


def test_sharp_scan_and_text_pages_are_left_alone(tmp_path):
    assert enhance_if_needed(_pdf(tmp_path, 2600, name="hi.pdf"), tmp_path / "e1") == tmp_path / "hi.pdf"   # ~315dpi
    t = _pdf(tmp_path, 800, with_text=True, name="t.pdf")
    assert enhance_if_needed(t, tmp_path / "e2") == t
