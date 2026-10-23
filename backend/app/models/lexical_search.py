"""CPU-only BM25 retrieval over MinerU structured chunks; no E5 or generative LLM.

Keyword retrieval is NOT semantic vector search: synonyms without shared tokens
may be missed. Keep original chunks, page metadata, formulas and citations.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
STOP = {"là", "gì", "của", "cho", "về", "hãy", "có", "không", "trong",
        "nào", "những", "các", "và", "được", "ở", "một", "trang", "bao", "nhiêu"}


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.casefold()) if t not in STOP]


def search_chunks(path: Path, query: str, top_k: int = 5) -> list[dict]:
    """Return hits with the same page/section/text/score keys as former retriever."""
    if not path.is_file():
        return []
    chunks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(chunks, list) or not chunks:
        return []
    terms = set(tokens(query))
    if not terms:
        return []
    documents = [Counter(tokens(c.get("text") or "")) for c in chunks]
    avg_len = max(sum(sum(d.values()) for d in documents) / len(documents), 1.0)
    doc_freq = Counter(term for d in documents for term in d)
    scored = []
    for idx, (chunk, freq) in enumerate(zip(chunks, documents)):
        length = sum(freq.values())
        score = 0.0
        for term in terms:
            tf = freq.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(chunks) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / avg_len))
        if score > 0:
            scored.append((score, idx, chunk))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{
        "node_id": f"{c.get('doc_id', '')}-{c.get('chunk_id', i)}",
        "score": round(score, 6),
        "source": c.get("source"),
        "page": c.get("page"),
        "page_end": c.get("page_end"),
        "pages": c.get("pages") or [],
        "section": c.get("section"),
        "formula_latex": c.get("formula_latex"),
        "text": c.get("text", ""),
    } for score, i, c in scored[:max(1, top_k)]]
