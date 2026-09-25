"""Kiểm tra DoD của Preprocessing: không base64, không cắt đôi công thức, có source/page."""
import re
from typing import Dict, List, Optional

from .chunking import math_balanced

B64 = re.compile(r"data:image/|;base64,")


def validate_chunks(chunks: List[Dict], expected_source: Optional[str] = None,
                    expected_doc_id: Optional[str] = None) -> Dict:
    problems: List[str] = []
    no_page = 0
    for c in chunks:
        cid = c["chunk_id"]
        if B64.search(c["text"]):
            problems.append(f"chunk {cid}: chứa base64/data:image")
        if not math_balanced(c["text"]):
            problems.append(f"chunk {cid}: công thức bị cắt đôi (delimiter lẻ)")
        if not c.get("source"):
            problems.append(f"chunk {cid}: thiếu source")
        if expected_source and c["source"] != expected_source:
            problems.append(f"chunk {cid}: source {c['source']} != {expected_source}")
        if expected_doc_id and c["doc_id"] != expected_doc_id:
            problems.append(f"chunk {cid}: doc_id lẫn dữ liệu doc khác")
        if c.get("page") is None:
            no_page += 1
    return {"n_chunks": len(chunks), "n_without_page": no_page,
            "n_with_formula": sum(1 for c in chunks if c["has_formula"]),
            "ok": not problems, "problems": problems}
