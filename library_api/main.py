"""Library API (cổng 8002): tài liệu, phiên chat, công thức, lịch sử DOCX theo client_id ẩn danh."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from library_api import db, sources
from library_api.formulas import fts_query, parse_content_list

ORIGINS = [o for o in os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:5173,http://localhost:5173").split(",") if o]
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")

app = FastAPI(title="SGU Library API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "X-Client-Id", "Range"],
                   expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])


@app.exception_handler(sqlite3.OperationalError)
def _db_busy(_request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": f"CSDL bận hoặc lỗi: {str(exc)[:120]}"}, status_code=503)


def get_db():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def client_id(x_client_id: str = Header(default="")) -> str:
    if not CLIENT_ID_RE.fullmatch(x_client_id):
        raise HTTPException(400, "Thiếu hoặc sai header X-Client-Id.")
    return x_client_id


def _doc_id(value: str) -> str:
    if not sources.DOC_ID_RE.fullmatch(value):
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return value


def _doc(conn, cid: str, doc_id: str, *, alive: bool = True):
    row = conn.execute("SELECT * FROM documents WHERE client_id=? AND doc_id=?", (cid, _doc_id(doc_id))).fetchone()
    if not row or (alive and row["deleted_at"]):
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return row


def _session(conn, cid: str, sid: str):
    row = conn.execute("SELECT * FROM sessions WHERE id=? AND client_id=?", (sid, cid)).fetchone()
    if not row:
        raise HTTPException(404, "Phiên không tồn tại.")
    return row


def _log(conn, cid: str, doc_id: str, kind: str, detail: str = "") -> None:
    conn.execute("INSERT INTO activity_log(client_id,doc_id,kind,detail,created_at) VALUES(?,?,?,?,?)",
                 (cid, doc_id, kind, detail[:300], time.time()))


class DocIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    num_pages: int | None = Field(default=None, ge=0, le=100000)
    parser: str | None = Field(default=None, max_length=40)


class RenameIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class SessionIn(BaseModel):
    title: str = Field(default="", max_length=120)


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    citations: list[int] | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    elapsed_s: float | None = None


class MessagesIn(BaseModel):
    messages: list[MessageIn] = Field(min_length=1, max_length=4)


class SnapshotIn(BaseModel):
    source: Literal["fast", "mineru"] = "fast"


@app.get("/api/lib/health")
def health() -> dict:
    return {"ok": True}


# ---------------- tài liệu ----------------
@app.get("/api/doc")
def list_docs(cid: str = Depends(client_id), conn=Depends(get_db)) -> list[dict]:
    rows = conn.execute("SELECT doc_id,name,display_name,num_pages,parser,created_at,last_opened_at FROM documents "
                        "WHERE client_id=? AND deleted_at IS NULL ORDER BY last_opened_at DESC", (cid,)).fetchall()
    return [dict(r) for r in rows]


@app.put("/api/doc/{doc_id}")
def upsert_doc(doc_id: str, body: DocIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    doc_id, now = _doc_id(doc_id), time.time()
    existing = conn.execute("SELECT deleted_at FROM documents WHERE client_id=? AND doc_id=?", (cid, doc_id)).fetchone()
    if existing and existing["deleted_at"]:
        raise HTTPException(410, "Tài liệu đã bị xóa.")
    with conn:
        if existing:
            conn.execute("UPDATE documents SET name=?, num_pages=COALESCE(?,num_pages), parser=COALESCE(?,parser), "
                         "last_opened_at=? WHERE client_id=? AND doc_id=?",
                         (body.name, body.num_pages, body.parser, now, cid, doc_id))
        else:
            conn.execute("INSERT INTO documents(client_id,doc_id,name,num_pages,parser,created_at,last_opened_at) "
                         "VALUES(?,?,?,?,?,?,?)", (cid, doc_id, body.name, body.num_pages, body.parser, now, now))
            _log(conn, cid, doc_id, "register", body.name)
    return dict(_doc(conn, cid, doc_id))


@app.patch("/api/doc/{doc_id}")
def rename_doc(doc_id: str, body: RenameIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    with conn:
        conn.execute("UPDATE documents SET display_name=? WHERE client_id=? AND doc_id=?", (body.display_name, cid, doc_id))
    return dict(_doc(conn, cid, doc_id))


@app.delete("/api/doc/{doc_id}")
def delete_doc(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    pdf = sources.delete_pdf(doc_id)
    with conn:
        conn.execute("DELETE FROM sessions WHERE client_id=? AND doc_id=?", (cid, doc_id))  # messages cascade
        conn.execute("DELETE FROM formulas_fts WHERE rowid IN (SELECT id FROM formulas WHERE client_id=? AND doc_id=?)",
                     (cid, doc_id))
        conn.execute("DELETE FROM formulas WHERE client_id=? AND doc_id=?", (cid, doc_id))
        conn.execute("DELETE FROM docx_versions WHERE client_id=? AND doc_id=?", (cid, doc_id))
        conn.execute("DELETE FROM activity_log WHERE client_id=? AND doc_id=?", (cid, doc_id))
        conn.execute("UPDATE documents SET deleted_at=? WHERE client_id=? AND doc_id=?", (time.time(), cid, doc_id))
    shutil.rmtree(db.LIBRARY_DIR / "docx" / cid / doc_id, ignore_errors=True)
    return {"library": "deleted", "pdf": pdf}


@app.get("/api/doc/{doc_id}/file")
def pdf_file(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)):
    """PDF gốc đọc thẳng từ đĩa (hỗ trợ Range) — mở tài liệu không phải chờ BE nạp chỉ mục."""
    _doc(conn, cid, doc_id)
    path = sources.pdf_path(doc_id)
    if not path.exists():
        raise HTTPException(404, "PDF không có trên đĩa.")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")


# ---------------- phiên chat ----------------
@app.get("/api/doc/{doc_id}/sessions")
def list_sessions(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> list[dict]:
    _doc(conn, cid, doc_id)
    rows = conn.execute(
        "SELECT s.id,s.title,s.created_at,s.updated_at,(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS message_count "
        "FROM sessions s WHERE s.client_id=? AND s.doc_id=? ORDER BY s.updated_at DESC", (cid, doc_id)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/doc/{doc_id}/sessions")
def create_session(doc_id: str, body: SessionIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    now, sid = time.time(), uuid.uuid4().hex
    count = conn.execute("SELECT COUNT(*) FROM sessions WHERE client_id=? AND doc_id=?", (cid, doc_id)).fetchone()[0]
    title = body.title.strip() or f"Phiên {count + 1}"
    with conn:
        conn.execute("INSERT INTO sessions(id,client_id,doc_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (sid, cid, doc_id, title, now, now))
    return {"id": sid, "title": title, "created_at": now, "updated_at": now, "message_count": 0}


@app.patch("/api/session/{sid}")
def rename_session(sid: str, body: SessionIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _session(conn, cid, sid)
    if not body.title.strip():
        raise HTTPException(422, "Tiêu đề rỗng.")
    with conn:
        conn.execute("UPDATE sessions SET title=? WHERE id=?", (body.title.strip(), sid))
    return {"id": sid, "title": body.title.strip()}


@app.delete("/api/session/{sid}")
def delete_session(sid: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _session(conn, cid, sid)
    with conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    return {"deleted": sid}


def _message_row(row) -> dict:
    out = dict(row)
    out["citations"] = json.loads(out["citations"]) if out["citations"] else []
    return out


@app.get("/api/session/{sid}/messages")
def get_messages(sid: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> list[dict]:
    _session(conn, cid, sid)
    rows = conn.execute("SELECT id,role,content,citations,model,elapsed_s,created_at FROM messages "
                        "WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    return [_message_row(r) for r in rows]


@app.post("/api/session/{sid}/messages")
def add_messages(sid: str, body: MessagesIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _session(conn, cid, sid)
    now = time.time()
    with conn:
        for m in body.messages:
            conn.execute("INSERT INTO messages(session_id,role,content,citations,model,elapsed_s,created_at) "
                         "VALUES(?,?,?,?,?,?,?)",
                         (sid, m.role, m.content, json.dumps(m.citations) if m.citations else None,
                          m.model, m.elapsed_s, now))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, sid))
    return {"saved": len(body.messages)}


# ---------------- công thức + ngữ cảnh ----------------
@app.post("/api/doc/{doc_id}/ingest")
def ingest(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    path = sources.content_list_path(doc_id)
    if not path:
        return {"formulas": 0}
    try:
        formulas = parse_content_list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f"content_list không đọc được: {str(exc)[:120]}") from exc
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
        _log(conn, cid, doc_id, "ingest", f"{len(formulas)} công thức")
    return {"formulas": len(formulas)}


@app.get("/api/doc/{doc_id}/context")
def context(doc_id: str, q: str = "", session_id: str = "", cid: str = Depends(client_id),
            conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    recent: list[dict] = []
    if session_id:
        _session(conn, cid, session_id)
        rows = conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 5",
                            (session_id,)).fetchall()
        recent = [dict(r) for r in reversed(rows)]
    formulas: list[dict] = []
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
@app.post("/api/doc/{doc_id}/docx/snapshot")
def docx_snapshot(doc_id: str, body: SnapshotIn, cid: str = Depends(client_id), conn=Depends(get_db)) -> dict:
    _doc(conn, cid, doc_id)
    src = sources.docx_path(doc_id)
    if not src.exists():
        raise HTTPException(404, "DOCX chưa có trên BE.")
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
                              (cid, doc_id, version, body.source, digest, len(data), str(target), time.time()))
        _log(conn, cid, doc_id, "docx", f"v{version} ({body.source}, {len(data)} B)")
    row = conn.execute("SELECT * FROM docx_versions WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {**_version(row), "created": True}


def _version(row) -> dict:
    return {k: row[k] for k in ("id", "doc_id", "version", "source", "size", "created_at")}


@app.get("/api/doc/{doc_id}/docx")
def docx_versions(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> list[dict]:
    _doc(conn, cid, doc_id)
    rows = conn.execute("SELECT * FROM docx_versions WHERE client_id=? AND doc_id=? ORDER BY version DESC",
                        (cid, doc_id)).fetchall()
    return [_version(r) for r in rows]


@app.get("/api/doc/{version_id}/download")
def docx_download(version_id: int, cid: str = Depends(client_id), conn=Depends(get_db)):
    row = conn.execute("SELECT v.*, d.name, d.display_name FROM docx_versions v JOIN documents d "
                       "ON d.client_id=v.client_id AND d.doc_id=v.doc_id WHERE v.id=? AND v.client_id=?",
                       (version_id, cid)).fetchone()
    if not row or not Path(row["path"]).exists():
        raise HTTPException(404, "Bản DOCX không tồn tại.")
    stem = Path(row["display_name"] or row["name"]).stem
    return FileResponse(row["path"], filename=f"{stem}_v{row['version']}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/api/doc/{doc_id}/activity")
def activity(doc_id: str, cid: str = Depends(client_id), conn=Depends(get_db)) -> list[dict]:
    _doc(conn, cid, doc_id)
    rows = conn.execute("SELECT kind,detail,created_at FROM activity_log WHERE client_id=? AND doc_id=? "
                        "ORDER BY id DESC LIMIT 100", (cid, doc_id)).fetchall()
    return [dict(r) for r in rows]
