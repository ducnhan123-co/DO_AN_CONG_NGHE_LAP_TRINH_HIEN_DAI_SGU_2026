"""Sửa DẤU tiếng Việt trong Markdown của MinerU bằng cách cho nhiều bộ OCR bỏ phiếu.

Đo 2026-10-26 trên sách AAA, 2 trang ngẫu nhiên gõ tay làm đáp án (1.009 chữ): MinerU sai 8,72% chữ;
ghép Tesseract + Vision còn 0,59%; chỉ Tesseract 2,78%.
Trên sách scan AAA (chữ in rõ): VLM của MinerU (MinerU2.5-Pro 1.2B) đọc sai dấu
("CHUYÊN ĐỀ" -> "CHUYÊN ĐÊ", "Ngữ văn" -> "Ngũ văn", "phản ánh" -> "phần ánh"), trong khi Tesseract (vie)
và Apple Vision (vi-VT) đọc đúng. MinerU vẫn giữ bố cục / công thức / ảnh; ở đây chỉ đổi DẤU.

Cách làm:
  1. Mỗi trang render 1 lần, OCR bằng Tesseract (độ tin cậy từng chữ) + Apple Vision (macOS, nếu có).
     Windows/Linux không có Apple Vision -> chỉ Tesseract (chỉ sửa dấu khi conf >= SINGLE_CONF).
  2. Mỗi chữ -> mặt chữ không dấu ("phản" -> "phan"); chỉ mục ngược cụm 3 chữ -> tìm đoạn khớp dòng MinerU.
  3. Căn từng chữ, rồi quyết định:
       - Cùng mặt chữ, khác dấu: đổi khi >= 2 bộ OCR cùng đọc ra 1 dạng, hoặc chỉ 1 bộ khớp được dòng
         đó nhưng rất chắc (>= SINGLE_CONF).
       - Khác hẳn chữ (MinerU bịa "newborn" thay "nhẫn"): chỉ đổi khi >= 2 bộ OCR cùng đọc ra 1 chữ.
     Các bộ OCR đọc khác nhau -> giữ nguyên, ghi vào "flags" để người duyệt.
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

SINGLE_CONF = 95          # đo trên AAA: Tesseract đọc sai dấu ở conf 75-93, đọc đúng ở 96-97
_WORD = re.compile(r"[^\W\d_]+")
_MATH = re.compile(r"\$\$.*?\$\$|\$[^$\n]+?\$", re.S)
_SKIP_LINE = re.compile(r"^\s*(<|!\[|\|)")
_ROMAN = re.compile(r"[IVXLCDM]+")
_SWIFT = Path(__file__).with_name("vision_ocr.swift")
_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}   # 1 luồng/tiến trình, song song bằng ThreadPool


def base(word: str) -> str:
    """Mặt chữ không dấu, chữ thường: 'Phản' -> 'phan', 'ĐỀ' -> 'de'."""
    s = unicodedata.normalize("NFD", word.lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _match_case(src: str, new: str) -> str:
    """Giữ kiểu hoa/thường của chữ MinerU, chỉ lấy dấu từ bộ OCR khác."""
    if src.isupper():
        return new.upper()
    if src[:1].isupper():
        return new[:1].upper() + new[1:].lower()
    return new.lower()


def _vision_bin(cache: Path) -> Path | None:
    """Biên dịch vision_ocr.swift 1 lần (cần macOS + swiftc). Không có -> None."""
    exe = cache / "vision_ocr"
    if not exe.exists() and shutil.which("swiftc"):
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(_SWIFT), "-o", str(exe)], capture_output=True)
    return exe if exe.exists() else None


def ocr_pages(pdf: Path, cache: Path, dpi: int = 300, workers: int = 8, lang: str = "vie") -> dict[str, list]:
    """OCR mọi trang (cache theo trang). Trả {"tesseract": [(chữ, conf)...], "vision": [...]} theo thứ tự trang."""
    import pymupdf

    cache.mkdir(parents=True, exist_ok=True)
    n = pymupdf.open(pdf).page_count
    vision = _vision_bin(cache.parent / "bin")
    has_tess = shutil.which("tesseract") is not None

    def one(i: int) -> tuple[list, list]:
        stem = cache / f"p{i + 1:03d}"
        tsv, vis = stem.with_suffix(".tsv"), stem.with_suffix(".vis")
        need = (has_tess and not tsv.exists()) or (vision and not vis.exists())
        if need:
            png = stem.with_suffix(".png")
            pymupdf.open(pdf)[i].get_pixmap(dpi=dpi).save(png)
            if has_tess and not tsv.exists():
                subprocess.run(["tesseract", str(png), str(stem), "-l", lang, "--psm", "4", "tsv"],
                               capture_output=True, env=_ENV)
            if vision and not vis.exists():
                r = subprocess.run([str(vision), str(png)], capture_output=True, text=True)
                vis.write_text(r.stdout, encoding="utf-8")
            png.unlink(missing_ok=True)
        t = []
        if tsv.exists():
            for row in csv.DictReader(tsv.open(encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
                if (row.get("text") or "").strip():
                    t += [(w, float(row["conf"])) for w in _WORD.findall(unicodedata.normalize("NFC", row["text"]))]
        v = []
        if vis.exists():
            for line in vis.read_text(encoding="utf-8").splitlines():
                _, conf, text = line.split("\t", 2)
                v += [(w, float(conf)) for w in _WORD.findall(unicodedata.normalize("NFC", text))]
        return t, v

    with ThreadPoolExecutor(workers) as ex:
        pages = list(ex.map(one, range(n)))
    out = {"tesseract": [w for t, _ in pages for w in t], "vision": [w for _, v in pages for w in v]}
    return {k: v for k, v in out.items() if v}


class _Reference:
    """Danh sách chữ (kèm độ tin cậy) của 1 bộ OCR + chỉ mục ngược cụm 3 chữ không dấu."""

    def __init__(self, words: list[tuple[str, float]]):
        self.words = words
        self.bases = [base(w) for w, _ in words]
        self.index: dict[tuple, list[int]] = defaultdict(list)
        for i in range(len(self.bases) - 2):
            self.index[tuple(self.bases[i:i + 3])].append(i)

    def align(self, line_bases: list[str]) -> dict[int, tuple[str, float]]:
        """{vị trí chữ trong dòng: (chữ của bộ OCR này, conf)} cho các chữ cùng mặt chữ."""
        votes = Counter()
        for j in range(len(line_bases) - 2):
            for i in self.index.get(tuple(line_bases[j:j + 3]), ())[:50]:
                votes[i - j] += 1
        if not votes:
            return {}
        start, n = votes.most_common(1)[0]
        # ponytail: cần >= 2 cụm 3 chữ trùng (dòng rất ngắn: 1 cụm) mới coi là cùng đoạn văn
        if n < min(2, max(1, len(line_bases) - 2)):
            return {}
        lo = max(0, start - 3)
        rb = self.bases[lo:start + len(line_bases) + 3]
        got = {}
        for a, i1, i2, j1, j2 in SequenceMatcher(None, line_bases, rb, autojunk=False).get_opcodes():
            # equal: cùng mặt chữ; replace cùng số chữ: chữ khác hẳn ở đúng vị trí đó
            if a == "equal" or (a == "replace" and i2 - i1 == j2 - j1):
                got.update({i1 + k: self.words[lo + j1 + k] for k in range(i2 - i1)})
        return got


def _decide(word: str, alts: list[tuple[str, float]], min_votes: int, single_conf: float) -> str | None:
    """Dạng mới cho chữ MinerU, hoặc None (giữ nguyên). alts: chữ của các bộ OCR khớp được."""
    diff = [(w, c) for w, c in alts if w.lower() != word.lower()]
    if not diff:
        return None
    form, n = Counter(w.lower() for w, _ in diff).most_common(1)[0]
    if n >= min_votes:
        return form
    same_base = base(diff[0][0]) == base(word)
    if same_base and len(alts) == 1 and diff[0][1] >= single_conf:
        return diff[0][0].lower()
    return None


def fuse_markdown(md: str, refs: dict[str, list], min_votes: int = 2, single_conf: float = SINGLE_CONF) -> tuple[str, dict]:
    """Sửa dấu Markdown MinerU theo các bộ OCR trong refs. Công thức, ảnh, bảng, HTML giữ nguyên."""
    R = {k: _Reference(v) for k, v in refs.items()}
    stats, flags = Counter(), []
    lines = md.split("\n")
    for n, ln in enumerate(lines):
        if not ln.strip() or _SKIP_LINE.match(ln) or "data:image" in ln:
            continue
        maths = _MATH.findall(ln)
        segs = []
        for seg in _MATH.split(ln):
            words = list(_WORD.finditer(seg))
            lb = [base(m[0]) for m in words]
            aligned = [r.align(lb) for r in R.values()] if len(lb) >= 3 else []
            out, pos = [], 0
            for k, m in enumerate(words):
                w = m[0]
                if len(w) < 2 or (_ROMAN.fullmatch(w) and len(w) <= 4):
                    continue
                alts = [a[k] for a in aligned if k in a]
                new = _decide(w, alts, min_votes, single_conf)
                if new is None:
                    if len({a.lower() for a, _ in alts} | {w.lower()}) > 2:
                        flags.append({"line": n + 1, "word": w, "ocr": [a for a, _ in alts]})
                    continue
                new = _match_case(w, new)
                out.append(seg[pos:m.start()] + new)
                pos = m.end()
                stats[f"{w}->{new}"] += 1
            segs.append("".join(out) + seg[pos:])
        lines[n] = "".join(s + (maths[i] if i < len(maths) else "") for i, s in enumerate(segs))
    changes = dict(stats.most_common())
    return "\n".join(lines), {"engines": list(refs), "words_changed": sum(changes.values()),
                              "changes": changes, "flags": flags}
