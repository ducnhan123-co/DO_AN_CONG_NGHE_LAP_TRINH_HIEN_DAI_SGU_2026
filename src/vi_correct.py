"""Sửa lỗi dấu / chính tả tiếng Việt bằng bmd1905/vietnamese-correction-v2, THEO TỪNG CHỮ.

Model là seq2seq (mBART, ~0.4B): nó viết lại CẢ đoạn. Bản này không lấy cả đoạn của model
mà so từng chữ với bản OCR rồi chỉ nhận những chữ thay đổi hợp lệ:

  - Chữ chứa công thức (placeholder ZM0Z...) không bao giờ bị đổi.
  - Chữ số, dấu câu, ký hiệu đầu dòng (1., ##, -) phải giữ nguyên.
  - Chữ mới phải "gần" chữ cũ: hoặc chỉ khác dấu, hoặc giống >= VI_WORD_SIM (mặc định 0.5).
  - Chỉ đổi hoa/thường -> bỏ.
  - Model thêm / bớt chữ -> bỏ phần đó, giữ nguyên chữ OCR.

Có 2 bước độc lập (cùng một model, nạp 1 lần):
  spelling=True        sửa chính tả từng chữ                      (main.py: --vi-correct)
  add_diacritics=True  bỏ dấu cả đoạn rồi thêm dấu lại theo ngữ cảnh,
                       chỉ nhận chữ khác bản OCR ở dấu             (main.py: --vi-diacritic)

Nhờ vậy một đoạn có 1 chữ sửa đúng + 1 chữ model sửa bậy vẫn nhận được chữ đúng.

Biến môi trường (tuỳ chọn, PowerShell: $env:TÊN = "giá trị"):
  VI_WORD_SIM   ngưỡng giống nhau giữa chữ cũ và mới, mặc định 0.5 (cao = chặt hơn).
  VI_BATCH      kích thước lô, mặc định 16.
  VI_LIMIT      chỉ xử lý N đoạn đầu để chạy thử.

Dùng: đặt file này là src/vi_correct.py, chạy  python main.py --pdf ... --vi-correct
"""
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

MODEL_NAME = os.environ.get("VI_CORRECT_MODEL", "bmd1905/vietnamese-correction-v2")
MAX_CHARS = 400          # model giới hạn 512 token -> cắt đoạn dài theo câu
WORD_SIM = float(os.environ.get("VI_WORD_SIM", "0.5"))
BATCH = int(os.environ.get("VI_BATCH", "16"))
LIMIT = int(os.environ.get("VI_LIMIT", "0") or 0)

_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)
_SKIP_LINE = re.compile(r"^\s*(<|!\[|\||#\s*$)")
_HAS_VI = re.compile(r"[A-Za-zÀ-ỹ]")
_LETTER = re.compile(r"[A-Za-zÀ-ỹ]")
_PH = re.compile(r"ZM(\d+)Z")
_NUM = re.compile(r"\d+")

_pipe = None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _strip_dia(s: str) -> str:
    s = _nfc(s).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------- model
def _get_pipe():
    """Trả về hàm run(texts, max_length, batch_size) -> [{'generated_text': ...}]."""
    global _pipe
    if _pipe is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[vi-correct] tải model {MODEL_NAME} (thiết bị: {device})")
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to(device).eval()

        def run(texts, max_length=512, batch_size=16):
            out = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                enc = tok(batch, return_tensors="pt", padding=True,
                          truncation=True, max_length=max_length).to(device)
                with torch.no_grad():
                    gen = model.generate(**enc, max_length=max_length)
                out += [{"generated_text": t}
                        for t in tok.batch_decode(gen, skip_special_tokens=True)]
                print(f"[vi-correct] {min(i + batch_size, len(texts))}/{len(texts)}",
                      end="\r", flush=True)
            print()
            return out

        _pipe = run
    return _pipe


# --------------------------------------------------------------------------- helpers
def _split_long(s: str, limit: int = MAX_CHARS):
    if len(s) <= limit:
        return [s]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?;:])\s+", s):
        if cur and len(cur) + len(sent) + 1 > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return out


def _mask(line: str):
    spans = []

    def rep(m):
        spans.append(m.group(0))
        return f"ZM{len(spans) - 1}Z"

    return _MATH.sub(rep, line), spans


def _word_ok(a: str, b: str) -> bool:
    """Có nhận chữ b của model thay chữ a của OCR không."""
    a, b = _nfc(a), _nfc(b)
    if a == b:
        return False
    if _PH.search(a) or _PH.search(b):                 # chữ chứa công thức: không đụng
        return False
    if not _LETTER.search(a) or not _LETTER.search(b):  # chỉ số / dấu câu: không đụng
        return False
    if _NUM.findall(a) != _NUM.findall(b):             # không đổi số
        return False
    if _LETTER.sub("", a) != _LETTER.sub("", b):       # dấu câu / ký hiệu giữ nguyên
        return False
    if a.lower() == b.lower():                         # chỉ đổi hoa/thường
        return False
    if _strip_dia(a).lower() == _strip_dia(b).lower():  # chỉ khác dấu -> nhận
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= WORD_SIM


