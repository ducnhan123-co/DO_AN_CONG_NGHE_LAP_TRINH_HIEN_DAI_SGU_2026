# Chép nguyên từ đồ án: Doan/src_update_fixed_new/src/latex_norm.py (chuẩn hoá LaTeX của MinerU).
"""Chuẩn hoá LaTeX do MinerU/OCR sinh ra, trước khi đưa vào structured/chunking/RAG.

Vì sao cần: cùng một công thức nhưng OCR có thể trả về nhiều dạng khác nhau
(`\\dfrac {a}{b}`, `x ^ { 2 }`, `×`, `≤`, `\\[...\\]`, xuống dòng lung tung...). Nếu không
chuẩn hoá, embedding E5 coi chúng là các chuỗi khác nhau và retrieval kém ổn định.

Nguyên tắc: CHỈ đổi những thứ an toàn về ngữ nghĩa (khoảng trắng trong math mode, ký tự
Unicode -> lệnh LaTeX, alias trình bày). Không "sửa" công thức sai, chỉ báo lỗi qua
`find_latex_problems`. Nội dung trong \\text{...} được giữ nguyên (khoảng trắng ở đó có nghĩa).
Hàm chuẩn hoá là idempotent: norm(norm(x)) == norm(x).

API chính:
  strip_math_delims(s)                    bỏ $$..$$ / \\[..\\] / \\(..\\) / $..$ bao ngoài
  normalize_latex(s)                      chuẩn hoá 1 công thức (kết quả không có delimiter)
  normalize_math_in_text(text)            chuẩn hoá mọi công thức nhúng trong đoạn văn
  find_latex_problems(s) / is_valid_latex kiểm tra ngoặc {} / \\left-\\right / \\begin-\\end
"""
import re
from typing import List, Tuple

__all__ = ["strip_math_delims", "normalize_latex", "normalize_math_in_text",
           "find_latex_problems", "is_valid_latex"]

# --------------------------------------------------------------------------- delimiters
_DELIMS = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$"))


def strip_math_delims(s: str) -> str:
    s = (s or "").strip()
    for a, b in _DELIMS:
        if len(s) >= len(a) + len(b) and s.startswith(a) and s.endswith(b):
            return s[len(a):len(s) - len(b)].strip()
    return s


# --------------------------------------------------------------------------- unicode -> LaTeX
# Lệnh có khoảng trắng đuôi để không dính vào ký tự kế tiếp (\times x, không phải \timesx);
# khoảng trắng thừa được dọn ở bước sau.
_SYMBOLS = {
    "×": "\\times ", "÷": "\\div ", "·": "\\cdot ", "⋅": "\\cdot ", "∘": "\\circ ",
    "±": "\\pm ", "∓": "\\mp ", "∗": "*", "−": "-", "–": "-", "—": "-",
    "≤": "\\leq ", "≥": "\\geq ", "≠": "\\neq ", "≈": "\\approx ", "≡": "\\equiv ",
    "∼": "\\sim ", "∝": "\\propto ", "≪": "\\ll ", "≫": "\\gg ",
    "∞": "\\infty ", "∂": "\\partial ", "∇": "\\nabla ", "ℓ": "\\ell ",
    "∈": "\\in ", "∉": "\\notin ", "⊂": "\\subset ", "⊆": "\\subseteq ",
    "⊃": "\\supset ", "⊇": "\\supseteq ", "∪": "\\cup ", "∩": "\\cap ",
    "∖": "\\setminus ", "∅": "\\emptyset ", "∀": "\\forall ", "∃": "\\exists ",
    "∧": "\\land ", "∨": "\\lor ", "¬": "\\neg ", "⊕": "\\oplus ", "⊗": "\\otimes ",
    "⊥": "\\perp ", "∥": "\\parallel ", "∠": "\\angle ", "△": "\\triangle ",
    "∣": "\\mid ", "⟨": "\\langle ", "⟩": "\\rangle ",
    "→": "\\to ", "←": "\\leftarrow ", "↦": "\\mapsto ",
    "⇒": "\\Rightarrow ", "⟹": "\\Rightarrow ", "⇔": "\\Leftrightarrow ",
    "⟺": "\\Leftrightarrow ", "…": "\\ldots ", "⋯": "\\cdots ", "⋮": "\\vdots ",
    "∑": "\\sum ", "∏": "\\prod ", "∫": "\\int ", "√": "\\sqrt ",
    "°": "^{\\circ}", "′": "'", "″": "''",
    "ℝ": "\\mathbb{R}", "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}",
    "ℚ": "\\mathbb{Q}", "ℂ": "\\mathbb{C}",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",          # các loại space lạ
    "\u200b": "", "\u200c": "", "\u200d": "", "\ufeff": "",  # zero-width
}
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho",
    "σ": "sigma", "τ": "tau", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi",
    "Π": "Pi", "Σ": "Sigma", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
}
_SUP = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
_SUB = dict(zip("₀₁₂₃₄₅₆₇₈₉", "0123456789"))

