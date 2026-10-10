"""SQLite cho thư viện (theo client_id ẩn danh): kết nối + migration (PRAGMA user_version).

Dùng FILE RIÊNG (library.db), KHÔNG dùng chung app.db của SQLAlchemy: hai bên đều có bảng
documents/messages nên trộn chung sẽ xung đột. Chỉ dùng stdlib sqlite3.
"""
import os
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from backend.app.core.config import get_settings

_settings = get_settings()
DB_PATH = Path(os.getenv("LIBRARY_DB", _settings.data_dir / "library.db"))
LIBRARY_DIR = Path(os.getenv("LIBRARY_DATA_DIR", _settings.data_dir / "library"))  # bản chụp DOCX: docx/<client>/<doc>/vN.docx

SCHEMA_V1 = """
CREATE TABLE documents(
  client_id TEXT NOT NULL, doc_id TEXT NOT NULL, name TEXT NOT NULL, display_name TEXT,
  num_pages INTEGER, parser TEXT, created_at REAL NOT NULL, last_opened_at REAL NOT NULL, deleted_at REAL,
  PRIMARY KEY(client_id, doc_id));
CREATE TABLE sessions(
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, doc_id TEXT NOT NULL, title TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX sessions_doc ON sessions(client_id, doc_id, updated_at);
CREATE TABLE messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN('user','assistant')), content TEXT NOT NULL,
  citations TEXT, model TEXT, elapsed_s REAL, created_at REAL NOT NULL);
CREATE INDEX messages_session ON messages(session_id, id);
CREATE TABLE formulas(
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, doc_id TEXT NOT NULL,
  page INTEGER, section TEXT, latex TEXT NOT NULL, ctx_before TEXT, ctx_after TEXT);
CREATE INDEX formulas_doc ON formulas(client_id, doc_id);
CREATE VIRTUAL TABLE formulas_fts USING fts5(latex, ctx_before, ctx_after);
CREATE TABLE docx_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, doc_id TEXT NOT NULL,
  version INTEGER NOT NULL, source TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
  path TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(client_id, doc_id, sha256));
CREATE TABLE activity_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL, doc_id TEXT NOT NULL,
  kind TEXT NOT NULL, detail TEXT, created_at REAL NOT NULL);
CREATE INDEX activity_doc ON activity_log(client_id, doc_id, id);
"""
# V2: nhóm tài liệu (collection) để chat chung nhiều file. Phiên chat của nhóm có
# sessions.collection_id != NULL và doc_id = '' (phiên của 1 tài liệu giữ collection_id NULL).
SCHEMA_V2 = """
CREATE TABLE collections(
  id TEXT PRIMARY KEY, client_id TEXT NOT NULL, name TEXT NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX collections_client ON collections(client_id, updated_at);
CREATE TABLE collection_docs(
  collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  doc_id TEXT NOT NULL, position INTEGER NOT NULL,
  PRIMARY KEY(collection_id, doc_id));
CREATE INDEX collection_docs_doc ON collection_docs(doc_id);
ALTER TABLE sessions ADD COLUMN collection_id TEXT;
CREATE INDEX sessions_collection ON sessions(client_id, collection_id, updated_at);
"""
MIGRATIONS = [SCHEMA_V1, SCHEMA_V2]  # thêm phần tử mới ở cuối để nâng phiên bản


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        try:
            conn.executescript("BEGIN;" + MIGRATIONS[index] + f"PRAGMA user_version={index + 1};COMMIT;")
        except sqlite3.OperationalError:
            conn.rollback()  # tiến trình khác vừa migrate xong
            if conn.execute("PRAGMA user_version").fetchone()[0] <= index:
                raise
    return conn


def get_lib_db():
    """Dependency FastAPI: 1 kết nối SQLite cho mỗi request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


LibDb = Annotated[sqlite3.Connection, Depends(get_lib_db)]