def _merge(src: str, out: str):
    """Trộn từng chữ. Trả (đoạn_mới, [(cũ, mới)], [(cũ, mới) bị bỏ])."""
    a, b = src.split(), out.split()
    if a == b:
        return src, [], []
    res, accepted, rejected = [], [], []
    sm = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            res += a[i1:i2]
        elif tag == "replace" and i2 - i1 == j2 - j1:
            for x, y in zip(a[i1:i2], b[j1:j2]):
                if _word_ok(x, y):
                    res.append(_nfc(y))
                    accepted.append((x, y))
                else:
                    res.append(x)
                    if _nfc(x) != _nfc(y):
                        rejected.append((x, y))
        else:                       # thêm / bớt / lệch số chữ -> giữ nguyên chữ OCR
            res += a[i1:i2]
    if not accepted:
        return src, [], rejected
    return " ".join(res), accepted, rejected


def _dia_merge(src: str, cur: str, out: str):
    """Bước THÊM DẤU. src = đoạn OCR; cur = đoạn sau bước chính tả; out = model thêm dấu lại
    từ bản đã bỏ dấu. Chỉ đổi chữ mà (1) bước chính tả chưa đụng tới, (2) bỏ dấu ra thì giống
    hệt chữ model, (3) không chứa công thức, (4) không chỉ đổi hoa/thường.
    Trả (đoạn_mới, [(cũ, mới)])."""
    a, c, b = src.split(), cur.split(), out.split()
    if len(a) != len(b) or len(a) != len(c):
        return cur, []
    res, acc = list(c), []
    for k, (x, y) in enumerate(zip(a, b)):
        x, y = _nfc(x), _nfc(y)
        if c[k] != a[k] or x == y:
            continue
        if _PH.search(x) or _PH.search(y):
            continue
        if not _LETTER.search(x) or _strip_dia(x) != _strip_dia(y):
            continue
        if x.lower() == y.lower():
            continue
        res[k] = y
        acc.append((x, y))
    if not acc:
        return cur, []
    return " ".join(res), acc


# --------------------------------------------------------------------------- chính
def correct_markdown(md: str, batch_size: int = BATCH, min_len: int = 15,
                     report_path="vi_correct_report.txt",
                     spelling: bool = True, add_diacritics: bool = False):
    """Trả về (markdown_đã_sửa, report). Gọi SAU repair_markdown() của math_repair.py."""
    lines = md.split("\n")
    units = []   # (line_idx, masked_piece)
    plan = {}    # line_idx -> (spans, [unit_ids])
    for i, ln in enumerate(lines):
        if len(ln.strip()) < min_len or _SKIP_LINE.match(ln) or not _HAS_VI.search(ln):
            continue
        masked, spans = _mask(ln)
        ids = []
        for piece in _split_long(masked):
            ids.append(len(units))
            units.append((i, piece))
        plan[i] = (spans, ids)
    if LIMIT:
        units_active = min(LIMIT, len(units))
    else:
        units_active = len(units)

    report = {"units": len(units), "processed": units_active, "units_changed": 0,
              "words_changed": 0, "words_rejected": 0, "dia_words": 0}
    if not units:
        return md, report
    log = []   # (loại, đoạn, chi tiết)
    fixed = [u[1] for u in units]        # mặc định giữ nguyên bản OCR
    changed = set()
    run = _get_pipe()

    # A) sửa chính tả từng chữ (model sinh lại cả đoạn, chỉ nhận chữ hợp lệ)
    if spelling:
        preds = run([u[1] for u in units[:units_active]], max_length=512, batch_size=batch_size)
        for k, ((_, src), p) in enumerate(zip(units[:units_active], preds)):
            new, acc, rej = _merge(src, p["generated_text"].strip())
            fixed[k] = new
            if acc:
                changed.add(k)
                report["words_changed"] += len(acc)
                log.append(("SỬA", src, "; ".join(f"{x}→{y}" for x, y in acc)))
            if rej:
                report["words_rejected"] += len(rej)
                log.append(("BỎ QUA", src, "; ".join(f"{x}→{y}" for x, y in rej)))

    # B) thêm dấu: bỏ dấu cả đoạn rồi để model thêm dấu lại theo ngữ cảnh
    if add_diacritics:
        bare = [" ".join(_strip_dia(t) for t in u[1].split()) for u in units[:units_active]]
        preds2 = run(bare, max_length=512, batch_size=batch_size)
        for k, p2 in enumerate(preds2):
            src = units[k][1]
            new, acc = _dia_merge(src, fixed[k], p2["generated_text"].strip())
            if acc:
                fixed[k] = new
                changed.add(k)
                report["dia_words"] += len(acc)
                log.append(("DẤU", src, "; ".join(f"{x}→{y}" for x, y in acc)))
    report["units_changed"] = len(changed)

    if report_path:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for kind, a, b in log:
                f.write(f"[{kind}]\n  câu : {a}\n  chữ : {b}\n\n")
        report["report_file"] = str(p)

    for i, (spans, ids) in plan.items():
        if not any(fixed[k] != units[k][1] for k in ids):
            continue                      # dòng không có chữ nào đổi -> giữ nguyên 100%
        text = " ".join(fixed[k] for k in ids) if len(ids) > 1 else fixed[ids[0]]
        lines[i] = _PH.sub(lambda m: spans[int(m.group(1))], text)
    return "\n".join(lines), report


def correct_query(q: str) -> str:
    """Sửa câu hỏi người dùng trước khi embed/retrieve."""
    return correct_markdown(q, min_len=1, report_path=None)[0]