"""SQLite cho thư viện: kết nối + migration (PRAGMA user_version). Chỉ dùng stdlib."""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("LIBRARY_DB", ROOT / "runtime" / "library.db"))
LIBRARY_DIR = Path(os.getenv("LIBRARY_DATA_DIR", ROOT / "runtime" / "library"))  # bản chụp DOCX

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
MIGRATIONS = [SCHEMA_V1]  # thêm phần tử mới ở cuối để nâng phiên bản


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
