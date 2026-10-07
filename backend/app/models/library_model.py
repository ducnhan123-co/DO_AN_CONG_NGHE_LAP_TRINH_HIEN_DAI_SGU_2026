"""Nghiệp vụ thư viện (SQLite thuần, theo client_id ẩn danh): tài liệu, phiên chat,
công thức (FTS5), lịch sử DOCX, nhật ký.

Dùng chung đường dẫn với backend qua Settings (pdf_path/docx_path/mineru_dir) — không còn
gọi HTTP sang chính mình như lib_api cũ.
"""
import hashlib
import json
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError, document_not_found
from backend.app.models import library_db as db
from backend.app.models.formulas import fts_query, parse_content_list

CLIENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")
DOC_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


# ---------------- kiểm tra / tra cứu ----------------
def require_client_id(value: str) -> str:
    if not CLIENT_ID_RE.fullmatch(value or ""):
        raise AppError(400, "INVALID_CLIENT_ID", "Thiếu hoặc sai header X-Client-Id.")
    return value


def valid_doc_id(value: str) -> str:
    if not DOC_ID_RE.fullmatch(value or ""):
        raise document_not_found(value)
    return value


def get_doc(conn: sqlite3.Connection, cid: str, doc_id: str, *, alive: bool = True) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM documents WHERE client_id=? AND doc_id=?",
                       (cid, valid_doc_id(doc_id))).fetchone()
    if not row or (alive and row["deleted_at"]):
        raise document_not_found(doc_id)
    return row


def get_session(conn: sqlite3.Connection, cid: str, sid: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sessions WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if not row:
        raise AppError(404, "SESSION_NOT_FOUND", "Phiên không tồn tại.")
    return row


def log(conn: sqlite3.Connection, cid: str, doc_id: str, kind: str, detail: str = "") -> None:
    conn.execute("INSERT INTO activity_log(client_id,doc_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                 (cid, doc_id, kind, detail[:300], time.time()))


# ---------------- tài liệu ----------------
def list_docs(conn, cid: str) -> List[dict]:
    rows = conn.execute("SELECT doc_id,name,display_name,num_pages,parser,created_at,last_opened_at FROM documents "
                        "WHERE client_id=? AND deleted_at IS NULL ORDER BY last_opened_at DESC", (cid,)).fetchall()
    return [dict(r) for r in rows]


def upsert_doc(conn, cid: str, doc_id: str, name: str, num_pages: Optional[int],
               parser: Optional[str]) -> dict:
    doc_id, now = valid_doc_id(doc_id), time.time()
    existing = conn.execute("SELECT deleted_at FROM documents WHERE client_id=? AND doc_id=?",
                            (cid, doc_id)).fetchone()
    if existing and existing["deleted_at"]:
        raise AppError(410, "DOCUMENT_DELETED", "Tài liệu đã bị xóa.")
    with conn:
        if existing:
            conn.execute("UPDATE documents SET name=?, num_pages=COALESCE(?,num_pages), parser=COALESCE(?,parser), "
                         "last_opened_at=? WHERE client_id=? AND doc_id=?",
                         (name, num_pages, parser, now, cid, doc_id))
        else:
            conn.execute("INSERT INTO documents(client_id,doc_id,name,num_pages,parser,created_at,last_opened_at) "
                         "VALUES(?,?,?,?,?,?,?)", (cid, doc_id, name, num_pages, parser, now, now))
            log(conn, cid, doc_id, "register", name)
    return dict(get_doc(conn, cid, doc_id))


def rename_doc(conn, cid: str, doc_id: str, display_name: str) -> dict:
    get_doc(conn, cid, doc_id)
    with conn:
        conn.execute("UPDATE documents SET display_name=? WHERE client_id=? AND doc_id=?",
                     (display_name, cid, doc_id))
    return dict(get_doc(conn, cid, doc_id))


def delete_document(conn, doc_id: str) -> bool:
    """Xóa dữ liệu thư viện của doc_id (phiên, tin nhắn, công thức, bản DOCX, nhật ký) cho MỌI client
    — PDF đã bị xóa khỏi backend nên mọi tham chiếu đều vô nghĩa. Dòng documents được đánh dấu
    deleted_at để PUT sau đó trả 410. Trả về True nếu thư viện có tài liệu này."""
    doc_id = valid_doc_id(doc_id)
    found = conn.execute("SELECT 1 FROM documents WHERE doc_id=? AND deleted_at IS NULL LIMIT 1",
                         (doc_id,)).fetchone() is not None
    cids = [r["client_id"] for r in conn.execute("SELECT DISTINCT client_id FROM documents WHERE doc_id=?", (doc_id,))]
    paths = [r["path"] for r in conn.execute("SELECT path FROM docx_versions WHERE doc_id=?", (doc_id,))]
    with conn:
        conn.execute("DELETE FROM sessions WHERE doc_id=?", (doc_id,))  # messages cascade
        conn.execute("DELETE FROM formulas_fts WHERE rowid IN (SELECT id FROM formulas WHERE doc_id=?)", (doc_id,))
        conn.execute("DELETE FROM formulas WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM docx_versions WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM activity_log WHERE doc_id=?", (doc_id,))
        conn.execute("UPDATE documents SET deleted_at=? WHERE doc_id=? AND deleted_at IS NULL", (time.time(), doc_id))
    for p in paths:                                   # cả bản chụp cũ nằm ở vị trí khác
        parent = Path(p).parent
        if parent.name == doc_id:
            shutil.rmtree(parent, ignore_errors=True)
        else:
            Path(p).unlink(missing_ok=True)
    for cid in cids:
        shutil.rmtree(db.LIBRARY_DIR / "docx" / cid / doc_id, ignore_errors=True)
    return found


# ---------------- phiên chat ----------------
def list_sessions(conn, cid: str, doc_id: str) -> List[dict]:
    get_doc(conn, cid, doc_id)
    rows = conn.execute(
        "SELECT s.id,s.title,s.created_at,s.updated_at,(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS message_count "
        "FROM sessions s WHERE s.client_id=? AND s.doc_id=? ORDER BY s.updated_at DESC", (cid, doc_id)).fetchall()
    return [dict(r) for r in rows]


def create_session(conn, cid: str, doc_id: str, title: str) -> dict:
    get_doc(conn, cid, doc_id)
    now, sid = time.time(), uuid.uuid4().hex
    count = conn.execute("SELECT COUNT(*) FROM sessions WHERE client_id=? AND doc_id=?", (cid, doc_id)).fetchone()[0]
    title = title.strip() or f"Phiên {count + 1}"
    with conn:
        conn.execute("INSERT INTO sessions(id,client_id,doc_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (sid, cid, doc_id, title, now, now))
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "message_count": 0}


def rename_session(conn, cid: str, sid: str, title: str) -> dict:
    get_session(conn, cid, sid)
    title = title.strip()
    if not title:
        raise AppError(422, "EMPTY_TITLE", "Tiêu đề rỗng.")
    with conn:
        conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, sid))
    return {"id": sid, "title": title}


