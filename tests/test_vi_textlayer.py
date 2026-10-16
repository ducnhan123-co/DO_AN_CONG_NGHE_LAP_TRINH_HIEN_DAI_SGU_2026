"""Sửa chữ Việt rụng dấu bằng lớp chữ PDF; chỉ sửa khi từ đúng chứa từ hỏng như dãy con."""
from llm.src.vi_textlayer import repair_text, strip_footers


def test_repair_dropped_diacritics():
    cands = "ω T 2π và lưu ý thay chu kỳ phải đổi đúng đối với là giây".split()
    bad = "và lu $\\acute { \\mathbf { y } }$ thay chu k ph đi đng đi với là giây"
    assert repair_text(bad, cands) == "và lưu ý thay chu kỳ phải đổi đúng đối với là giây"


def test_correct_text_untouched():
    cands = "Vận tốc góc của trái đất".split()
    t = "Vận tốc góc của trái đất"
    assert repair_text(t, cands) == t


def test_real_formula_untouched_and_no_invention():
    cands = "ta có x bằng".split()
    t = "ta có $x = a _ { 1 } \\cos \\omega t$ bằng"
    assert repair_text(t, cands) == t
    assert repair_text("xin chào", ["abc"]) == "xin chào"   # không có ứng viên chứa -> giữ nguyên


def test_strip_footers_joins_split_sentence():
    f = "Khoa Vật Lí, trường ĐH Khoa Học"
    md = "\n\n".join(["đầu", "không phụ thuộc", f + " vào chiều chuyển động.", "mục khác"] + [f] * 25)
    out = strip_footers(md)
    assert f not in out and "không phụ thuộc vào chiều chuyển động." in out
