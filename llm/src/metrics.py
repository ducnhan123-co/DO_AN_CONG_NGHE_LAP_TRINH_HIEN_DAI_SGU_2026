"""Độ đo đầu ra chuyển đổi PDF -> Word: CER, WER và PER.

Định nghĩa dùng trong module này:
- CER (Character Error Rate) = (S + D + I) / N, tính trên ký tự.
- WER (Word Error Rate)      = (S + D + I) / N, tính trên đơn vị từ.
- PER (Page Error Rate)      = số trang có ít nhất một lỗi / tổng số trang.
  PER = 0 nghĩa là mọi trang khớp ground truth tuyệt đối; đây là phép đo
  nghiêm, chỉ cần một ký tự sai là trang đó bị tính lỗi. Vì vậy kết quả
  còn có page_exact_match_rate = 1 - PER và CER theo từng trang để đọc
  mức độ lỗi, không chỉ đếm trang.

Quy ước chuẩn hóa trước khi so sánh (bắt buộc, nếu không CER bị thổi phồng
bởi khác biệt mã hóa):
- Unicode NFC (quan trọng với tiếng Việt: dấu tổ hợp và dấu dựng sẵn).
- Bỏ ký tự vô hình (ZWSP, ZWJ, BOM, soft hyphen, control direction).
- Gộp mọi khoảng trắng liên tiếp thành một dấu cách và strip hai đầu.
- Tùy chọn bỏ vùng công thức ($...$, $$...$$, \\(...\\), \\[...\\]) để CER
  văn bản không bị trộn với lỗi công thức.
- Tùy chọn lowercase.

WER ở đây tách từ theo khoảng trắng. Với tiếng Việt, cách tách này thực chất
đo ở mức âm tiết, không phải mức từ ngữ nghĩa; khi báo cáo phải nói rõ.

Module không tự tạo ground truth. Không có bản tham chiếu độc lập thì không
thể tính CER/WER/PER có ý nghĩa; chỉ có thể đếm số đối tượng đầu ra.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from itertools import zip_longest
from pathlib import Path

_INVISIBLE_RE = re.compile(
    "[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_WHITESPACE_RE = re.compile(r"\s+")
_MATH_RE = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\$)\$(?!\$)[^$\n]*?\$(?!\$)",
    re.S,
)
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".text"}
_SUPPORTED_SUFFIXES = _TEXT_SUFFIXES | {".docx"}


def normalize_text(
    text: str,
    *,
    strip_math: bool = False,
    lower: bool = False,
    collapse_whitespace: bool = True,
) -> str:
    """Chuẩn hóa một chuỗi trước khi so sánh CER/WER."""
    if strip_math:
        text = _MATH_RE.sub(" ", text)
    text = _INVISIBLE_RE.sub("", text)
    text = unicodedata.normalize("NFC", text)
    if lower:
        text = text.lower()
    if collapse_whitespace:
        text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


@dataclass(frozen=True)
class EditCounts:
    """Số lỗi thay thế/xóa/chèn và độ dài bản tham chiếu."""

    substitutions: int
    deletions: int
    insertions: int
    ref_len: int
    exact: bool = True

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def rate(self) -> float:
        if self.ref_len == 0:
            return 0.0 if self.errors == 0 else 1.0
        return self.errors / self.ref_len


@dataclass(frozen=True)
class PageMetrics:
    name: str
    cer: float
    wer: float
    char_counts: EditCounts
    word_counts: EditCounts

    @property
    def has_error(self) -> bool:
        return self.char_counts.errors > 0


@dataclass(frozen=True)
class CorpusMetrics:
    cer: float
    wer: float
    per: float
    page_exact_match_rate: float
    n_pages: int
    n_pages_with_error: int
    char_counts: EditCounts
    word_counts: EditCounts
    pages: list[PageMetrics]
    exact: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _tokens(text: str, unit: str) -> list[str]:
    if unit == "char":
        return list(text)
    return text.split()


def _exact_counts(ref_tokens: list[str], hyp_tokens: list[str]) -> EditCounts:
    n, m = len(ref_tokens), len(hyp_tokens)
    if n == 0:
        return EditCounts(0, 0, m, 0)
    if m == 0:
        return EditCounts(0, n, 0, n)

    width = m + 1
    directions = bytearray((n + 1) * width)
    for j in range(1, m + 1):
        directions[j] = 2  # chèn: đi từ trái sang
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [0] * width
        cur[0] = i
        base = i * width
        directions[base] = 1  # xóa: đi từ trên xuống
        ref_token = ref_tokens[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ref_token == hyp_tokens[j - 1] else 1
            diag = prev[j - 1] + cost
            up = prev[j] + 1
            left = cur[j - 1] + 1
            best, direction = diag, 0
            if up < best:
                best, direction = up, 1
            if left < best:
                best, direction = left, 2
            cur[j] = best
            directions[base + j] = direction
        prev = cur

    substitutions = deletions = insertions = 0
    i, j = n, m
    while i > 0 or j > 0:
        direction = directions[i * width + j]
        if i > 0 and j > 0 and direction == 0:
            if ref_tokens[i - 1] != hyp_tokens[j - 1]:
                substitutions += 1
            i -= 1
            j -= 1
        elif i > 0 and (j == 0 or direction == 1):
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return EditCounts(substitutions, deletions, insertions, n)


def _line_counts(ref_lines: list[str], hyp_lines: list[str], unit: str) -> EditCounts:
    """Căn theo dòng khi chuỗi quá lớn cho bảng DP đầy đủ.

    Đây là xấp xỉ có kiểm soát: các dòng khớp/khác được căn cứ trên nội dung,
    phần dư của một khối replace được tính là xóa/chèn. Kết quả trả về có
    exact=False để nơi gọi không nhầm với Levenshtein tối ưu toàn chuỗi.
    """
    def tokenize(line: str) -> list[str]:
        return list(line) if unit == "char" else line.split()

    def length(line: str) -> int:
        return len(line) if unit == "char" else len(line.split())

    matcher = SequenceMatcher(None, ref_lines, hyp_lines, autojunk=False)
    total = EditCounts(0, 0, 0, 0, exact=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for ref_line, hyp_line in zip(ref_lines[i1:i2], hyp_lines[j1:j2]):
                total = _add_counts(total, _exact_counts(tokenize(ref_line), tokenize(hyp_line)))
        elif tag == "delete":
            n = sum(length(x) for x in ref_lines[i1:i2])
            total = _add_counts(total, EditCounts(0, n, 0, n, False))
        elif tag == "insert":
            n = sum(length(x) for x in hyp_lines[j1:j2])
            total = _add_counts(total, EditCounts(0, 0, n, 0, False))
        else:  # replace
            paired = min(i2 - i1, j2 - j1)
            for k in range(paired):
                total = _add_counts(total, _exact_counts(tokenize(ref_lines[i1 + k]),
                                                         tokenize(hyp_lines[j1 + k])))
            for ref_line in ref_lines[i1 + paired:i2]:
                n = length(ref_line)
                total = _add_counts(total, EditCounts(0, n, 0, n, False))
            for hyp_line in hyp_lines[j1 + paired:j2]:
                total = _add_counts(total, EditCounts(0, 0, length(hyp_line), 0, False))
    return total


def _add_counts(a: EditCounts, b: EditCounts) -> EditCounts:
    return EditCounts(
        a.substitutions + b.substitutions,
        a.deletions + b.deletions,
        a.insertions + b.insertions,
        a.ref_len + b.ref_len,
        a.exact and b.exact,
    )


def edit_counts(ref: str, hyp: str, *, unit: str = "char", max_cells: int = 20_000_000) -> EditCounts:
    """Đếm S/D/I giữa ref và hyp bằng Levenshtein.

    unit='char' cho CER, unit='word' cho WER. Với chuỗi ngắn (mặc định
    <= 20 triệu ô DP) kết quả là Levenshtein chính xác. Với chuỗi lớn hơn,
    module căn theo dòng và trả exact=False; muốn số chính xác tuyệt đối,
    hãy chia đầu vào thành từng trang rồi gọi evaluate_pages().
    """
    if unit not in {"char", "word"}:
        raise ValueError("unit phải là 'char' hoặc 'word'")
    ref_tokens, hyp_tokens = _tokens(ref, unit), _tokens(hyp, unit)
    if len(ref_tokens) * len(hyp_tokens) <= max_cells:
        return _exact_counts(ref_tokens, hyp_tokens)
    return _line_counts(ref.splitlines(keepends=True), hyp.splitlines(keepends=True), unit)


def cer(ref: str, hyp: str, *, normalize: bool = True, strip_math: bool = False,
        lower: bool = False, **kwargs) -> float:
    if normalize:
        ref = normalize_text(ref, strip_math=strip_math, lower=lower)
        hyp = normalize_text(hyp, strip_math=strip_math, lower=lower)
    return edit_counts(ref, hyp, unit="char", **kwargs).rate


def wer(ref: str, hyp: str, *, normalize: bool = True, strip_math: bool = False,
        lower: bool = False, **kwargs) -> float:
    if normalize:
        ref = normalize_text(ref, strip_math=strip_math, lower=lower)
        hyp = normalize_text(hyp, strip_math=strip_math, lower=lower)
    return edit_counts(ref, hyp, unit="word", **kwargs).rate


def page_error_rate(pairs: list[tuple[str, str]], *, threshold: float = 0.0, **kwargs) -> float:
    """Tỉ lệ trang có CER > threshold. threshold=0 là định nghĩa PER nghiêm."""
    if not pairs:
        return 0.0
    bad = sum(1 for ref, hyp in pairs if cer(ref, hyp, **kwargs) > threshold)
    return bad / len(pairs)


def evaluate_pages(
    pairs: list[tuple[str, str]],
    *,
    names: list[str] | None = None,
    strip_math: bool = False,
    lower: bool = False,
    threshold: float = 0.0,
) -> CorpusMetrics:
    """Tính CER/WER/PER trên danh sách (ref, hyp) theo từng trang.

    CER/WER toàn bộ là micro-average: tổng lỗi / tổng độ dài tham chiếu,
    không phải trung bình cộng CER các trang. Cách này tránh để trang ngắn
    chi phối kết quả.
    """
    names = names or [f"page-{i + 1}" for i in range(len(pairs))]
    pages: list[PageMetrics] = []
    total_char = EditCounts(0, 0, 0, 0)
    total_word = EditCounts(0, 0, 0, 0)
    exact = True
    for name, (ref_raw, hyp_raw) in zip(names, pairs):
        ref = normalize_text(ref_raw, strip_math=strip_math, lower=lower)
        hyp = normalize_text(hyp_raw, strip_math=strip_math, lower=lower)
        char_counts = edit_counts(ref, hyp, unit="char")
        word_counts = edit_counts(ref, hyp, unit="word")
        total_char = _add_counts(total_char, char_counts)
        total_word = _add_counts(total_word, word_counts)
        exact = exact and char_counts.exact and word_counts.exact
        pages.append(PageMetrics(
            name=name,
            cer=char_counts.rate,
            wer=word_counts.rate,
            char_counts=char_counts,
            word_counts=word_counts,
        ))
    n_bad = sum(1 for p in pages if p.cer > threshold)
    return CorpusMetrics(
        cer=total_char.rate,
        wer=total_word.rate,
        per=(n_bad / len(pages)) if pages else 0.0,
        page_exact_match_rate=((len(pages) - n_bad) / len(pages)) if pages else 0.0,
        n_pages=len(pages),
        n_pages_with_error=n_bad,
        char_counts=total_char,
        word_counts=total_word,
        pages=pages,
        exact=exact,
    )


def split_pages(text: str) -> list[str]:
    """Tách trang bằng form feed (\\f); không có form feed thì coi là một trang."""
    if "\f" not in text:
        return [text]
    return text.split("\f")


def read_document(path: Path) -> str:
    """Đọc .txt/.md hoặc .docx. DOCX lấy paragraph + cell, không lấy OMML."""
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:  # pragma: no cover - phụ thuộc môi trường
            raise RuntimeError("Cần python-docx để đọc .docx") from exc
        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    raise ValueError(f"Không hỗ trợ đọc {path.suffix}: {path}")


def _find_hypothesis(hyp_dir: Path, stem: str) -> Path | None:
    for suffix in (".txt", ".md", ".markdown", ".text", ".docx"):
        candidate = hyp_dir / f"{stem}{suffix}"
        if candidate.exists():
            return candidate
    return None


def collect_pairs(ref_path: Path, hyp_path: Path) -> list[tuple[str, str, str]]:
    """Trả [(tên, ref_text, hyp_text)] từ hai file hoặc hai thư mục."""
    if ref_path.is_file():
        return [(ref_path.stem or "input", read_document(ref_path), read_document(hyp_path))]
    pairs = []
    for ref_file in sorted(ref_path.iterdir()):
        if ref_file.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        hyp_file = _find_hypothesis(hyp_path, ref_file.stem)
        if hyp_file is None:
            print(f"[BỎ QUA] không có đầu ra cho {ref_file.name}", file=sys.stderr)
            continue
        pairs.append((ref_file.stem, read_document(ref_file), read_document(hyp_file)))
    return pairs


def _format_table(result: CorpusMetrics) -> str:
    rows = [("Tên", "CER", "WER", "S", "D", "I", "N")]
    for page in result.pages:
        c = page.char_counts
        rows.append((page.name, f"{page.cer:.4%}", f"{page.wer:.4%}",
                     str(c.substitutions), str(c.deletions), str(c.insertions), str(c.ref_len)))
    c = result.char_counts
    rows.append(("TỔNG", f"{result.cer:.4%}", f"{result.wer:.4%}",
                 str(c.substitutions), str(c.deletions), str(c.insertions), str(c.ref_len)))
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows]
    lines.append("")
    lines.append(f"PER (Page Error Rate, ngưỡng 0): {result.per:.2%} "
                 f"({result.n_pages_with_error}/{result.n_pages} trang có lỗi)")
    lines.append(f"Page exact match: {result.page_exact_match_rate:.2%}")
    if not result.exact:
        lines.append("Lưu ý: một phần kết quả dùng căn theo dòng (xấp xỉ), không phải Levenshtein toàn chuỗi.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Tính CER/WER/PER giữa ground truth và đầu ra chuyển đổi.")
    parser.add_argument("--ref", type=Path, required=True,
                        help="File hoặc thư mục ground truth (.txt/.md/.docx)")
    parser.add_argument("--hyp", type=Path, required=True,
                        help="File hoặc thư mục đầu ra cần đo")
    parser.add_argument("--strip-math", action="store_true",
                        help="Bỏ vùng $...$/$$...$$ trước khi đo văn bản")
    parser.add_argument("--lower", action="store_true", help="So sánh không phân biệt hoa thường")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="Ngưỡng CER để tính một trang là lỗi (mặc định 0)")
    parser.add_argument("--json", type=Path, help="Ghi kết quả đầy đủ ra JSON")
    args = parser.parse_args(argv)

    pairs = collect_pairs(args.ref, args.hyp)
    if not pairs:
        print("Không tìm được cặp file nào để đo.", file=sys.stderr)
        return 2

    all_pages: list[tuple[str, str]] = []
    names: list[str] = []
    for name, ref_text, hyp_text in pairs:
        ref_pages, hyp_pages = split_pages(ref_text), split_pages(hyp_text)
        if len(ref_pages) != len(hyp_pages):
            print(f"[CẢNH BÁO] {name}: ref có {len(ref_pages)} trang, hyp có {len(hyp_pages)} trang; "
                  f"ghép theo thứ tự và trang thiếu coi là rỗng.", file=sys.stderr)
        for index, (ref_page, hyp_page) in enumerate(zip_longest(ref_pages, hyp_pages, fillvalue="")):
            names.append(f"{name}:{index + 1}" if len(ref_pages) > 1 or len(hyp_pages) > 1 else name)
            all_pages.append((ref_page, hyp_page))

    result = evaluate_pages(all_pages, names=names, strip_math=args.strip_math,
                            lower=args.lower, threshold=args.threshold)
    print(_format_table(result))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã ghi JSON: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
