"""Chunk theo BLOCK: formula/table là đơn vị không chia; text dài chỉ cắt ở ranh giới câu
và không bao giờ cắt khi đang mở công thức $...$ / $$...$$ / \\[...\\] / \\(...\\)."""
import re
from itertools import groupby
from typing import Dict, List

ATOMIC = {"formula", "table", "code"}


def math_balanced(s: str) -> bool:
    if s.count("$$") % 2:
        return False
    rest = s.replace("$$", "")
    if len(re.findall(r"(?<!\\)\$", rest)) % 2:
        return False
    return s.count("\\[") == s.count("\\]") and s.count("\\(") == s.count("\\)")


def split_text_safe(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    tokens = [t for t in re.findall(r".*?(?:[.!?;:]\s+|\n+|\Z)", text, flags=re.S) if t]
    pieces, cur = [], ""
    for tok in tokens:
        cand = cur + tok
        if not cur or len(cand) <= max_chars or not math_balanced(cur):
            cur = cand          # còn chỗ, hoặc đang mở công thức -> phải gộp tiếp
        else:
            pieces.append(cur.strip())
            cur = tok
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def _render(b: Dict) -> str:
    if b["content_type"] == "formula" and b.get("formula_latex"):
        return f"$$\n{b['formula_latex']}\n$$"
    return b["text"]


def _make_chunk(cid: int, section: str, units: List[Dict]) -> Dict:
    blocks = [u["block"] for u in units]
    pages = sorted({b["page"] for b in blocks if b["page"] is not None})
    formulas = [b["formula_latex"] for b in blocks
                if b["content_type"] == "formula" and b.get("formula_latex")]
    text = f"# {section}\n" + "\n\n".join(u["text"] for u in units)
    return {
        "chunk_id": cid, "doc_id": blocks[0]["doc_id"], "source": blocks[0]["source"],
        "section": section, "page": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None, "pages": pages,
        "content_types": sorted({b["content_type"] for b in blocks}),
        "has_formula": bool(formulas), "formula_latex": formulas,
        "block_ids": sorted({b["block_id"] for b in blocks}),
        "n_chars": len(text), "text": text,
    }


def build_chunks(blocks: List[Dict], max_chars: int = 1800, overlap: int = 250) -> List[Dict]:
    chunks: List[Dict] = []
    for section, grp in groupby(blocks, key=lambda b: b["section"]):
        prefix_len = len(f"# {section}\n")
        budget = max(200, max_chars - prefix_len)
        units: List[Dict] = []
        for b in grp:
            if b["content_type"] == "heading" or not (b["text"] or "").strip():
                continue
            if b["content_type"] in ATOMIC:
                units.append({"block": b, "text": _render(b)})
            else:
                for piece in split_text_safe(b["text"], budget):
                    units.append({"block": b, "text": piece})

        cur: List[Dict] = []
        cur_len, new_count = 0, 0

        def flush():
            nonlocal cur, cur_len, new_count
            if cur and new_count > 0:
                chunks.append(_make_chunk(len(chunks), section, cur))
            last = cur[-1] if cur else None
            cur, cur_len, new_count = [], 0, 0
            # overlap: mang đoạn text cuối (nếu ngắn) sang chunk kế; không mang formula/table
            if (last is not None and last["block"]["content_type"] in ("text", "list")
                    and len(last["text"]) <= overlap):
                cur, cur_len = [last], len(last["text"]) + 2

        for u in units:
            add = len(u["text"]) + 2
            if new_count > 0 and cur_len + add > budget:
                flush()
            cur.append(u)
            cur_len += add
            new_count += 1
        if new_count > 0:
            chunks.append(_make_chunk(len(chunks), section, cur))
    return chunks
