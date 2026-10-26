from pdf2docx_engine.docx.build_docx import fix_legacy_tex_bf
from pdf2docx_engine.math.math_repair import merge_fragmented_math, repair_markdown


def test_merge_fragmented_math():
    md, n = merge_fragmented_math("Khai triển x$^{7}$ và (1+x)$^{11}$")
    assert "$x^{7}$" in md and "$(1+x)^{11}$" in md and n >= 2


def test_fix_legacy_bf():
    assert "\\mathbf{X}" in fix_legacy_tex_bf("${\\bf X}$")


def test_repair_markdown_reports():
    _, rep = repair_markdown("Bài 1. x$^{2}$\n\nBài 2. y\n")
    assert rep["merged_math_fragments"] >= 1
