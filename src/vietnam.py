"""Sửa dấu tiếng Việt theo NGỮ CẢNH, miễn phí, chạy trên máy (nrl-ai/vn-diacritic-vit5-base).

Cách làm: bỏ hết dấu của từng đoạn -> model thêm dấu lại theo ngữ cảnh cả câu ->
so từng chữ với bản OCR. Model chỉ ~90-99% đúng nên KHÔNG tin tuyệt đối: mỗi chữ khác
bản OCR phải qua bước kiểm chứng, tức là câu có chữ mới phải được chính model chấm
"hợp lý hơn" câu OCR gốc ít nhất MARGIN (log-xác suất) thì mới nhận.

Chỉ sửa được lỗi DẤU (nên/nền, tôn/tồn, ngũ/ngữ...). Lỗi chữ cái (thiếu "h" trong
"nghìn", nhầm ê/ơ thành chữ khác hẳn) thì không sửa được.

An toàn: công thức $...$ bằng placeholder; chữ số, ký hiệu Markdown đầu dòng, bảng/HTML/ảnh
không bị đụng; chữ nào model đổi cả chữ cái thì bỏ.

Dùng được cho cả 2 bản main.py:
  - Cách 2: đặt file này là src/vietnam.py, chạy  --correct-vietnamese
  - Cách 3: đổi tên thành src/vi_correct.py,       chạy  --vi-correct

Biến môi trường (tuỳ chọn, PowerShell: $env:TÊN = "giá trị"):
  VI_MARGIN   ngưỡng chấp nhận, mặc định 1.0. Thấp = sửa nhiều hơn nhưng rủi ro hơn.
  VI_BATCH    kích thước lô, mặc định 16.
  VI_LIMIT    chỉ xử lý N đoạn đầu để chạy thử.
  VI_CACHE    file cache kết quả model, mặc định vi_diacritic_cache.jsonl.
"""
import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path

MODEL_NAME = os.environ.get("VI_DIACRITIC_MODEL", "nrl-ai/vn-diacritic-vit5-base")
MARGIN = float(os.environ.get("VI_MARGIN", "1.0"))
BATCH = int(os.environ.get("VI_BATCH", "16"))
LIMIT = int(os.environ.get("VI_LIMIT", "0") or 0)
CACHE_PATH = Path(os.environ.get("VI_CACHE", "vi_diacritic_cache.jsonl"))
MAX_CHARS = 300      # model nhận tối đa 256 sub-word -> cắt đoạn dài theo câu
MAX_DIFFS = 12       # mỗi đoạn kiểm chứng tối đa ngần này chữ khác biệt

_MATH = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+?\$)", re.S)
_SKIP_LINE = re.compile(r"^\s*(<|!\[|\||#\s*$)")
_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)?)(.*)$", re.S)
_WORD = re.compile(r"[A-Za-zÀ-ỹ]{2,}")
_PH = re.compile(r"ZM(\d+)Z")

_model = None


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def strip_diacritics(s: str) -> str:
    s = _nfc(s).replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", s)


# --------------------------------------------------------------------------- model
def _get_model():
    global _model
    if _model is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[vi-diacritic] tải model {MODEL_NAME} (thiết bị: {dev})")
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        mdl = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).to(dev).eval()
        _model = (torch, tok, mdl, dev)
    return _model


def _generate(texts):
    torch, tok, mdl, dev = _get_model()
    enc = tok(texts, return_tensors="pt", padding=True, truncation=True,
              max_length=256).to(dev)
    with torch.inference_mode():
        gen = mdl.generate(**enc, max_length=256)
    return [t.strip() for t in tok.batch_decode(
        gen, skip_special_tokens=True, clean_up_tokenization_spaces=False)]


def _score(srcs, tgts):
    """Tổng log-xác suất model gán cho mỗi tgts[i] khi đầu vào là srcs[i]."""
    torch, tok, mdl, dev = _get_model()
    enc = tok(srcs, return_tensors="pt", padding=True, truncation=True,
              max_length=256).to(dev)
    lab = tok(text_target=tgts, return_tensors="pt", padding=True, truncation=True,
              max_length=256).input_ids.to(dev)
    mask = lab != tok.pad_token_id
    lab_in = lab.clone()
    lab_in[~mask] = -100
    with torch.inference_mode():
        logits = mdl(**enc, labels=lab_in).logits
        lp = torch.log_softmax(logits.float(), dim=-1).gather(-1, lab.unsqueeze(-1)).squeeze(-1)
    return (lp * mask).sum(-1).tolist()