def delete_session(conn, cid: str, sid: str) -> dict:
    get_session(conn, cid, sid)
    with conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    return {"deleted": sid}


def _message_row(row) -> dict:
    out = dict(row)
    out["citations"] = json.loads(out["citations"]) if out["citations"] else []
    return out


def get_messages(conn, cid: str, sid: str) -> List[dict]:
    get_session(conn, cid, sid)
    rows = conn.execute("SELECT id,role,content,citations,model,elapsed_s,created_at FROM messages "
                        "WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [_message_row(r) for r in rows]


def add_messages(conn, cid: str, sid: str, messages: list) -> dict:
    get_session(conn, cid, sid)
    now = time.time()
    with conn:
        for m in messages:
            conn.execute("INSERT INTO messages(session_id,role,content,citations,model,elapsed_s,created_at) "
                         "VALUES(?,?,?,?,?,?,?)",
                         (sid, m.role, m.content, json.dumps(m.citations) if m.citations else None,
                          m.model, m.elapsed_s, now))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
    return {"saved": len(messages)}


# ---------------- công thức + ngữ cảnh ----------------
def content_list_path(doc_id: str) -> Optional[Path]:
    found = list(get_settings().mineru_dir(doc_id).rglob("*_content_list.json"))
    return max(found, key=lambda p: p.stat().st_size) if found else None


def ingest(conn, cid: str, doc_id: str) -> dict:
    get_doc(conn, cid, doc_id)
    path = content_list_path(doc_id)
    if not path:
        return {"formulas": 0}
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError(422, "CONTENT_LIST_INVALID", f"content_list không đọc được: {str(exc)[:120]}") from exc
    if not isinstance(items, list):
        raise AppError(422, "CONTENT_LIST_INVALID", "content_list không phải danh sách.")
    formulas = parse_content_list(items)
    with conn:
        conn.execute("DELETE FROM formulas_fts WHERE rowid IN (SELECT id FROM formulas WHERE client_id=? AND doc_id=?)",
                     (cid, doc_id))
        conn.execute("DELETE FROM formulas WHERE client_id=? AND doc_id=?", (cid, doc_id))
        for f in formulas:
            cursor = conn.execute(
                "INSERT INTO formulas(client_id,doc_id,page,section,latex,ctx_before,ctx_after) VALUES(?,?,?,?,?,?,?)",
                (cid, doc_id, f["page"], f["section"], f["latex"], f["ctx_before"], f["ctx_after"]))
            conn.execute("INSERT INTO formulas_fts(rowid,latex,ctx_before,ctx_after) VALUES(?,?,?,?)",
                         (cursor.lastrowid, f["latex"], f["ctx_before"], f["ctx_after"]))
        log(conn, cid, doc_id, "ingest", f"{len(formulas)} công thức")
    return {"formulas": len(formulas)}


def context(conn, cid: str, doc_id: str, q: str = "", session_id: str = "") -> dict:
    get_doc(conn, cid, doc_id)
    recent: List[dict] = []
    if session_id:
        get_session(conn, cid, session_id)
        rows = conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 5",
                            (session_id,)).fetchall()
        recent = [dict(r) for r in reversed(rows)]
    formulas: List[dict] = []
    match = fts_query(q)
    if match:
        rows = conn.execute(
            "SELECT f.page,f.section,f.latex,f.ctx_before,f.ctx_after FROM formulas_fts "
            "JOIN formulas f ON f.id=formulas_fts.rowid "
            "WHERE formulas_fts MATCH ? AND f.client_id=? AND f.doc_id=? ORDER BY bm25(formulas_fts) LIMIT 3",
            (match, cid, doc_id)).fetchall()
        formulas = [dict(r) for r in rows]
    return {"recent": recent, "formulas": formulas}


