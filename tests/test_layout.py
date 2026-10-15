import zipfile

import pytest

from llm.src import layout as L


def _items():
    mk = lambda pg, x0, x1, y0, y1, text: {"type": "text", "page_idx": pg, "bbox": [x0, y0, x1, y1], "text": text}
    return [mk(0, 30, 300, 20, 60, "Cot mot dong dau tien"), mk(0, 30, 300, 70, 120, "Cot mot dong thu hai"),
            mk(0, 30, 300, 130, 200, "Cot mot dong thu ba"), mk(0, 350, 650, 20, 60, "Cot hai dong dau tien"),
            mk(0, 350, 650, 70, 120, "Cot hai dong thu hai"), mk(0, 350, 650, 130, 200, "Cot hai dong thu ba")]


def test_two_columns_detected_and_one_column_not():
    two = L._columns(_items())
    assert len(two) == 2 and two[0][0] == 30 and two[1][0] == 350
    one = [dict(b, bbox=[60 + i, b["bbox"][1], 900, b["bbox"][3]]) for i, b in enumerate(_items())]
    assert len(L._columns(one)) < 2                                    # khối rộng >=60% trang không tính là cột


def test_markers_break_column_and_page_in_reading_order():
    items = _items() + [{"type": "text", "page_idx": 1, "bbox": [30, 20, 300, 60], "text": "Trang hai dong dau"}]
    lay = {"pages": {0: {"w": 595, "h": 842, "ml": 20, "mr": 20, "mt": 20, "mb": 20, "cols": [[30, 300], [350, 650]]},
                     1: {"w": 595, "h": 842, "ml": 20, "mr": 20, "mt": 20, "mb": 20, "cols": [[30, 300]]}}}
    md = "\n\n".join(i["text"] for i in items)
    out = L.insert_layout_markers(md, items, lay)
    assert out.count('w:type="column"') == 1 and out.count("<w:sectPr>") == 1 and '<w:cols w:num="2"' in out
    assert out.index("Cot mot dong thu ba") < out.index('w:type="column"') < out.index("Cot hai dong dau tien")
    assert out.index("Cot hai dong thu ba") < out.index("<w:sectPr>") < out.index("Trang hai")
    assert 'w:type="column"' not in L.insert_layout_markers(md, items, lay, column_breaks=False)


def test_image_widths_added_once():
    md = "a ![](/x/y/abc.jpg) b ![](/x/other.png)"
    out = L.apply_image_widths(md, {"abc.jpg": 120.5})
    assert "![](/x/y/abc.jpg){width=120.5pt}" in out and out.endswith("![](/x/other.png)")
    assert L.apply_image_widths(out, {"abc.jpg": 120.5}) == out


def test_apply_layout_sets_page_size_and_font(tmp_path):
    import docx
    d = docx.Document()
    d.add_paragraph("x")
    p = tmp_path / "a.docx"
    d.save(str(p))
    lay = {"pages": {"0": {"w": 842.0, "h": 595.0, "ml": 22, "mr": 24, "mt": 18, "mb": 29, "cols": [[26, 303], [342, 653]]}},
           "font_pt": 8.0, "multi_col": True, "img_width_pt": {}}
    L.apply_layout(p, lay)
    s = docx.Document(str(p)).sections[-1]
    assert round(s.page_width.pt) == 842 and round(s.page_height.pt) == 595 and round(s.left_margin.pt) == 22
    assert 'w:num="2"' in zipfile.ZipFile(p).read("word/document.xml").decode()
    assert docx.Document(str(p)).styles["Normal"].font.size.pt == 8.0
