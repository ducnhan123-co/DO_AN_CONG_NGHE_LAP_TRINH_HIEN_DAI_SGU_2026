"""RAG tùy chọn (bước 4 của main.py): dựng/tải LlamaIndex (E5) và truy vấn retrieval cho 1 tài liệu.

Mặc định TẮT (RAG_INDEX=0) vì cần torch + model embedding (~1 GB). Bật bằng RAG_INDEX=1 và cài requirements-rag.txt.
Chưa có bước LLM (Qwen) ở đây: trả về các đoạn truy xuất kèm score/page/section — frontend hiện tại chưa có màn hỏi đáp.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Dict, List

from ..core.config import Settings
from ..core.errors import AppError
from .engine import Engine
from .storage import Storage

_build_lock = threading.Lock()            # dựng index nặng RAM: mỗi lúc một tài liệu
_cache: "OrderedDict[str, object]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 3


class RagService:
    def __init__(self, settings: Settings, storage: Storage, engine: Engine):
        self.s, self.storage, self.engine = settings, storage, engine

    def _index_dir(self, doc_id: str):
        return self.storage.run_dir(doc_id) / "index"

    def build_index(self, doc_id: str, chunks: List[Dict]) -> None:
        E = self.engine.load()
        from src.llama_rag import build_index, chunks_to_nodes
        with _build_lock:
            nodes = chunks_to_nodes(chunks)
            build_index(nodes, E.cfg.EMBED_MODEL, self._index_dir(doc_id))
        with _cache_lock:
            _cache.pop(doc_id, None)

    def search(self, doc_id: str, query: str, top_k: int | None = None) -> List[Dict]:
        if not self.s.rag_index:
            raise AppError(501, "RAG_DISABLED", "Tính năng tìm kiếm RAG đang tắt (đặt RAG_INDEX=1 và cài requirements-rag.txt).")
        E = self.engine.load()
        idx_dir = self._index_dir(doc_id)
        if not idx_dir.is_dir():
            raise AppError(409, "INDEX_NOT_READY", "Tài liệu này chưa có index RAG.")
        from src.llama_rag import load_index, retrieve
        with _cache_lock:
            index = _cache.get(doc_id)
            if index is not None:
                _cache.move_to_end(doc_id)
        if index is None:
            index = load_index(idx_dir, E.cfg.EMBED_MODEL)
            with _cache_lock:
                _cache[doc_id] = index
                while len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
        return retrieve(index, query, top_k or E.cfg.TOP_K)
