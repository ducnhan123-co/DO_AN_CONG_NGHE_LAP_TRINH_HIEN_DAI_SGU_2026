"""Sửa lỗi dấu / chính tả tiếng Việt bằng nrl-ai/vn-spell-correction-small.

Model này là seq2seq (BARTpho-syllable, ~0.1B) chuyên SỬA CHÍNH TẢ + THÊM DẤU, không phải
embedding hay LLM hỏi đáp. Vì vậy nó chỉ nên dùng ở 2 chỗ:
  1) Lúc nạp tài liệu: làm sạch chữ OCR trước khi chunk/embed  -> correct_markdown()
  2) Lúc hỏi: sửa câu hỏi gõ không dấu / sai chính tả          -> correct_query()

An toàn cho tài liệu toán:
  - Công thức $...$ / $$...$$ được thay bằng placeholder rồi trả lại nguyên vẹn.
  - Nếu model làm mất placeholder, đổi số, hoặc sửa quá tay -> GIỮ NGUYÊN dòng gốc.
  - Bỏ qua dòng bảng / HTML / ảnh.
  - Tiền tố Markdown (##, -, +, số thứ tự) không đưa vào model; chỉ nhận sửa BÊN TRONG
    từng chữ — model đổi dấu câu / ngoặc / khoảng trắng / số chữ thì giữ nguyên chữ gốc.

Đo 2026-10-26 trên 36 dòng OCR thật của sách AAA (đáp án gõ tay): không sửa 94,70% ->
bmd1905/vietnamese-correction-v2 92,00% (sửa sai 14 chữ đúng), nrl-ai/vn-spell-correction-small
96,54% (0 chữ đúng bị sửa sai), 52 ms/dòng trên MPS.
"""
import re
from difflib import SequenceMatcher

MODEL_NAME = "nrl-ai/vn-spell-correction-small"
MAX_CHARS = 400          # model giới hạn 512 token -> cắt đoạn dài theo câu
MIN_SIMILARITY = 0.6     # sửa lệch quá nhiều so với gốc thì không tin

_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)
_SKIP_LINE = re.compile(r"^\s*(<|!\[|\||#\s*$)")
_HAS_VI = re.compile(r"[A-Za-zÀ-ỹ]")
_PH = re.compile(r"ZM(\d+)Z")
_NUM = re.compile(r"\d+")
_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|\\?[-+*]\s+|\(?\d+(?:\.\d+)*[.)]\s+|[a-zđ][.)]\s+|[IVX]+\.\s+)?)(.*)$", re.S)
_LETTERS = re.compile(r"[^\W\d_]+")

_pipe = None


def _get_pipe():
    """Trả về hàm run(texts, max_length, batch_size) -> [{'generated_text': ...}].

    Không dùng transformers.pipeline("text2text-generation") vì bản transformers
    mới đã bỏ task này; nạp thẳng AutoModelForSeq2SeqLM chạy được mọi phiên bản.
    """
    global _pipe
    if _pipe is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        device = ("cuda" if torch.cuda.is_available()
                  else "mps" if torch.backends.mps.is_available() else "cpu")
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


def _shape(word: str) -> str:
    """Bộ khung của 1 chữ: dấu câu/số giữ nguyên, mỗi cụm chữ cái -> kiểu hoa/thường."""
    return _LETTERS.sub(lambda m: "U" if len(m[0]) > 1 and m[0].isupper()
                        else "C" if m[0][0].isupper() else "l", word)


def _merge_words(src: str, out: str) -> str:
    """Chỉ nhận sửa TRONG từng chữ. Số chữ khác nhau (model gộp/tách/xoá chữ) -> giữ cả dòng gốc;
    chữ nào đổi dấu câu, ngoặc, hoa/thường -> giữ chữ gốc. Khoảng trắng luôn theo dòng gốc."""
    parts, words = re.split(r"(\s+)", src), out.split()
    if sum(1 for w in parts if w and not w.isspace()) != len(words):
        return src
    it = iter(words)
    return "".join(w if not w or w.isspace() else
                   (o if _shape(o := next(it)) == _shape(w) else w) for w in parts)


def _accept(src: str, out: str) -> bool:
    if _PH.findall(src) != _PH.findall(out):          # mất / đảo placeholder công thức
        return False
    if sorted(_NUM.findall(src)) != sorted(_NUM.findall(out)):   # đổi số (Bài 52, 1970...)
        return False
    return SequenceMatcher(None, src, out).ratio() >= MIN_SIMILARITY


def correct_markdown(md: str, batch_size: int = 16, min_len: int = 15,
                     report_path: str = "vi_correct_report.txt"):
    """Trả về (markdown_đã_sửa, report). Gọi SAU repair_markdown() của math_repair.py."""
    lines = md.split("\n")
    units = []   # (line_idx, masked_piece)
    plan = {}    # line_idx -> (spans, [unit_ids])
    for i, ln in enumerate(lines):
        if len(ln.strip()) < min_len or _SKIP_LINE.match(ln) or not _HAS_VI.search(ln):
            continue
        prefix, body = _PREFIX.match(ln).groups()
        masked, spans = _mask(body)
        ids = []
        for piece in _split_long(masked):
            ids.append(len(units))
            units.append((i, piece))
        plan[i] = (prefix, spans, ids)

    report = {"units": len(units), "changed": 0, "format_only": 0, "rejected": 0}
    if not units:
        return md, report
    log = []   # (loại, trước, sau)

    preds = _get_pipe()([u[1] for u in units], max_length=512, batch_size=batch_size)
    fixed = []
    for (_, src), p in zip(units, preds):
        out = _merge_words(src, p["generated_text"].strip())
        if _accept(src, out):
            fixed.append(out)
            if out != src:
                # chỉ khác khoảng trắng/dấu câu -> không tính là sửa lỗi thật
                if " ".join(out.split()) == " ".join(src.split()):
                    report["format_only"] += 1
                else:
                    report["changed"] += 1
                    log.append(("SỬA", src, out))
        else:
            fixed.append(src)
            report["rejected"] += 1
            log.append(("TỪ CHỐI", src, out))

    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            for kind, a, b in log:
                f.write(f"[{kind}]\n  trước: {a}\n  sau  : {b}\n\n")
        report["report_file"] = report_path

    for i, (prefix, spans, ids) in plan.items():
        text = " ".join(fixed[k] for k in ids) if len(ids) > 1 else fixed[ids[0]]
        lines[i] = prefix + _PH.sub(lambda m: spans[int(m.group(1))], text)
    return "\n".join(lines), report


def correct_query(q: str) -> str:
    """Sửa câu hỏi người dùng trước khi embed/retrieve."""
    return correct_markdown(q, min_len=1)[0]