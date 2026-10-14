"""DEPRECATED kể từ Tuần 2.

File này là bản gốc (chunk theo max_chars, không lọc base64, dùng FAISS thủ công).
Nó có 3 lỗi đã ghi trong Weekly_Sprint_02.xlsx:
  1) reuse nhầm dữ liệu cũ giữa các lần chạy MinerU
  2) base64 ảnh lọt vào chunk text
  3) công thức toán bị cắt đôi khi chunk theo max_chars

Pipeline mới thay thế hoàn toàn 3 module: structured.py + chunking.py + llama_rag.py
(được main.py dùng). File này CHỈ giữ lại để đối chiếu / báo cáo "trước - sau",
không import từ đây nữa trong code mới.
"""
import json
import re
from pathlib import Path

import numpy as np


def split_markdown_sections(md: str):
    sections, heading, buf = [], "Document", []
    for line in md.splitlines():
        if re.match(r"^#{1,6}\s+", line):
            body = "\n".join(buf).strip()
            if body:
                sections.append({"heading": heading, "text": body})
            buf = []
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
        else:
            buf.append(line)
    body = "\n".join(buf).strip()
    if body:
        sections.append({"heading": heading, "text": body})
    return sections


def make_chunks(sections, max_chars: int = 1800, overlap: int = 250):
    chunks = []
    for sec_id, sec in enumerate(sections):
        heading, body = sec["heading"], sec["text"]
        if len(body) <= max_chars:
            chunks.append({
                "chunk_id": len(chunks), "section_id": sec_id,
                "heading": heading, "text": f"# {heading}\n{body}".strip(),
            })
            continue
        start = 0
        while start < len(body):
            end = min(start + max_chars, len(body))
            chunks.append({
                "chunk_id": len(chunks), "section_id": sec_id,
                "heading": heading,
                "text": f"# {heading}\n{body[start:end]}".strip(),
            })
            if end >= len(body):
                break
            start = max(0, end - overlap)
    return chunks


def build_index(chunks, embed_model: str, rag_dir: Path):
    from sentence_transformers import SentenceTransformer
    import faiss

    embedder = SentenceTransformer(embed_model)
    passages = ["passage: " + c["text"] for c in chunks]
    embeddings = np.asarray(
        embedder.encode(passages, normalize_embeddings=True,
                        show_progress_bar=True),
        dtype="float32",
    )
    print("Embedding shape:", embeddings.shape)
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    index_path = rag_dir / "index.faiss"
    chunks_path = rag_dir / "chunks.json"
    faiss.write_index(index, str(index_path))
    chunks_path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Index:", index_path)
    print("Chunks:", chunks_path)
    return index, embedder, index_path, chunks_path


def retrieve(query: str, embedder, index, chunks, top_k: int = 5):
    q = embedder.encode(["query: " + query],
                        normalize_embeddings=True).astype("float32")
    scores, ids = index.search(q, top_k)
    out = []
    for score, idx in zip(scores[0], ids[0]):
        if idx < 0:
            continue
        item = dict(chunks[int(idx)])
        item["score"] = float(score)
        out.append(item)
    return out
