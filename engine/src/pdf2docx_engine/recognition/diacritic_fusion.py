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
  3. Căn từng chữ, rồi bỏ phiếu có trọng số (Vision 1; Tesseract 1 nếu conf >= TESS_MIN, chỉ có Tesseract
     thì cần >= SINGLE_CONF; MinerU MINERU_WEIGHT):
       - Cùng mặt chữ, khác dấu: lấy dạng có tổng phiếu cao nhất.
       - Khác hẳn chữ (MinerU bịa "newborn" thay "nhẫn"), hoặc MinerU dính 2 chữ ("kìảo" -> "kì ảo"):
         chỉ đổi khi >= 2 bộ OCR cùng đọc ra đúng 1 dạng.
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

SINGLE_CONF = 95          # chỉ có Tesseract: đo trên AAA, đọc sai dấu ở conf 75-93, đúng ở 96-97
TESS_MIN = 90             # có Vision: phiếu Tesseract < 90 bị bỏ (đo: "lỗng" 61, "ổn" 89 đều sai, Vision đúng)
MINERU_WEIGHT = 0.9       # VLM MinerU yếu dấu tiếng Việt -> thua 1 bộ OCR khi bất đồng, thắng khi có thêm Tesseract
VISION_WEIGHT = 0.6       # mỗi lượt Vision (300, 400 DPI) — 2 lượt cùng 1 engine, sai cùng nhau ("hoá" -> "hoa")
VISION_DPIS = (300, 400)  # Vision đọc cả trang ở 2 độ phân giải = 2 phiếu (đo AAA 6 trang: 300 sai 2, 400 sai 5, cả 2: 1)
RECHECK_DPI = 400         # đọc lại sát 1 dòng: Vision đọc đúng chữ nghiêng mà cả trang đọc sai ("ở lại", "chầy")
LEX_BONUS = 1.0           # từ điển = 1 phiếu: dạng ghép với chữ bên cạnh thành từ có trong từ điển (dạng kia không). 1.5 làm hỏng "hò đò" -> "hồ đồ"
# Viet74K (GPL-2.0): KHÔNG đóng gói vào repo, tải về cache khi chạy lần đầu
LEXICON_URL = "https://raw.githubusercontent.com/duyet/vietnamese-wordlist/master/Viet74K.txt"
_WORD = re.compile(r"[^\W\d_]+")
# vùng giữ nguyên trong dòng: công thức và thẻ HTML (chú thích cuối trang MinerU bọc <small><span ...>)
_MATH = re.compile(r"\$\$.*?\$\$|\$[^$\n]+?\$|<[^>]+>", re.S)
_SKIP_LINE = re.compile(r"^\s*(!\[|\|)")   # ảnh, bảng


def _line_words(ln: str) -> list[re.Match]:
    """Chữ của dòng, bỏ qua công thức/thẻ HTML; đánh số chung cho cả dòng (fuse và recheck dùng chung)."""
    keep = [m.span() for m in _MATH.finditer(ln)]
    return [m for m in _WORD.finditer(ln) if not any(a <= m.start() < b for a, b in keep)]
_ROMAN = re.compile(r"[IVXLCDM]+")
_SWIFT = Path(__file__).with_name("vision_ocr.swift")
_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}   # 1 luồng/tiến trình, song song bằng ThreadPool


def base(word: str) -> str:
    """Mặt chữ không dấu, chữ thường: 'Phản' -> 'phan', 'ĐỀ' -> 'de'."""
    s = unicodedata.normalize("NFD", word.lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


_TONES = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}   # huyền, sắc, ngã, hỏi, nặng


def tone_key(word: str) -> tuple[str, str]:
    """(chữ bỏ dấu thanh, các dấu thanh): "hoá" và "hóa" (chỉ khác chỗ đặt dấu) cùng key."""
    d = unicodedata.normalize("NFD", word.lower())
    return (unicodedata.normalize("NFC", "".join(c for c in d if c not in _TONES)),
            "".join(sorted(c for c in d if c in _TONES)))


def ck(text: str) -> str:
    """Khoá so từ điển không phụ thuộc chỗ đặt dấu: "văn hoá" == "văn hóa" (Viet74K viết kiểu cũ "hóa")."""
    return " ".join("|".join(tone_key(s)) for s in text.split())


