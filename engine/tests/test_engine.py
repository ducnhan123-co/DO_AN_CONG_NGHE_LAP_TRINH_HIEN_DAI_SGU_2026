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
    assert _merge_words("tàn nhẫn, bạc", "tàn newborn, bạc") == "tàn nhẫn, bạc"            # đổi hẳn chữ -> giữ gốc


def test_ocr_fusion_votes():
    from pdf2docx_engine.recognition.diacritic_fusion import fuse_markdown
    md = "## CHUYÊN ĐÊ 3. ĐẶC TRUNG VĂN HỌC\nĐối tượng phần ánh của văn học, tàn newborn, bạc bẽo $x^2$ ở đây"
    good = "CHUYÊN ĐỀ 3. ĐẶC TRƯNG VĂN HỌC Đối tượng phản ánh của văn học, tàn nhẫn, bạc bẽo ở đây"
    ref = [(w, 97.0) for w in good.replace(",", "").replace(".", "").split()]
    out, rep = fuse_markdown(md, {"tesseract": ref, "vision": ref})
    assert out == ("## CHUYÊN ĐỀ 3. ĐẶC TRƯNG VĂN HỌC\n"
                   "Đối tượng phản ánh của văn học, tàn nhẫn, bạc bẽo $x^2$ ở đây")
    one, _ = fuse_markdown(md, {"tesseract": ref})            # 1 bộ OCR: chỉ sửa dấu, không thay hẳn chữ
    assert "phản ánh" in one and "newborn" in one