def _score_all(pairs):
    out = [0.0] * len(pairs)
    order = sorted(range(len(pairs)), key=lambda k: len(pairs[k][0]) + len(pairs[k][1]))
    n = max(1, BATCH * 2)
    for s in range(0, len(order), n):
        ids = order[s:s + n]
        res = _score([pairs[k][0] for k in ids], [pairs[k][1] for k in ids])
        for k, v in zip(ids, res):
            out[k] = v
        print(f"[vi-diacritic] kiểm chứng {min(s + n, len(order))}/{len(order)}",
              end="\r", flush=True)
    if pairs:
        print()
    return out


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


def _mask(text: str):
    spans = []

    def rep(m):
        spans.append(m.group(0))
        return f"ZM{len(spans) - 1}Z"

    return _MATH.sub(rep, text), spans


def _prep(piece: str):
    s = _nfc(piece)
    letters = [c for c in s if c.isalpha()]
    # Tiêu đề IN HOA: đưa về chữ thường cho model (dữ liệu huấn luyện là chữ thường/hoa đầu câu)
    upper = bool(letters) and s == s.upper() and s.lower().upper() == s
    work = s.lower() if upper else s
    parts = re.split(r"(\s+)", work)
    idx = [k for k, p in enumerate(parts) if p and not p.isspace()]
    toks = [parts[k] for k in idx]
    if len(toks) < 2:
        return None
    return {"orig": piece, "upper": upper, "parts": parts, "idx": idx, "toks": toks,
            "src": " ".join(strip_diacritics(t) for t in toks)}


def _finish(info, accepted):
    parts = list(info["parts"])
    for k, new in accepted.items():
        parts[info["idx"][k]] = new
    out = "".join(parts)
    return out.upper() if info["upper"] else out


def _ckey(src: str) -> str:
    return hashlib.sha1(f"{MODEL_NAME}\n{src}".encode("utf-8")).hexdigest()


def _load_cache():
    cache = {}
    if CACHE_PATH.exists():
        for ln in CACHE_PATH.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
                cache[d["k"]] = d["v"]
            except Exception:
                pass
    return cache


