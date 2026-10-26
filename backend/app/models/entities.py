"""Thực thể (Model): Document = kết quả xử lý của 1 PDF; LibraryEntry = mục trong thư viện của 1 người dùng."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Trạng thái — trùng với bảng nhãn LABEL / ACTIVE trong frontend/app.js
QUEUED, PARSING, MERGING, PREPARING, BUILDING, VALIDATING = (
    "queued", "parsing", "merging", "preparing", "building", "validating")
DONE, FAILED, CANCELLED = "done", "failed", "cancelled"

ACTIVE_STATUSES = (QUEUED, PARSING, MERGING, PREPARING, BUILDING, VALIDATING)
RUNNING_STATUSES = (PARSING, MERGING, PREPARING, BUILDING, VALIDATING)   # đã có worker nhận
TERMINAL_STATUSES = (DONE, FAILED, CANCELLED)


@dataclass
class Document:
    id: str
    sha256: str
    filename: str
    size_bytes: int
    num_pages: int
    status: str = QUEUED
    progress: float = 0.0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    tier: Optional[str] = None
    shards: List[Dict[str, Any]] = field(default_factory=list)
    stages: List[Dict[str, Any]] = field(default_factory=list)
    docx_size: Optional[int] = None
    queued_at: Optional[float] = None
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    updated_at: float = 0.0
    rag_ok: Optional[bool] = None
    rag_note: Optional[str] = None
    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @classmethod
    def from_row(cls, row) -> "Document":
        d = dict(row)
        d["shards"] = json.loads(d.get("shards") or "[]")
        d["stages"] = json.loads(d.get("stages") or "[]")
        if d.get("rag_ok") is not None:
            d["rag_ok"] = bool(d["rag_ok"])
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class LibraryEntry:
    client_id: str
    doc_id: str
    display_name: str
    filename: str
    cache_hit: bool
    created_at: float

    @classmethod
    def from_row(cls, row) -> "LibraryEntry":
        return cls(client_id=row["client_id"], doc_id=row["doc_id"], display_name=row["display_name"],
                   filename=row["filename"], cache_hit=bool(row["cache_hit"]), created_at=row["created_at"])
