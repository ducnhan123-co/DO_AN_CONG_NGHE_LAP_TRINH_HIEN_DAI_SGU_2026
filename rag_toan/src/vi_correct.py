"""Sửa lỗi dấu / chính tả tiếng Việt bằng bmd1905/vietnamese-correction-v2.

Model này là seq2seq (mBART, ~0.4B) chuyên SỬA CHÍNH TẢ + THÊM DẤU, không phải
embedding hay LLM hỏi đáp. Vì vậy nó chỉ nên dùng ở 2 chỗ:
  1) Lúc nạp tài liệu: làm sạch chữ OCR trước khi chunk/embed  -> correct_markdown()
  2) Lúc hỏi: sửa câu hỏi gõ không dấu / sai chính tả          -> correct_query()

An toàn cho tài liệu toán:
  - Công thức $...$ / $$...$$ được thay bằng placeholder rồi trả lại nguyên vẹn.
  - Nếu model làm mất placeholder, đổi số, hoặc sửa quá tay -> GIỮ NGUYÊN dòng gốc.
  - Bỏ qua dòng bảng / HTML / ảnh.
"""
import re
from difflib import SequenceMatcher

MODEL_NAME = "bmd1905/vietnamese-correction-v2"
MAX_CHARS = 400          # model giới hạn 512 token -> cắt đoạn dài theo câu
MIN_SIMILARITY = 0.6     # sửa lệch quá nhiều so với gốc thì không tin

_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)
_SKIP_LINE = re.compile(r"^\s*(<|!\[|\||#\s*$)")
_HAS_VI = re.compile(r"[A-Za-zÀ-ỹ]")
_PH = re.compile(r"ZM(\d+)Z")
_NUM = re.compile(r"\d+")

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

        device = "cuda" if torch.cuda.is_available() else "cpu"
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
        masked, spans = _mask(ln)
        ids = []
        for piece in _split_long(masked):
            ids.append(len(units))
            units.append((i, piece))
        plan[i] = (spans, ids)

    report = {"units": len(units), "changed": 0, "format_only": 0, "rejected": 0}
    if not units:
        return md, report
    log = []   # (loại, trước, sau)

    preds = _get_pipe()([u[1] for u in units], max_length=512, batch_size=batch_size)
    fixed = []
    for (_, src), p in zip(units, preds):
        out = p["generated_text"].strip()
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

    for i, (spans, ids) in plan.items():
        text = " ".join(fixed[k] for k in ids) if len(ids) > 1 else fixed[ids[0]]
        lines[i] = _PH.sub(lambda m: spans[int(m.group(1))], text)
    return "\n".join(lines), report


def correct_query(q: str) -> str:
    """Sửa câu hỏi người dùng trước khi embed/retrieve."""
    return correct_markdown(q, min_len=1)[0]