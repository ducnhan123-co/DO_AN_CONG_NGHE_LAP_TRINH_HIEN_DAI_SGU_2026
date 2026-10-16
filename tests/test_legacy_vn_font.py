"""PDF font tiếng Việt cũ (TCVN3): nhận ra lớp chữ rác và đổi lại Unicode."""
from llm.src.run_mineru import fix_vi_ocr, is_legacy_vn_garbled, tcvn3_to_unicode


def test_detect():
    assert is_legacy_vn_garbled("C¬ häc Ch−¬ng 1: §éng häc chÊt ®iÓm ph−¬ng tr×nh chuyÓn ®éng " * 3)
    assert not is_legacy_vn_garbled("Cơ học Chương 1: Động học chất điểm, phương trình chuyển động " * 3)
    assert not is_legacy_vn_garbled("The LSTM cell uses gates and a 25° ± 2° range, µ = 3 m². " * 3)


def test_convert():
    assert tcvn3_to_unicode("C¬ häc") == "Cơ học"
    assert tcvn3_to_unicode("§éng häc chÊt ®iÓm") == "Động học chất điểm"
    assert tcvn3_to_unicode("Ph−¬ng tr×nh chuyÓn ®éng cña mét chÊt ®iÓm, ®−îc b»ng") == \
        "Phương trình chuyển động của một chất điểm, được bằng"
    assert tcvn3_to_unicode("Khoa VËt LÝ, tr−êng §H Khoa Häc, §H Th¸i Nguyªn") == \
        "Khoa Vật Lí, trường ĐH Khoa Học, ĐH Thái Nguyên"


def test_u_horn_tones():
    assert tcvn3_to_unicode("Tõ ®ã tøc lµ khö, tù, gi÷a") == "Từ đó tức là khử, tự, giữa"


def test_a_tilde_read_as_C():
    assert tcvn3_to_unicode("ta ®C khö, quCng ®−êng, hCm") == "ta đã khử, quãng đường, hãm"
    assert tcvn3_to_unicode("tương ứng ®. cho vµo (7). ®. lµ") == "tương ứng đã cho vào (7). đã là"


def test_math_untouched():
    assert fix_vi_ocr("tÝnh $x_{\\alpha}+\\mu$ víi", legacy=True) == "tính $x_{\\alpha}+\\mu$ với"
