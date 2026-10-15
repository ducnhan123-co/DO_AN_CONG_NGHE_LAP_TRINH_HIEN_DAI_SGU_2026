"""Kiểm tra dò cột + chèn ngắt cột (llm/src/columns.py) và tìm input.pdf lồng sâu."""
import numpy as np

from llm.src import columns as C
from llm.src.build_docx import _find_input_pdf


def test_detect_columns_three_bars():
    img = np.full((400, 600), 255, np.uint8)
    for x0 in (30, 220, 410):
        img[20:380, x0:x0 + 150] = 0
    assert len(C.detect_columns(img)) == 3


def test_insert_column_breaks_between_columns():
    lay = {"n_cols": 2, "page_pt": (595, 842),
           "cells": [(0, 0, C._norm("alpha beta gamma delta")), (0, 1, C._norm("omega sigma kappa lambda"))]}
    out = C.insert_column_breaks("alpha beta gamma delta\n\nomega sigma kappa lambda", lay)
    assert out.count('w:type="column"') == 1
    assert out.index("alpha") < out.index('w:type="column"') < out.index("omega")


def test_find_input_pdf_nested(tmp_path):
    (tmp_path / "input.pdf").write_bytes(b"%PDF")
    md = tmp_path / "mineru" / "doc" / "txt" / "doc.md"
    md.parent.mkdir(parents=True)
    assert _find_input_pdf(md) == tmp_path / "input.pdf"


def test_degenerate_latex_block_becomes_image(tmp_path):
    import json

    import fitz

    from llm.src.build_docx import swap_degenerate_math_for_images
    doc = fitz.open(); doc.new_page(width=300, height=400).insert_text((20, 50), "x"); doc.save(str(tmp_path / "input.pdf"))
    junk = "14. $" + r"\begin{array} { r l } & { " * 4 + "x " * 800 + "$"
    mdp = tmp_path / "mineru" / "input.md"; mdp.parent.mkdir()
    mdp.write_text("intro\n\n" + junk + "\n\nouttro\n", encoding="utf-8")
    (mdp.parent / "input_content_list.json").write_text(json.dumps(
        [{"type": "text", "text": junk, "page_idx": 0, "bbox": [0, 0, 1000, 500]}]), encoding="utf-8")
    out = swap_degenerate_math_for_images(mdp.read_text(encoding="utf-8"), mdp, tmp_path / "work.md")
    assert r"\begin{array}" not in out and "![](" in out and "intro" in out and "outtro" in out
    assert (tmp_path / "crops" / "degenerate_0.png").exists()


def test_scanfix_empty_block_on_scan_page_becomes_image(tmp_path):
    import json

    import fitz

    from llm.src import scanfix as F
    pdf = tmp_path / "input.pdf"
    doc = fitz.open(); pg = doc.new_page(width=300, height=400)
    pg.insert_image(fitz.Rect(0, 0, 300, 400), pixmap=fitz.Pixmap(fitz.csGRAY, 60, 80, b"\xf0" * 4800, False)); doc.save(str(pdf))
    md = "first block here\n\nsecond\n"
    items = [{"type": "text", "text": "first block here", "page_idx": 0, "bbox": [50, 50, 950, 400]},
             {"type": "text", "text": "", "page_idx": 0, "bbox": [50, 450, 950, 900]}]
    out = F.swap_unreadable_blocks(md, items, pdf, tmp_path)
    assert "![](" in out and (tmp_path / "crops" / "unreadable_0.png").exists()
    assert F.swap_unreadable_blocks(md, [dict(items[0], page_idx=0)], pdf, tmp_path) is not None
