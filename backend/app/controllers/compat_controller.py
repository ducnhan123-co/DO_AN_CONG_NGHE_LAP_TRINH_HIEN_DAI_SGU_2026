"""
4 trục trạng thái độc lập (status/parser/embed/docx) được tính từ DocumentStatus
nội bộ của backend MVC — vì pipeline hiện tại chạy MinerU-first tuần tự (không có
bước "pypdf đọc nhanh trước"), field "parser" sẽ không bao giờ trả về 'pypdf',
chỉ nhảy thẳng mineru_running -> mineru.
"""
import json
import time
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.llm import LLMError, get_llm
from backend.app.models import chat_model, document_model
from backend.app.models.database import Document, DocumentStatus, get_db

router = APIRouter(tags=["compat (frontend hiện tại)"])
DbSession = Annotated[Session, Depends(get_db)]


def _raise_as_http(exc: AppError):
    raise HTTPException(exc.status_code, exc.message)


def _num_pages(pdf_path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:              # noqa: BLE001
        return 0


def _compat_info(doc: Document) -> dict:
    """Dựng đúng 4 field trạng thái mà reader.html/index.html đọc trực tiếp."""
    settings = get_settings()
    docx_exists = settings.docx_path(doc.id).exists()

    if doc.status == DocumentStatus.ready.value:
        status, parser = "ready", "mineru"
    elif doc.status == DocumentStatus.failed.value:
        status, parser = "failed", "mineru_failed"
    else:
        status, parser = "indexing", "mineru_running"

    embed = "building" if doc.status == DocumentStatus.indexing.value else None

    if doc.status == DocumentStatus.failed.value:
        docx_state = "failed"
    elif docx_exists:
        docx_state = "ready"
    else:
        docx_state = "building"

    return {
        "doc_id": doc.id, "name": doc.filename,
        "num_pages": _num_pages(settings.pdf_path(doc.id)),
        "num_chunks": doc.num_chunks,
        "status": status, "parser": parser, "embed": embed,
        "docx": docx_state,
        "docx_url": f"{settings.api_prefix}/docx/{doc.id}" if docx_state == "ready" else None,
        "file_url": f"{settings.api_prefix}/file/{doc.id}",
        "error": doc.error_message if doc.status == DocumentStatus.failed.value else None,
    }


class WarmRequest(BaseModel):
    model: str = Field(default="", max_length=100)


class ChatStreamRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    model: str = Field(default="", max_length=100)
    history: list[dict] = Field(default_factory=list, max_length=12)


@router.post("/upload", summary="[Tương thích] Upload PDF")
async def upload(db: DbSession, f: UploadFile = File(...)) -> dict:
    try:
        doc, _job = document_model.create_document(db, f)
    except AppError as exc:
        _raise_as_http(exc)
    return _compat_info(doc)


@router.get("/lib/doc/{doc_id}", summary="[Tương thích] Thông tin tài liệu (4 trục trạng thái)")
def doc_info(doc_id: str, db: DbSession) -> dict:
    try:
        doc = document_model.get_document(db, doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    return _compat_info(doc)


@router.delete("/lib/doc/{doc_id}", summary="[Tương thích] Xóa tài liệu")
def delete_doc(doc_id: str, db: DbSession):
    try:
        document_model.delete_document(db, doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    return {"ok": True}


@router.get("/lib/file/{doc_id}", summary="[Tương thích] Xem PDF gốc (inline)")
def file(doc_id: str, db: DbSession):
    try:
        doc = document_model.get_document(db, doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    path = get_settings().pdf_path(doc.id)
    if not path.exists():
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename,
                        content_disposition_type="inline")


@router.get("/lib/docx/{doc_id}", summary="[Tương thích] Tải file DOCX (endpoint riêng, khớp docx_url)")
def docx_file(doc_id: str, db: DbSession):
    try:
        doc = document_model.get_document(db, doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    path = get_settings().docx_path(doc.id)
    if doc.status == DocumentStatus.failed.value:
        raise HTTPException(404, "Tài liệu xử lý thất bại, không có DOCX.")
    if not path.exists():
        raise HTTPException(425, "DOCX đang xử lý, xong sẽ tải được.")
    name = Path(doc.filename).stem + ".docx"
    return FileResponse(
        path, filename=name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.post("/warm", summary="[Tương thích] Nạp trước mô hình ngôn ngữ")
def warm(payload: WarmRequest) -> dict:
    try:
        model = get_llm()
    except LLMError as exc:
        raise HTTPException(502, f"Không nạp được mô hình: {exc}") from exc
    if model is None:
        return {"ok": True, "model": None}
    warm_fn = getattr(model, "warm", None)
    if callable(warm_fn):
        try:
            warm_fn()
        except Exception as exc:                     # noqa: BLE001
            raise HTTPException(502, f"Lỗi khi warm mô hình: {str(exc)[:300]}") from exc
    return {"ok": True, "model": model.name}


@router.post("/chat_stream", summary="[Tương thích] Chat SSE ({t}/{done}/{error}, 425 khi đang xử lý)")
def chat_stream(payload: ChatStreamRequest, db: DbSession):
    try:
        doc = document_model.get_document(db, payload.doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    if doc.status != DocumentStatus.ready.value:
        detail = (doc.error_message or "Tài liệu xử lý thất bại.") \
            if doc.status == DocumentStatus.failed.value \
            else "Tài liệu đang được xử lý, vài giây nữa chat được."
        raise HTTPException(425, detail)

    def events():
        start = time.perf_counter()
        try:
            for kind, data in chat_model.stream_events(
                payload.doc_id, payload.question, payload.top_k,
                client_history=payload.history or None,
            ):
                if kind == "token":
                    yield f"data: {json.dumps({'t': data['text']}, ensure_ascii=False)}\n\n"
                elif kind == "done":
                    elapsed = round(time.perf_counter() - start, 1)
                    pages = sorted({c["page"] for c in data["citations"] if c.get("page") is not None})
                    out = {"done": True, "elapsed_s": elapsed, "citations": pages}
                    yield f"data: {json.dumps(out, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    yield f"data: {json.dumps({'error': data['message']}, ensure_ascii=False)}\n\n"
        except Exception as exc:                      # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")