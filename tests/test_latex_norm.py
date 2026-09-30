"""Test latex_norm. Chạy: python -m tests.test_latex_norm"""
from llm.chunking import build_chunks, math_balanced
from llm.latex_norm import (find_latex_problems, is_valid_latex, normalize_latex,
                            normalize_math_in_text, strip_math_delims)
from llm.structured import normalize_blocks
from llm.validate import validate_chunks

SAMPLES = [
    "$$\n\\dfrac {a}{b} + x ^ { 2 }\n$$",
    "a × b ≤ c ∧ d ≠ 0",
    "\\sum _{i=1} ^ n α_i²",
    "x \\text { nếu   } y \\geq 0",
    "\\begin{cases}\n a & x>0 \\\\\n b & x\\le 0\n\\end{cases}",
    "\\displaystyle \\int_0^1 x^2\\,dx",
    "√ {x} + ℝ",
    "\\{ x \\in A \\}",
]


def test_strip_delims():
    assert strip_math_delims("$$ x^2 $$") == "x^2"
    assert strip_math_delims("\\[ x^2 \\]") == "x^2"
    assert strip_math_delims("\\( x \\)") == "x"
    assert strip_math_delims("$x$") == "x"
    assert strip_math_delims("x^2") == "x^2"


def test_normalize_basic():
    assert normalize_latex("$$\n\\dfrac {a}{b}\n$$") == "\\frac{a}{b}"
    assert normalize_latex("x ^ { 2 } + y _ 1") == "x^{2}+y_1".replace("+", " + ")
    assert normalize_latex("a × b ≤ c") == "a \\times b \\leq c"
    assert normalize_latex("\\sqrt {x}") == "\\sqrt{x}"
    assert normalize_latex("√x") == "\\sqrt x"
    assert normalize_latex("x²") == "x^{2}"
    assert normalize_latex("\\displaystyle \\sum_{i} i") == "\\sum_{i} i"
    assert normalize_latex("a\n  +\n b") == "a + b"
    assert normalize_latex("\\{ x \\}") == "\\{ x \\}"   # không nuốt space của \{ \}
    assert normalize_latex("") == "" and normalize_latex(None) == ""


def test_text_group_preserved():
    # khoảng trắng trong \text{...} có nghĩa -> giữ nguyên
    assert normalize_latex("x \\text{ nếu } y") == "x \\text{ nếu } y"
    assert normalize_latex("x \\text { nếu   } y") == "x \\text{ nếu } y"
    # Unicode trong \text KHÔNG bị đổi thành lệnh LaTeX
    assert normalize_latex("\\text{a × b} × c") == "\\text{a × b} \\times c"


def test_idempotent():
    for s in SAMPLES:
        once = normalize_latex(s)
        assert normalize_latex(once) == once, (s, once)


def test_in_text():
    assert normalize_math_in_text("Ta có \\[ a  +  b \\] đúng") == "Ta có $$a + b$$ đúng"
    assert normalize_math_in_text("với \\( x ^ 2 \\) nhỏ") == "với $x^2$ nhỏ"
    assert normalize_math_in_text("với \\( x \\)", canonical_delims=False) == "với \\(x\\)"
    assert normalize_math_in_text("Cho $ a×b $ và $$ x ≤ y $$.") == "Cho $ a×b $ và $$x \\leq y$$."
    # $a×b$ (không space sát delimiter) được chuẩn hoá; "$ a×b $" theo luật Pandoc không phải math
    assert normalize_math_in_text("Cho $a×b$.") == "Cho $a\\times b$."
    # tiền tệ / chữ Việt không bị đụng
    money = "Giá $5 và $10, tổng ≤ 15 đồng."
    assert normalize_math_in_text(money) == money
    assert normalize_math_in_text("") == ""
    assert normalize_math_in_text("không có công thức") == "không có công thức"
    # kết quả vẫn cân bằng delimiter
    assert math_balanced(normalize_math_in_text("a \\[ x \\] b \\( y \\) c $z$ d $$w$$"))


def test_find_problems():
    assert is_valid_latex("\\frac{a}{b}")
    assert is_valid_latex("\\left( \\frac{a}{b} \\right)")
    assert is_valid_latex("\\begin{cases} a \\\\ b \\end{cases}")
    assert is_valid_latex("\\{ x \\}")
    assert any("thiếu" in p for p in find_latex_problems("\\frac{a}{b"))
    assert any("thừa" in p for p in find_latex_problems("a}"))
    assert any("\\left" in p for p in find_latex_problems("\\left( x"))
    assert any("chưa đóng" in p for p in find_latex_problems("\\begin{cases} a"))
    assert any("không khớp" in p for p in find_latex_problems("\\begin{a} x \\end{b}"))
    assert find_latex_problems("") == ["công thức rỗng"]


def test_integration_structured():
    raw = [
        {"type": "text", "text": "Chương 1", "text_level": 1, "page_idx": 0},
        {"type": "equation", "text": "$$\n\\dfrac {a}{b} ≤ x ^ { 2 }\n$$", "page_idx": 0},
        {"type": "text", "text": "Khi \\( x ≥ 0 \\) thì đúng.", "page_idx": 0},
        {"type": "list", "list_items": ["một \\[ y×z \\]", "hai"], "page_idx": 0},
        {"type": "table", "table_body": "<table><tr><td>$5 ≤ 6$</td></tr></table>", "page_idx": 0},
    ]
    blocks = normalize_blocks(raw, "d.pdf", "dddd")
    f = next(b for b in blocks if b["content_type"] == "formula")
    assert f["formula_latex"] == "\\frac{a}{b} \\leq x^{2}"
    assert f["text"] == "$$\n\\frac{a}{b} \\leq x^{2}\n$$"
    t = next(b for b in blocks if b["content_type"] == "text")
    assert t["text"] == "Khi $x \\geq 0$ thì đúng."
    li = next(b for b in blocks if b["content_type"] == "list")
    assert "$$y\\times z$$" in li["text"]
    tb = next(b for b in blocks if b["content_type"] == "table")
    assert "≤" in tb["text"]                     # bảng giữ nguyên, không chuẩn hoá
    chunks = build_chunks(blocks, 1800, 250)
    assert validate_chunks(chunks, "d.pdf", "dddd")["ok"]


if __name__ == "__main__":
    test_strip_delims(); test_normalize_basic(); test_text_group_preserved()
    test_idempotent(); test_in_text(); test_find_problems(); test_integration_structured()
    print("ALL PASSED")


def test_old_tex_fonts_and_displaylimits():
    # Pandoc/texmath không hiểu {\bf x}, \mathrm{\bf S}, \displaylimits -> DOCX ra chữ thô
    assert normalize_latex(r"\mathrm { \bf S }") == r"\mathrm{\mathbf{S}}"
    assert normalize_latex(r"\dot{\bf Y}") == r"\dot{\mathbf{Y}}"
    assert normalize_latex(r"\int \displaylimits _ { S } f") == r"\int \limits_{S} f"
    assert normalize_latex(r"\{\bf x\}") == r"\{\bf x\}"   # \{ escape: không đụng


def test_fix_vni():
    from llm.latex_norm import fix_vni
    assert fix_vni("Neáu khoâng da ãm leân, ta goïi laø giaù cuûa ñöôøng") == \
        "Nếu không dẫm lên, ta gọi là giá của đường"
    ok = "liên riêng giá toàn hoá xoáy tuân ân trò \\frac{1}{S}"
    assert fix_vni(ok) == ok                                  # Unicode chuẩn giữ nguyên
