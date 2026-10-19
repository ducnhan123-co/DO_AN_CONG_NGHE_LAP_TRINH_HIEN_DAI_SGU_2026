"""SQLite (data/app.db): kết nối ngắn theo từng thao tác, chế độ WAL để vừa ghi tiến độ vừa đọc.

Hai bảng chính:
  documents : 1 dòng cho mỗi NỘI DUNG PDF (id = hash nội dung, như doc_id của rag_toan)
  library   : mỗi trình duyệt (X-Client-Id) có thư viện riêng trỏ tới documents (đổi tên/xóa không ảnh hưởng người khác)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

DOCUMENT_COLUMNS = {
    "id", "sha256", "filename", "size_bytes", "num_pages", "status", "progress", "error_code",
    "error_message", "tier", "shards", "stages", "docx_size", "queued_at", "created_at",
    "started_at", "finished_at", "updated_at", "rag_ok", "rag_note",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    sha256        TEXT NOT NULL,
    filename      TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    num_pages     INTEGER NOT NULL,
    status        TEXT NOT NULL,
    progress      REAL NOT NULL DEFAULT 0,
    error_code    TEXT,
    error_message TEXT,
    tier          TEXT,
    shards        TEXT NOT NULL DEFAULT '[]',
    stages        TEXT NOT NULL DEFAULT '[]',
    docx_size     INTEGER,
    queued_at     REAL,
    created_at    REAL NOT NULL,
    started_at    REAL,
    finished_at   REAL,
    updated_at    REAL NOT NULL,
    rag_ok        INTEGER,
    rag_note      TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status, queued_at);

CREATE TABLE IF NOT EXISTS library (
    client_id    TEXT NOT NULL,
    doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    filename     TEXT NOT NULL,
    cache_hit    INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    PRIMARY KEY (client_id, doc_id)
);
CREATE INDEX IF NOT EXISTS idx_library_doc ON library(doc_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode = WAL")
            existing = {r["name"] for r in c.execute("PRAGMA table_info(documents)")}
            if existing and not DOCUMENT_COLUMNS.issubset(existing):
                raise RuntimeError(
                    f"{self.path} là app.db của một phiên bản backend CŨ (bảng 'documents' khác cấu trúc). "
                    f"Hãy sao lưu rồi đổi tên/xóa file này, hoặc đặt DATA_DIR sang thư mục mới."
                )
            c.executescript(SCHEMA)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
