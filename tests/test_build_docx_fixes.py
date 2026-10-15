import json
import shutil
import subprocess
import zipfile

import pytest

from llm.src.build_docx import (fix_font_declarations, fix_symbol_pua, looks_like_ocr_table,
                                md_to_docx, prepare_work_md)


def test_font_declarations_become_mathbf_groups():
    assert fix_font_declarations(r"\mathrm { ~ \bf ~ B . ~ } x") == r"\mathrm { ~ \mathbf{ ~ B . ~ }} x"
    assert fix_font_declarations(r"{ \sf R } = 1") == r"{ \mathsf{ R }} = 1"
    assert fix_font_declarations(r"\mathrm \mathbf{~ R} ^ 2") == r"\mathbf{~ R} ^ 2"
    assert fix_font_declarations(r"\intop \cfrac{1}{2} \tiny x") == r"\int \frac{1}{2}  x"
    assert fix_font_declarations(r"\frac \mathbf{x} { a }") == r"\frac{\mathbf{x}}{ a }"
    assert fix_font_declarations(r"\mathbf{b} \bfseries") == r"\mathbf{b} \bfseries"  # không đụng \bfseries


def test_symbol_font_private_use_chars_mapped():
    assert fix_symbol_pua("x  6  ") == "x = 6 ∞ α("


def test_ocr_table_detected_but_normal_fraction_not():
    assert looks_like_ocr_table(r"\begin{array}{c} \frac { x \quad - 3 \quad - 2 \quad 3 \quad 5 } { y' } \end{array}")
    assert not looks_like_ocr_table(r"\begin{array}{c} \frac{1}{2} \end{array}")


@pytest.mark.skipif(not shutil.which("pandoc"), reason="cần pandoc")
def test_short_doc_has_no_toc_and_unparsable_formula_becomes_image(tmp_path):
    from PIL import Image
    md_dir = tmp_path / "m"
    (md_dir / "images").mkdir(parents=True)
    Image.new("RGB", (40, 20), "white").save(md_dir / "images" / "f.png")
    bad = r"\begin{array}{c} \frac { x \quad - 3 \quad - 2 \quad 3 \quad 5 } { y } \end{array}"
    (md_dir / "d_content_list.json").write_text(json.dumps(
        [{"type": "equation", "text": f"$$\n{bad}\n$$", "img_path": "images/f.png", "page_idx": 0}]), encoding="utf-8")
    md = md_dir / "d.md"
    text = f"Câu 1: $x \\uf03d 1$\n\n$$\n{bad}\n$$\n\nHết\n"
    md.write_text(text, encoding="utf-8")
    work = tmp_path / "work.md"
    prepare_work_md(text, md, work)
    out = md_to_docx(work, tmp_path / "o.docx", md_dir, number_pages=False)
    z = zipfile.ZipFile(out)
    xml = z.read("word/document.xml").decode("utf8")
    assert "Table of Contents" not in xml and "TOC" not in xml
    assert any(n.startswith("word/media/") for n in z.namelist())   # công thức dạng bảng -> ảnh gốc
    assert "frac" not in xml and "\\begin" not in xml


@pytest.mark.skipif(not shutil.which("pandoc"), reason="cần pandoc")
def test_docx_path_never_exists_half_built(tmp_path, monkeypatch):
    """Backend coi docx_path tồn tại = xong -> trong lúc dựng chỉ được có file tạm."""
    import llm.src.build_docx as bd
    seen = []
    real = bd.set_font
    monkeypatch.setattr(bd, "set_font", lambda p, *a, **k: (seen.append((p.name, (tmp_path / "o.docx").exists())), real(p, *a, **k))[1])
    work = tmp_path / "w.md"
    work.write_text("Xin chào $x^2$\n", encoding="utf-8")
    out = bd.md_to_docx(work, tmp_path / "o.docx", tmp_path, number_pages=False)
    assert seen == [("o.building.docx", False)] and out.exists()
    assert not (tmp_path / "o.building.docx").exists()