def _match_case(src: str, new: str) -> str:
    """Giữ kiểu hoa/thường của chữ MinerU, chỉ lấy dấu từ bộ OCR khác."""
    if src.isupper():
        return new.upper()
    if src[:1].isupper():
        return new[:1].upper() + new[1:].lower()
    return new.lower()


def load_lexicon(cache: Path) -> set[str]:
    """Từ điển từ nhiều âm tiết (chữ thường, NFC). Không tải được -> set rỗng (bỏ qua bước từ điển)."""
    f = cache / "Viet74K.txt"
    if not f.exists():
        try:
            import urllib.request
            cache.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(LEXICON_URL, f)
        except OSError:
            return set()
    return {ck(unicodedata.normalize("NFC", l.strip().lower())) for l in f.open(encoding="utf-8") if " " in l.strip()}


def _vision_bin(cache: Path) -> Path | None:
    """Biên dịch vision_ocr.swift 1 lần (cần macOS + swiftc). Không có -> None."""
    exe = cache / "vision_ocr"
    if not exe.exists() and shutil.which("swiftc"):
        cache.mkdir(parents=True, exist_ok=True)
        subprocess.run(["swiftc", "-O", str(_SWIFT), "-o", str(exe)], capture_output=True)
    return exe if exe.exists() else None


