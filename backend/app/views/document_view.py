"""View: biến thực thể (Model) thành JSON mà frontend/app.js, index.html, reader.html đọc.

Các trường dưới đây đối chiếu từng cái với những chỗ frontend dùng `d.xxx` (xem docs trong README).
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from ..models.entities import ACTIVE_STATUSES, Document, LibraryEntry

_SHARD_KEYS = ("index", "page_from", "page_to", "status", "progress", "elapsed_s", "peak_ram_gb", "error")


def _elapsed(doc: Document, now: float) -> Optional[float]:
    if doc.started_at is None:
        return 0.0 if doc.status in ACTIVE_STATUSES else None
    end = now if doc.status in ACTIVE_STATUSES else (doc.finished_at or doc.updated_at)
    return round(max(0.0, end - doc.started_at), 1)


def render_document(doc: Document, entry: LibraryEntry, docx_available: bool, now: Optional[float] = None) -> Dict:
    now = now or time.time()
    error = {"code": doc.error_code or "ERROR", "message": doc.error_message or ""} \
        if doc.status == "failed" else None
    return {
        "id": doc.id,
        "name": entry.display_name,
        "filename": entry.filename,
        "num_pages": doc.num_pages,
        "size_bytes": doc.size_bytes,
        "status": doc.status,
        "progress": float(doc.progress or 0.0),
        "error": error,
        "docx_available": bool(docx_available and doc.status == "done"),
        "docx_size": doc.docx_size,
        "elapsed_s": _elapsed(doc, now),
        "cache_hit": entry.cache_hit,
        "tier": doc.tier,
        "created_at": entry.created_at,
        "shards": [{k: sh.get(k) for k in _SHARD_KEYS} for sh in doc.shards],
        "stages": doc.stages,
        "rag": {"ok": doc.rag_ok, "note": doc.rag_note},
    }


def render_list(pairs: List[Tuple[Document, LibraryEntry]], docx_exists) -> Dict:
    now = time.time()
    items = [render_document(d, e, docx_exists(d.id), now) for d, e in pairs]
    return {"items": items, "total": len(items)}
