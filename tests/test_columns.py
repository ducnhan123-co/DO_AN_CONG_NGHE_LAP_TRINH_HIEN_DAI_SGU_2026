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