# ---------------- lịch sử DOCX ----------------
def _version(row) -> dict:
    return {k: row[k] for k in ("id", "doc_id", "version", "source", "size", "created_at")}


def docx_snapshot(conn, cid: str, doc_id: str, source: str) -> dict:
    get_doc(conn, cid, doc_id)
    src = get_settings().docx_path(doc_id)
    if not src.exists():
        raise AppError(404, "DOCX_NOT_FOUND", "DOCX chưa có trên BE.")
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    row = conn.execute("SELECT * FROM docx_versions WHERE client_id=? AND doc_id=? AND sha256=?",
                       (cid, doc_id, digest)).fetchone()
    if row:
        return {**_version(row), "created": False}
    version = (conn.execute("SELECT MAX(version) FROM docx_versions WHERE client_id=? AND doc_id=?",
                            (cid, doc_id)).fetchone()[0] or 0) + 1
    target = db.LIBRARY_DIR / "docx" / cid / doc_id / f"v{version}.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    with conn:
        cursor = conn.execute("INSERT INTO docx_versions(client_id,doc_id,version,source,sha256,size,path,created_at) "
                              "VALUES(?,?,?,?,?,?,?,?)",
                              (cid, doc_id, version, source, digest, len(data), str(target), time.time()))
        log(conn, cid, doc_id, "docx", f"v{version} ({source}, {len(data)} B)")
    row = conn.execute("SELECT * FROM docx_versions WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {**_version(row), "created": True}


def docx_versions(conn, cid: str, doc_id: str) -> List[dict]:
    get_doc(conn, cid, doc_id)
    rows = conn.execute("SELECT * FROM docx_versions WHERE client_id=? AND doc_id=? ORDER BY version DESC",
                        (cid, doc_id)).fetchall()
    return [_version(r) for r in rows]


def docx_download(conn, cid: str, version_id: int) -> Tuple[Path, str]:
    row = conn.execute("SELECT v.*, d.name, d.display_name FROM docx_versions v JOIN documents d "
                       "ON d.client_id=v.client_id AND d.doc_id=v.doc_id WHERE v.id=? AND v.client_id=?",
                       (version_id, cid)).fetchone()
    if not row or not Path(row["path"]).exists():
        raise AppError(404, "DOCX_VERSION_NOT_FOUND", "Bản DOCX không tồn tại.")
    stem = Path(row["display_name"] or row["name"]).stem
    return Path(row["path"]), f"{stem}_v{row['version']}.docx"


def activity(conn, cid: str, doc_id: str) -> List[dict]:
    get_doc(conn, cid, doc_id)
    rows = conn.execute("SELECT kind,detail,created_at FROM activity_log WHERE client_id=? AND doc_id=? "
                        "ORDER BY id DESC LIMIT 100", (cid, doc_id)).fetchall()
    return [dict(r) for r in rows]