_TRANSLATE = {ord(k): v for k, v in _SYMBOLS.items()}
_TRANSLATE.update({ord(k): f"\\{v} " for k, v in _GREEK.items()})
_TRANSLATE.update({ord(k): f"^{{{v}}}" for k, v in _SUP.items()})
_TRANSLATE.update({ord(k): f"_{{{v}}}" for k, v in _SUB.items()})

# --------------------------------------------------------------------------- regex dọn dẹp
_ALIASES = ((re.compile(r"\\[dt]frac(?![A-Za-z])"), r"\\frac"),
            (re.compile(r"\\[dt]binom(?![A-Za-z])"), r"\\binom"),
            (re.compile(r"\\(?:displaystyle|textstyle)(?![A-Za-z])"), ""))
_WS = re.compile(r"\s+")
_CMD_SPACE = re.compile(r"(\\[A-Za-z]+)\s+(?=[{_^])")   # \frac {a} -> \frac{a}; \sum _i -> \sum_i
_SCRIPT_SPACE = re.compile(r"\s*([_^])\s*")              # x ^ { 2 } -> x^{ 2 }
_OPEN_SPACE = re.compile(r"(?<!\\)\{\s+")                # { x -> {x   (không đụng \{ )
_CLOSE_SPACE = re.compile(r"(?<!\\)\s+\}")               # x } -> x}   (không đụng "\ }" )

# Các lệnh mà khoảng trắng bên trong có nghĩa -> giữ nguyên nội dung
_TEXT_CMD = re.compile(r"\\(?:text|textrm|textbf|textit|textsf|texttt|mbox|hbox)\s*\{")


def _match_brace(s: str, open_idx: int) -> int:
    """Vị trí dấu } khớp với { tại open_idx (bỏ qua ký tự bị escape); -1 nếu không khớp."""
    depth, i = 0, open_idx
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_protected(s: str) -> List[Tuple[bool, str]]:
    """Tách chuỗi thành các đoạn (protected?, nội dung); protected = \\text{...} và tương tự."""
    parts: List[Tuple[bool, str]] = []
    start = pos = 0
    while True:
        m = _TEXT_CMD.search(s, pos)
        if not m:
            break
        end = _match_brace(s, m.end() - 1)
        if end == -1:
            break
        parts.append((False, s[start:m.start()]))
        parts.append((True, s[m.start():end + 1]))
        start = pos = end + 1
    parts.append((False, s[start:]))
    return parts


def _norm_segment(seg: str) -> str:
    seg = seg.translate(_TRANSLATE)
    for pat, rep in _ALIASES:
        seg = pat.sub(rep, seg)
    seg = _WS.sub(" ", seg)
    seg = _CMD_SPACE.sub(r"\1", seg)
    seg = _SCRIPT_SPACE.sub(r"\1", seg)
    seg = _OPEN_SPACE.sub("{", seg)
    seg = _CLOSE_SPACE.sub("}", seg)
    return _WS.sub(" ", seg)


