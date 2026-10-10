"""Controller: thư viện theo client_id ẩn danh (header X-Client-Id) — tài liệu, phiên chat,
công thức, lịch sử DOCX. Gộp từ lib_api (cổng 8002) cũ.

Lưu ý: DELETE /doc/{doc_id} nằm ở compat_controller (xóa cả dữ liệu backend lẫn thư viện).
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import FileResponse

from backend.app.core.config import DOCX_MIME, get_settings
from backend.app.core.errors import AppError
from backend.app.models import library_model
from backend.app.models.library_db import LibDb
from backend.app.views.library_schemas import (CollectionIn, CollectionRenameIn, DocIn,
                                               MessagesIn, RenameIn, SessionIn, SnapshotIn)

router = APIRouter(tags=["library"])


def client_id(x_client_id: Annotated[str, Header()] = "") -> str:
    return library_model.require_client_id(x_client_id)


Cid = Annotated[str, Depends(client_id)]


@router.get("/lib/health", summary="Kiểm tra thư viện")
def lib_health(conn: LibDb) -> dict:
    conn.execute("SELECT 1")
    return {"ok": True}


# ---------------- tài liệu ----------------
@router.get("/doc", summary="Danh sách tài liệu của client")
def list_docs(cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.list_docs(conn, cid)


@router.put("/doc/{doc_id}", summary="Đăng ký / cập nhật tài liệu vào thư viện")
def upsert_doc(doc_id: str, body: DocIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.upsert_doc(conn, cid, doc_id, body.name, body.num_pages, body.parser)


@router.patch("/doc/{doc_id}", summary="Đổi tên hiển thị")
def rename_doc(doc_id: str, body: RenameIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.rename_doc(conn, cid, doc_id, body.display_name)


@router.get("/doc/{doc_id}/file", summary="PDF gốc (hỗ trợ Range) — mở không cần chờ nạp chỉ mục")
def pdf_file(doc_id: str, cid: Cid, conn: LibDb):
    library_model.get_doc(conn, cid, doc_id)
    path = get_settings().pdf_path(doc_id)
    if not path.exists():
        raise AppError(404, "PDF_MISSING", "PDF không có trên đĩa.")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")


# ---------------- phiên chat ----------------
@router.get("/doc/{doc_id}/sessions", summary="Danh sách phiên chat")
def list_sessions(doc_id: str, cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.list_sessions(conn, cid, doc_id)


@router.post("/doc/{doc_id}/sessions", summary="Tạo phiên chat")
def create_session(doc_id: str, body: SessionIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.create_session(conn, cid, doc_id, body.title)


@router.patch("/session/{sid}", summary="Đổi tên phiên")
def rename_session(sid: str, body: SessionIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.rename_session(conn, cid, sid, body.title)


@router.delete("/session/{sid}", summary="Xóa phiên")
def delete_session(sid: str, cid: Cid, conn: LibDb) -> dict:
    return library_model.delete_session(conn, cid, sid)


@router.get("/session/{sid}/messages", summary="Tin nhắn của phiên")
def get_messages(sid: str, cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.get_messages(conn, cid, sid)


@router.post("/session/{sid}/messages", summary="Lưu tin nhắn vào phiên")
def add_messages(sid: str, body: MessagesIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.add_messages(conn, cid, sid, body.messages)


# ---------------- công thức + ngữ cảnh ----------------
@router.post("/doc/{doc_id}/ingest", summary="Nạp công thức từ content_list của MinerU")
def ingest(doc_id: str, cid: Cid, conn: LibDb) -> dict:
    return library_model.ingest(conn, cid, doc_id)


@router.get("/doc/{doc_id}/context", summary="Ngữ cảnh: tin nhắn gần đây + công thức liên quan")
def context(doc_id: str, cid: Cid, conn: LibDb, q: str = "", session_id: str = "") -> dict:
    return library_model.context(conn, cid, doc_id, q, session_id)


# ---------------- lịch sử DOCX ----------------
@router.post("/doc/{doc_id}/docx/snapshot", summary="Chụp bản DOCX hiện tại thành 1 phiên bản")
def docx_snapshot(doc_id: str, body: SnapshotIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.docx_snapshot(conn, cid, doc_id, body.source)


@router.get("/doc/{doc_id}/docx", summary="Danh sách phiên bản DOCX")
def docx_versions(doc_id: str, cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.docx_versions(conn, cid, doc_id)


@router.get("/doc/{version_id}/download", summary="Tải 1 phiên bản DOCX")
def docx_download(version_id: int, cid: Cid, conn: LibDb):
    path, filename = library_model.docx_download(conn, cid, version_id)
    return FileResponse(path, filename=filename, media_type=DOCX_MIME)


@router.get("/doc/{doc_id}/activity", summary="Nhật ký hoạt động")
def activity(doc_id: str, cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.activity(conn, cid, doc_id)


# ---------------- nhóm tài liệu (chat chung nhiều file) ----------------
@router.get("/collection", summary="Danh sách nhóm tài liệu của client")
def list_collections(cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.list_collections(conn, cid)


@router.post("/collection", summary="Tạo nhóm từ nhiều tài liệu (cùng tập tài liệu -> trả nhóm cũ)")
def create_collection(body: CollectionIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.create_collection(conn, cid, body.doc_ids, body.name)


@router.get("/collection/{coll_id}", summary="Chi tiết nhóm + danh sách tài liệu theo thứ tự")
def get_collection(coll_id: str, cid: Cid, conn: LibDb) -> dict:
    return library_model.collection_detail(conn, cid, coll_id)


@router.patch("/collection/{coll_id}", summary="Đổi tên nhóm")
def rename_collection(coll_id: str, body: CollectionRenameIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.rename_collection(conn, cid, coll_id, body.name)


@router.delete("/collection/{coll_id}", summary="Xóa nhóm + phiên chat chung (không xóa tài liệu)")
def delete_collection(coll_id: str, cid: Cid, conn: LibDb) -> dict:
    return library_model.delete_collection(conn, cid, coll_id)


@router.get("/collection/{coll_id}/sessions", summary="Phiên chat chung của nhóm")
def list_collection_sessions(coll_id: str, cid: Cid, conn: LibDb) -> list[dict]:
    return library_model.list_collection_sessions(conn, cid, coll_id)


@router.post("/collection/{coll_id}/sessions", summary="Tạo phiên chat chung của nhóm")
def create_collection_session(coll_id: str, body: SessionIn, cid: Cid, conn: LibDb) -> dict:
    return library_model.create_collection_session(conn, cid, coll_id, body.title)


@router.get("/collection/{coll_id}/context", summary="Ngữ cảnh nhóm: tin nhắn gần đây + công thức liên quan")
def collection_context(coll_id: str, cid: Cid, conn: LibDb, q: str = "", session_id: str = "") -> dict:
    return library_model.collection_context(conn, cid, coll_id, q, session_id)