# --------------------------------------------------------------------------- chính
def correct_markdown(md: str, model_name=None, max_new_tokens=None,
                     report_path="vi_correct_report.txt", min_len: int = 15):
    """Trả về (markdown_đã_sửa, report). Gọi SAU repair_markdown().

    model_name / max_new_tokens chỉ để tương thích với main.py Cách 2, bị bỏ qua
    (đổi model bằng biến môi trường VI_DIACRITIC_MODEL).
    """
    lines = md.split("\n")
    pieces = []        # thông tin từng đoạn gửi cho model
    line_info = {}     # line_idx -> (prefix, spans, segs); seg = id đoạn (int) hoặc chuỗi giữ nguyên
    for i, ln in enumerate(lines):
        if len(ln.strip()) < min_len or _SKIP_LINE.match(ln):
            continue
        prefix, body = _PREFIX.match(ln).groups()
        masked, spans = _mask(body)
        if not _WORD.search(_PH.sub("", masked)):
            continue
        segs = []
        for piece in _split_long(masked):
            info = _prep(piece)
            if info is None:
                segs.append(piece)
            else:
                segs.append(len(pieces))
                pieces.append(info)
        if any(isinstance(s, int) for s in segs):
            line_info[i] = (prefix, spans, segs)

    active = range(min(LIMIT, len(pieces)) if LIMIT else len(pieces))
    report = {"pieces": len(pieces), "processed": len(active), "unchanged": 0,
              "skipped_mismatch": 0, "pieces_changed": 0, "words_changed": 0,
              "near_threshold": 0, "margin": MARGIN}
    if not pieces:
        return md, report

    # 1) model thêm dấu lại (có cache theo nội dung đã bỏ dấu)
    cache = _load_cache()
    todo = sorted({pieces[p]["src"] for p in active if _ckey(pieces[p]["src"]) not in cache},
                  key=len)
    for s in range(0, len(todo), BATCH):
        batch = todo[s:s + BATCH]
        res = _generate(batch)
        with CACHE_PATH.open("a", encoding="utf-8") as cf:
            for src, out in zip(batch, res):
                cache[_ckey(src)] = out
                cf.write(json.dumps({"k": _ckey(src), "v": out}, ensure_ascii=False) + "\n")
        print(f"[vi-diacritic] thêm dấu {min(s + BATCH, len(todo))}/{len(todo)}",
              end="\r", flush=True)
    if todo:
        print()

    # 2) tìm chữ khác biệt, dựng câu ứng viên
    cand_info = {}     # pid -> (diffs, rtoks)
    pairs, owners = [], []     # (src, tgt) cần chấm; owners[j] = (pid, kind, ks)
    for pid in active:
        info = pieces[pid]
        rtoks = [_nfc(t) for t in cache[_ckey(info["src"])].split()]
        toks = info["toks"]
        if len(rtoks) != len(toks):
            report["skipped_mismatch"] += 1
            continue
        diffs = [k for k, (a, b) in enumerate(zip(toks, rtoks))
                 if a != b and strip_diacritics(a) == strip_diacritics(b)][:MAX_DIFFS]
        if not diffs:
            report["unchanged"] += 1
            continue
        cand_info[pid] = (diffs, rtoks)
        pairs.append((info["src"], " ".join(toks)))
        owners.append((pid, "base", ()))
        for k in diffs:
            t = list(toks)
            t[k] = rtoks[k]
            pairs.append((info["src"], " ".join(t)))
            owners.append((pid, "one", (k,)))
        for k in diffs:
            if k + 1 in diffs:
                t = list(toks)
                t[k], t[k + 1] = rtoks[k], rtoks[k + 1]
                pairs.append((info["src"], " ".join(t)))
                owners.append((pid, "pair", (k, k + 1)))

    # 3) kiểm chứng: chỉ nhận thay đổi nếu model chấm câu mới hơn câu OCR >= MARGIN
    scores = _score_all(pairs)
    base, gains = {}, {}
    for (pid, kind, ks), sc in zip(owners, scores):
        if kind == "base":
            base[pid] = sc
    for (pid, kind, ks), sc in zip(owners, scores):
        if kind != "base":
            gains[(pid, ks)] = sc - base[pid]

    log, final = [], {}
    for pid, (diffs, rtoks) in cand_info.items():
        info, toks = pieces[pid], pieces[pid]["toks"]
        acc = {k for k in diffs if gains[(pid, (k,))] > MARGIN}
        for k in diffs:
            if k + 1 in diffs and k not in acc and k + 1 not in acc \
                    and gains[(pid, (k, k + 1))] > MARGIN:
                acc |= {k, k + 1}
        near = [k for k in diffs if k not in acc and 0 < gains[(pid, (k,))] <= MARGIN]
        if near:
            report["near_threshold"] += len(near)
            log.append(("GẦN NGƯỠNG", " ".join(toks),
                        "; ".join(f"{toks[k]}→{rtoks[k]} ({gains[(pid, (k,))]:+.1f})"
                                  for k in near)))
        if not acc:
            report["unchanged"] += 1
            continue
        new = _finish(info, {k: rtoks[k] for k in acc})
        final[pid] = new
        report["pieces_changed"] += 1
        report["words_changed"] += len(acc)
        detail = "; ".join(
            f"{toks[k]}→{rtoks[k]} ({gains.get((pid, (k,)), gains.get((pid, (k - 1, k)), 0)):+.1f})"
            for k in sorted(acc))
        log.append(("SỬA", " ".join(toks), detail))

    # 4) ghép lại, chỉ đụng tới dòng thật sự có sửa
    for i, (prefix, spans, segs) in line_info.items():
        if not any(isinstance(s, int) and s in final for s in segs):
            continue
        texts = [(final[x] if x in final else pieces[x]["orig"]) if isinstance(x, int) else x
                 for x in segs]
        body = " ".join(texts) if len(texts) > 1 else texts[0]
        lines[i] = prefix + _PH.sub(lambda m: spans[int(m.group(1))], body)

    if report_path:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for kind, a, b in log:
                f.write(f"[{kind}]\n  câu : {a}\n  chữ : {b}\n\n")
        report["report_file"] = str(p)
    print("[vi-diacritic]", report)
    return "\n".join(lines), report


def correct_query(q: str) -> str:
    """Sửa dấu câu hỏi người dùng trước khi embed/retrieve."""
    return correct_markdown(q, min_len=1, report_path=None)[0]