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


def test_vi_correct_merge_keeps_punctuation_and_prefix():
    from pdf2docx_engine.recognition.vi_correct import _PREFIX, _merge_words
    assert _merge_words("Đối tượng phần ánh, “Sắc”.", "Đối tượng phản ánh. Sắc.") == "Đối tượng phản ánh, “Sắc”."
    assert _merge_words("thống. Nhở biện", "thống.Nhờ biện") == "thống. Nhở biện"   # gộp chữ -> giữ gốc
    assert _merge_words("(THEO CHƯỜNG", "(TheO CHƯƠNG") == "(THEO CHƯƠNG"
    assert _PREFIX.match("## CHUYÊN ĐÊ 3").groups() == ("## ", "CHUYÊN ĐÊ 3")