def _norm_protected(seg: str) -> str:
    seg = re.sub(r"^(\\[A-Za-z]+)\s+\{", r"\1{", seg)   # \text {..} -> \text{..}
    return _WS.sub(" ", seg)                             # xuống dòng/nhiều space -> 1 space


def _normalize_body(body: str) -> str:
    out = "".join(_norm_protected(t) if prot else _norm_segment(t)
                  for prot, t in _split_protected(body))
    return out.strip()


def normalize_latex(s: str) -> str:
    """Chuẩn hoá một công thức. Nhận cả chuỗi có/không có delimiter; trả về KHÔNG có delimiter."""
    if not s:
        return ""
    return _normalize_body(strip_math_delims(s))


# --------------------------------------------------------------------------- công thức trong văn bản
# Thứ tự alternation quan trọng: $$..$$ thử trước $..$.
# $..$ theo luật của Pandoc: sau $ mở không phải space, trước $ đóng không phải space,
# và $ đóng không đứng trước chữ số -> "giá $5 và $10" không bị nhận nhầm là công thức.
_MATH_SPAN = re.compile(
    r"\$\$(?P<dd>.+?)\$\$"
    r"|\\\[(?P<br>.+?)\\\]"
    r"|\\\((?P<pa>.+?)\\\)"
    r"|(?<![\\$])\$(?![\s$])(?P<sd>[^$\n]+?)(?<![\s\\])\$(?!\d)",
    re.S,
)


def normalize_math_in_text(text: str, canonical_delims: bool = True) -> str:
    """Chuẩn hoá mọi công thức nhúng trong đoạn văn; phần chữ bên ngoài giữ nguyên.

    canonical_delims=True: \\[..\\] -> $$..$$ và \\(..\\) -> $..$ (một kiểu delimiter duy nhất
    cho embedding). Công thức chuẩn hoá ra rỗng thì giữ nguyên bản gốc.
    """
    if not text or not any(c in text for c in "$\\"):
        return text or ""

    def repl(m: "re.Match") -> str:
        kind = m.lastgroup
        norm = _normalize_body(m.group(kind))
        if not norm:
            return m.group(0)
        if kind == "dd":
            return f"$${norm}$$"
        if kind == "sd":
            return f"${norm}$"
        if canonical_delims:
            return f"$${norm}$$" if kind == "br" else f"${norm}$"
        return f"\\[{norm}\\]" if kind == "br" else f"\\({norm}\\)"

    return _MATH_SPAN.sub(repl, text)


# --------------------------------------------------------------------------- kiểm tra
_LEFT = re.compile(r"\\left(?![A-Za-z])")
_RIGHT = re.compile(r"\\right(?![A-Za-z])")
_ENV = re.compile(r"\\(begin|end)\s*\{([^{}]*)\}")


def find_latex_problems(latex: str) -> List[str]:
    """Trả về danh sách lỗi cấu trúc (rỗng = ổn). Không sửa, chỉ báo."""
    s = strip_math_delims(latex)
    problems: List[str] = []
    if not s:
        return ["công thức rỗng"]

    depth, i = 0, 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                problems.append("thừa dấu }")
                depth = 0
        i += 1
    if depth > 0:
        problems.append(f"thiếu {depth} dấu }}")

    nl, nr = len(_LEFT.findall(s)), len(_RIGHT.findall(s))
    if nl != nr:
        problems.append(f"\\left/\\right lệch ({nl} vs {nr})")

    stack: List[str] = []
    for m in _ENV.finditer(s):
        kind, name = m.group(1), m.group(2).strip()
        if kind == "begin":
            stack.append(name)
        elif not stack or stack[-1] != name:
            problems.append(f"\\end{{{name}}} không khớp \\begin")
        else:
            stack.pop()
    for name in stack:
        problems.append(f"\\begin{{{name}}} chưa đóng")
    return problems


def is_valid_latex(latex: str) -> bool:
    return not find_latex_problems(latex)