def _vision_read(vision: Path, images: list[Path]) -> list[list[tuple[str, float]]]:
    """Vision OCR nhiều ảnh trong 1 lần gọi -> danh sách chữ (chữ, conf) theo từng ảnh."""
    out = [[] for _ in images]
    r = subprocess.run([str(vision), *map(str, images)], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        i, conf, text = line.split("\t", 2)
        out[int(i)] += [(w, float(conf)) for w in _WORD.findall(unicodedata.normalize("NFC", text))]
    return out


def ocr_pages(pdf: Path, cache: Path, dpi: int = 300, workers: int = 8, lang: str = "vie",
              vision_dpis: tuple[int, ...] = VISION_DPIS) -> dict[str, list]:
    """OCR mọi trang (cache theo trang). Trả {"tesseract": [(chữ, conf, trang, bbox_pt)...],
    "vision": [(chữ, conf)...], "vision400": [...]} theo thứ tự trang."""
    import pymupdf

    cache.mkdir(parents=True, exist_ok=True)
    n = pymupdf.open(pdf).page_count
    vision = _vision_bin(cache.parent / "bin")
    has_tess = shutil.which("tesseract") is not None

    def one(i: int):
        stem = cache / f"p{i + 1:03d}"
        tsv, png = stem.with_suffix(".tsv"), stem.with_suffix(".png")
        if has_tess and not tsv.exists():
            pymupdf.open(pdf)[i].get_pixmap(dpi=dpi).save(png)
            subprocess.run(["tesseract", str(png), str(stem), "-l", lang, "--psm", "4", "tsv"],
                           capture_output=True, env=_ENV)
        vis = {d: stem.with_suffix(".vis" if d == 300 else f".v{d}.vis") for d in vision_dpis}
        for d, f in vis.items():
            if vision and not f.exists():
                pymupdf.open(pdf)[i].get_pixmap(dpi=d).save(png)
                f.write_text(subprocess.run([str(vision), str(png)], capture_output=True, text=True).stdout,
                             encoding="utf-8")
        png.unlink(missing_ok=True)
        t = []
        if tsv.exists():
            k = 72 / dpi   # px -> pt
            for row in csv.DictReader(tsv.open(encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
                if (row.get("text") or "").strip():
                    box = tuple(float(row[c]) * k for c in ("left", "top", "width", "height"))
                    t += [(w, float(row["conf"]), i, box) for w in _WORD.findall(unicodedata.normalize("NFC", row["text"]))]
        v = {}
        for d, f in vis.items():
            v[d] = []
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    _, conf, text = line.split("\t", 2)
                    v[d] += [(w, float(conf)) for w in _WORD.findall(unicodedata.normalize("NFC", text))]
        return t, v

    with ThreadPoolExecutor(workers) as ex:
        pages = list(ex.map(one, range(n)))
    out = {"tesseract": [w for t, _ in pages for w in t]}
    for d in vision_dpis:
        out["vision" if d == 300 else f"vision{d}"] = [w for _, v in pages for w in v[d]]
    return {k: v for k, v in out.items() if v}


class _Reference:
    """Danh sách chữ (kèm độ tin cậy) của 1 bộ OCR + chỉ mục ngược cụm 3 chữ không dấu."""

    def __init__(self, words: list[tuple[str, float]]):
        self.words = words
        self.bases = [base(w[0]) for w in words]
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
            # MinerU dính 2 chữ thành 1 ("kìảo"), bộ OCR này tách đúng ("kì ảo")
            elif a == "replace" and i2 - i1 == 1 and j2 - j1 == 2 and "".join(rb[j1:j2]) == line_bases[i1]:
                (w1, c1), (w2, c2) = self.words[lo + j1][:2], self.words[lo + j1 + 1][:2]
                got[i1] = (f"{w1} {w2}", min(c1, c2))
        return got


def _decide(word: str, alts: dict[str, tuple[str, float]], min_votes: int, single_conf: float,
            prev: str | set[str] = "", nxt: str | set[str] = "", lexicon: set[str] = frozenset()) -> str | None:
    """Dạng mới cho chữ MinerU, hoặc None (giữ nguyên). alts: {bộ OCR: (chữ, conf)} các bộ khớp được."""
    # chỉ khác chỗ đặt dấu thanh ("hóa"/"hoá") = cùng chữ -> coi như đồng ý với MinerU
    alts = {e: (word if tone_key(a[0]) == tone_key(word) else a[0], a[1]) for e, a in alts.items()}
    if not any(w.lower() != word.lower() for w, _ in alts.values()):
        return None
    # khác hẳn chữ / tách chữ dính: cần >= min_votes bộ OCR cùng đọc ra 1 dạng
    other = Counter(w.lower() for w, _ in alts.values() if base(w.replace(" ", "")) != base(word) or " " in w)
    if other:
        form, n = other.most_common(1)[0]
        return form if n >= min_votes else None
    tess_min = TESS_MIN if "vision" in alts else single_conf
    score = Counter({word.lower(): MINERU_WEIGHT})
    for eng, (w, c) in alts.items():
        score[w.lower()] += (c >= tess_min) if eng == "tesseract" else VISION_WEIGHT if eng.startswith("vision") else 1.0
    if lexicon and len(score) > 1:
        # chữ bên cạnh: mọi dạng các nguồn đọc ra (MinerU sai cả 2 chữ liền nhau: "lùa đối" -> "lừa dối")
        ps, ns = ({prev} if isinstance(prev, str) else prev), ({nxt} if isinstance(nxt, str) else nxt)
        in_lex = {f: any(ck(f"{p} {f}") in lexicon for p in ps if p) or any(ck(f"{f} {x}") in lexicon for x in ns if x)
                  for f in score}
        if any(in_lex.values()) and not all(in_lex.values()):
            for f, ok in in_lex.items():
                score[f] += LEX_BONUS * ok
    form, top = score.most_common(1)[0]
    return form if form != word.lower() and top > score[word.lower()] else None


def fuse_markdown(md: str, refs: dict[str, list], min_votes: int = 2, single_conf: float = SINGLE_CONF,
                  lexicon: set[str] = frozenset()) -> tuple[str, dict]:
    """Sửa chữ Markdown MinerU theo các bộ OCR trong refs. Công thức, ảnh, bảng, HTML giữ nguyên."""
    R = {k: _Reference(v) for k, v in refs.items()}
    stats, flags = Counter(), []
    syllables = {s for wd in lexicon for s in wd.split()}   # khoá ck các âm tiết hợp lệ
    lines = md.split("\n")
    for n, ln in enumerate(lines):
        if not ln.strip() or _SKIP_LINE.match(ln) or "data:image" in ln:
            continue
        words = _line_words(ln)
        lb = [base(m[0]) for m in words]
        aligned = {k: r.align(lb) for k, r in R.items()} if len(lb) >= 3 else {}
        out, pos = [], 0
        for k, m in enumerate(words):
            w = m[0]
            # 1 ký tự không dấu ("I", "a") và số La Mã: bỏ qua; chữ 1 ký tự có dấu ("ở", "ý") vẫn xét
            if (len(w) < 2 and w.isascii()) or (_ROMAN.fullmatch(w) and len(w) <= 4):
                continue
            alts = {e: a[k] for e, a in aligned.items() if k in a}
            def near(j):   # dạng MinerU + các bộ OCR của chữ thứ j
                if not 0 <= j < len(words):
                    return set()
                return {words[j][0].lower()} | {a[j][0].lower() for a in aligned.values() if j in a and " " not in a[j][0]}
            new = _decide(w, alts, min_votes, single_conf, prev=near(k - 1), nxt=near(k + 1), lexicon=lexicon)
            # bất đồng thật: bỏ dạng chỉ khác chỗ đặt dấu ("hóa"/"hoá") và âm tiết không hợp lệ ("hóá")
            chosen = (new or w).lower()
            forms = {ck(chosen)} | {ck(a[0].lower()) for a in alts.values()
                                    if " " not in a[0] and (not syllables or ck(a[0].lower()) in syllables)}
            if len(forms) > 1:
                flags.append({"line": n + 1, "k": k, "word": w, "chosen": new or w,
                              "ocr": {e: a[0] for e, a in alts.items()}})
            if new is None:
                continue
            new = _match_case(w, new)
            out.append(ln[pos:m.start()] + new)
            pos = m.end()
            stats[f"{w}->{new}"] += 1
        lines[n] = "".join(out) + ln[pos:]
    changes = dict(stats.most_common())
    return "\n".join(lines), {"engines": list(refs), "words_changed": sum(changes.values()),
                              "changes": changes, "flags": flags}


def recheck(md: str, pdf: Path, refs: dict[str, list], lexicon: set[str], cache: Path,
            flags: list[dict] = ()) -> tuple[str, dict]:
    """Đọc lại sát dòng (Vision, RECHECK_DPI) các chữ khả nghi; ảnh cắt sát là trọng tài cuối.

    Khả nghi khi:
      - các bộ OCR bất đồng (flags của fuse_markdown): ứng viên = các dạng bộ OCR đã đọc ra
        (vd "ô lại": MinerU + Vision "ô", Tesseract 96 điểm "ở"); hoặc
      - chữ thường không ghép được từ nào trong từ điển với chữ bên cạnh mà 1 biến thể DẤU thì ghép được.
        Từ điển chỉ chỉ ra chỗ cần xem (tự đổi theo từ điển: đo AAA 3 -> 62 lỗi).
    Chỉ đổi khi Vision trên ảnh cắt sát đọc ra đúng 1 ứng viên, chữ bên cạnh khớp, VÀ Tesseract (engine khác
    Vision, conf >= TESS_MIN) cũng đọc ra dạng đó. Ảnh cắt một mình sai ~1/2 mẫu ("nhất thống chí" -> "chi"),
    và Vision cả trang cũng sai cùng kiểu ("hiện đại hoá" -> "hoa") nên không dùng làm phiếu ủng hộ."""
    import pymupdf

    vision = _vision_bin(cache.parent / "bin")
    if not (vision and lexicon and "tesseract" in refs):
        return md, {"rechecked": 0, "changed": {}}
    variants: dict[str, set[str]] = defaultdict(set)   # mặt chữ -> các âm tiết (dạng khoá ck)
    for wd in lexicon:
        for syl in wd.split():
            variants[base(syl.split("|")[0])].add(syl)
    syllables = {s for v in variants.values() for s in v}   # âm tiết hợp lệ: chặn "hòà", "qưá", "họạ"
    tess = _Reference(refs["tesseract"])
    R = {k: (tess if k == "tesseract" else _Reference(v)) for k, v in refs.items()}
    support: dict[tuple[int, int], set[str]] = {}   # (dòng, vị trí chữ) -> khoá ck các dạng bộ OCR đọc cả trang
    lines = md.split("\n")
    targets = []   # (dòng, vị trí chữ, chữ, các biến thể, trang, khung dòng pt)
    flagged = defaultdict(dict)   # dòng -> {vị trí chữ: ứng viên từ các bộ OCR}
    for f in flags:
        alts = {a.lower() for a in f["ocr"].values() if " " not in a and ck(a.lower()) != ck(f["chosen"].lower())}
        if alts:
            flagged[f["line"] - 1][f["k"]] = alts
    for n, ln in enumerate(lines):
        if not ln.strip() or _SKIP_LINE.match(ln) or "data:image" in ln:
            continue
        words = _line_words(ln)
        lw = [m[0].lower() for m in words]

        def joined(k, f):
            # f: khoá ck của 1 âm tiết
            left = k and not ln[words[k - 1].end():words[k].start()].strip() and f"{ck(lw[k - 1])} {f}" in lexicon
            right = k + 1 < len(words) and not ln[words[k].end():words[k + 1].start()].strip() and f"{f} {ck(lw[k + 1])}" in lexicon
            return bool(left or right)

        aligned = None
        for k, w in enumerate(lw):
            if len(w) < 2 and w.isascii():
                continue
            cands = flagged.get(n, {}).get(k)
            if not cands:
                if words[k][0][:1].isupper() or joined(k, ck(w)):   # chữ hoa: tên riêng -> không đoán theo từ điển
                    continue
                cands = {v for v in variants.get(base(w), ()) if v != ck(w) and joined(k, v)}
            if not cands:
                continue
            if aligned is None:
                lb = [base(x) for x in lw]
                every = {e: r.align(lb) for e, r in R.items()} if len(lw) >= 3 else {}
                aligned = every.get("tesseract", {})
            tk = aligned.get(k)
            support[(n, k)] = {ck(tk[0].lower())} if tk and tk[1] >= TESS_MIN else set()
            t = aligned.get(k)
            if t is None or len(t) < 4:
                continue
            targets.append((n, k, words[k], cands, t[2], t[3]))
    if not targets:
        return md, {"rechecked": 0, "changed": {}}
    doc, imgs, boxes = pymupdf.open(pdf), [], {}
    cache.mkdir(parents=True, exist_ok=True)
    for page, (x, y, w, h) in {(t[4], t[5]) for t in targets}:
        r = doc[page].rect
        # lề trên 1.2 dòng: 0.6 cắt mất dấu sắc ("văn hoá" đọc thành "văn hoa", đo AAA tr.58)
        clip = pymupdf.Rect(r.x0, max(r.y0, y - 1.2 * h), r.x1, min(r.y1, y + 2.0 * h))
        f = cache / f"rc{len(imgs):05d}.png"
        doc[page].get_pixmap(dpi=RECHECK_DPI, clip=clip).save(f)
        boxes[(page, (x, y, w, h))] = len(imgs)
        imgs.append(f)
    reads = []
    for i in range(0, len(imgs), 200):
        reads += _vision_read(vision, imgs[i:i + 200])
    for f in imgs:
        f.unlink(missing_ok=True)
    changed, edits = Counter(), defaultdict(list)
    for n, k, m, cands, page, box in targets:
        crop = reads[boxes[(page, box)]]
        cw = [c[0].lower() for c in crop]
        lw = [x[0].lower() for x in _line_words(lines[n])]
        # tìm đúng chữ trong dòng đọc lại: cùng mặt chữ + chữ bên cạnh khớp mặt chữ
        for j, c in enumerate(cw):
            if (c in cands or ck(c) in cands) and ck(c) in syllables and tone_key(c) != tone_key(lw[k]) \
                    and ck(c) in support.get((n, k), ()) and (
                    base(c) == base(lw[k]) or k in flagged.get(n, {})) and (
                    (k and j and base(cw[j - 1]) == base(lw[k - 1])) or
                    (k + 1 < len(lw) and j + 1 < len(cw) and base(cw[j + 1]) == base(lw[k + 1]))):
                edits[n].append((m, _match_case(m[0], c)))
                changed[f"{m[0]}->{c}"] += 1
                break
    for n, es in edits.items():
        ln, out, pos = lines[n], [], 0
        for m, new in sorted(es, key=lambda e: e[0].start()):
            out.append(ln[pos:m.start()] + new)
            pos = m.end()
        lines[n] = "".join(out) + ln[pos:]
    return "\n".join(lines), {"rechecked": len(targets), "crops": len(imgs), "changed": dict(changed.most_common())}


def place_tone(syl: str, new_style: bool = True) -> str:
    """Đặt dấu thanh đúng chính tả cho 1 âm tiết chữ thường. Kiểu mới (sách giáo khoa): "hoá", "thuỷ", "khoẻ"."""
    d = unicodedata.normalize("NFD", syl)
    tones = [c for c in d if c in _TONES]
    bare = unicodedata.normalize("NFC", "".join(c for c in d if c not in _TONES))
    m = re.match(r"^(qu|gi(?=[aăâeêoôơuư])|[^aăâeêioôơuưy]*)([aăâeêioôơuưy]+)(.*)$", bare)
    if not tones or not m:
        return syl
    head, vow, tail = m.groups()
    idx = max((i for i, c in enumerate(vow) if c in "ăâêôơư"), default=None)   # có mũ/móc nhận dấu (ươ -> ơ)
    if idx is None:
        idx = 0 if len(vow) == 1 else 1 if (len(vow) == 3 or tail or (new_style and vow in ("oa", "oe", "uy"))) else 0
    return head + vow[:idx] + unicodedata.normalize("NFC", vow[idx] + tones[0]) + vow[idx + 1:] + tail


def fix_tone_placement(md: str, lexicon: set[str]) -> tuple[str, dict]:
    """Sửa chữ đặt dấu thanh sai chỗ theo cả kiểu cũ lẫn kiểu mới ("diụ" -> "dịu", "meọ" -> "mẹo").
    Chỉ âm tiết hợp lệ trong từ điển, >= 3 ký tự (chữ 2 ký tự không phụ âm đầu dễ là mảnh chữ)."""
    syllables = {s for wd in lexicon for s in wd.split()}
    stats = Counter()

    def fix(m):
        w, low = m[0], m[0].lower()
        if len(w) < 3 or ck(low) not in syllables or low in (place_tone(low), place_tone(low, False)):
            return w
        stats[f"{w}->{place_tone(low)}"] += 1
        return _match_case(w, place_tone(low))

    out = [ln if (_SKIP_LINE.match(ln) or "data:image" in ln) else
           "".join(p if i % 2 else _WORD.sub(fix, p) for i, p in enumerate(re.split(f"({_MATH.pattern})", ln, flags=re.S)))
           for ln in md.split("\n")]
    return "\n".join(out), dict(stats)


def drop_facing_page_slivers(md: str, lexicon: set[str]) -> tuple[str, list[str]]:
    """Bỏ khối chữ lọt từ mép trang bên cạnh của sách scan (MinerU đọc cả dải hẹp trang kia).

    Khối bị bỏ khi đủ cả 3: >= 3 dòng, >= 80% dòng ngắn (<= 25 ký tự); >= 60% dòng (bỏ chữ đầu bị cắt)
    trùng (theo mặt chữ không dấu) chỗ khác trong tài liệu (trang bên cũng được OCR đầy đủ); >= 50% dòng mở đầu bằng chữ thường
    hoặc mảnh chữ không phải âm tiết ("nuốn trở về", "ug làm được") -> thơ (mỗi dòng viết hoa) không bị bỏ."""
    syllables = {s for wd in lexicon for s in wd.split()}
    lines = md.split("\n")
    blocks, cur = [], []
    for i, ln in enumerate(lines + [""]):
        if ln.strip() and not _SKIP_LINE.match(ln) and "data:image" not in ln and not ln.lstrip().startswith(("#", "$")):
            cur.append(i)
        else:
            if len(cur) >= 3:
                blocks.append(cur)
            cur = []
    def norm(t: str) -> str:   # chỉ chữ, mặt chữ không dấu: mảnh bị đọc sai dấu / dấu câu khác bản chính
        return " ".join(base(w) for w in _WORD.findall(t))

    flat = " " + norm(" ".join(lines)) + " "
    drop, removed = set(), []
    for b in blocks:
        texts = [" ".join(lines[i].split()) for i in b]
        if sum(len(t) <= 25 for t in texts) < 0.8 * len(texts):
            continue
        rest = flat.replace(" " + norm(" ".join(texts)) + " ", " ")
        found = cut = 0
        for t in texts:
            words = t.split(" ")
            tail = " ".join(words[1:]) if len(words) > 1 else ""
            found += len(tail) >= 4 and f" {norm(tail)} " in rest
            first = _WORD.match(words[0])
            cut += bool(first) and (words[0][:1].islower() or (syllables and ck(first[0].lower()) not in syllables))
        if found >= 0.6 * len(texts) and cut >= 0.5 * len(texts):
            drop.update(b)
            removed.append(" / ".join(texts))
    return "\n".join(ln for i, ln in enumerate(lines) if i not in drop), removed
