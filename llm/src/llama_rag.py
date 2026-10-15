"""Chunks -> LlamaIndex TextNode -> VectorStoreIndex (E5) -> retriever (score + source/page)."""
import threading
from pathlib import Path
from typing import Dict, List

META_KEYS = ["chunk_id", "doc_id", "source", "section", "page", "page_end", "pages",
             "content_types", "has_formula", "formula_latex", "block_ids", "n_chars"]

# Singleton: E5 ~1GB, load 10-30s trên CPU — nạp 1 lần, dùng lại cho mọi
# build_index / load_index / retrieve trong process này.
_embed_cache: Dict[str, object] = {}
_embed_lock = threading.Lock()


def get_embed_model(name: str):
    with _embed_lock:
        if name in _embed_cache:
            return _embed_cache[name]
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    # E5 bắt buộc prefix; nếu thiếu retrieval sẽ tụt chất lượng
    model = HuggingFaceEmbedding(model_name=name, query_instruction="query: ",
                                 text_instruction="passage: ")
    with _embed_lock:
        _embed_cache.setdefault(name, model)
        return _embed_cache[name]


def chunks_to_nodes(chunks: List[Dict]):
    from llama_index.core.schema import TextNode
    nodes = []
    for c in chunks:
        meta = {k: c[k] for k in META_KEYS if k in c}
        node = TextNode(id_=f"{c['doc_id']}-{c['chunk_id']:04d}",  # ID ổn định cho DB/BE
                        text=c["text"], metadata=meta)
        node.excluded_embed_metadata_keys = list(meta.keys())   # chỉ embed nội dung
        node.excluded_llm_metadata_keys = ["block_ids", "doc_id", "chunk_id", "n_chars"]
        nodes.append(node)
    return nodes


def build_index(nodes, embed_model_name: str, persist_dir: Path):
    from llama_index.core import VectorStoreIndex
    index = VectorStoreIndex(nodes, embed_model=get_embed_model(embed_model_name),
                             show_progress=True)
    persist_dir.mkdir(parents=True, exist_ok=True)
    index.storage_context.persist(persist_dir=str(persist_dir))
    print("Index persisted:", persist_dir)
    return index


def load_index(persist_dir: Path, embed_model_name: str):
    from llama_index.core import StorageContext, load_index_from_storage
    sc = StorageContext.from_defaults(persist_dir=str(persist_dir))
    return load_index_from_storage(sc, embed_model=get_embed_model(embed_model_name))


def retrieve(index, query: str, top_k: int = 5) -> List[Dict]:
    hits = index.as_retriever(similarity_top_k=top_k).retrieve(query)
    return [{"node_id": h.node.node_id, "score": float(h.score or 0.0),
             "source": h.node.metadata.get("source"), "page": h.node.metadata.get("page"),
             "section": h.node.metadata.get("section"),
             "formula_latex": h.node.metadata.get("formula_latex"),
             "text": h.node.get_content()} for h in hits]
