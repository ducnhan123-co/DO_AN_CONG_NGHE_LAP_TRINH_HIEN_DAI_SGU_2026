import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.llm import LLMError, get_llm
from backend.app.models import chat_model, document_model
from backend.app.models.database import DocumentStatus, get_db

router = APIRouter(tags=["compat (frontend hiện tại)"])
DbSession = Annotated[Session, Depends(get_db)]


def _raise_as_http(exc: AppError):
    raise HTTPException(exc.status_code, exc.message)


def _parser_status(status: str) -> str:
    """Map trạng thái nội bộ sang 4 giá trị mà PARSER[] trong reader.html hiểu:
    pypdf | mineru_running | mineru | mineru_failed."""
    if status == DocumentStatus.ready.value:
        return "mineru"
    if status == DocumentStatus.failed.value:
        return "mineru_failed"
    return "mineru_running"


def _num_pages(pdf_path) -> int:
    """Đếm số trang nhanh bằng pypdf, không phụ thuộc MinerU đã chạy xong hay chưa."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:              # noqa: BLE001
        return 0


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
        doc, job = document_model.create_document(db, f)
    except AppError as exc:
        _raise_as_http(exc)
    settings = get_settings()
    return {
        "doc_id": doc.id,
        "name": doc.filename,
        "num_pages": _num_pages(settings.pdf_path(doc.id)),
        "num_chunks": 0,                         # chưa lập chỉ mục xong, cập nhật khi poll /doc/{id}
        "parser": _parser_status(doc.status),
        "job_id": job.id,
    }


@router.get("/doc/{doc_id}", summary="[Tương thích] Thông tin tài liệu")
def doc_info(doc_id: str, db: DbSession) -> dict:
    try:
        out = document_model.document_out(db, doc_id)
    except AppError as exc:
        _raise_as_http(exc)
    settings = get_settings()
    return {
        "doc_id": out.id,
        "name": out.filename,
        "num_pages": _num_pages(settings.pdf_path(out.id)),
        "num_chunks": out.num_chunks,
        "parser": _parser_status(out.status),
        "file_url": f"{settings.api_prefix}/file/{out.id}",   # reader.html: API.fileUrl = API.base + j.file_url
    }


@router.get("/file/{doc_id}", summary="[Tương thích] Xem PDF gốc (inline)")
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


@router.post("/chat_stream", summary="[Tương thích] Chat SSE (định dạng {t}/{done}/{error})")
def chat_stream(payload: ChatStreamRequest, db: DbSession):
    try:
        document_model.get_document(db, payload.doc_id)
        chat_model.ensure_ready(db, payload.doc_id)
    except AppError as exc:
        _raise_as_http(exc)

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
                    payload_out = {"done": True, "elapsed_s": elapsed, "citations": pages}
                    yield f"data: {json.dumps(payload_out, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    yield f"data: {json.dumps({'error': data['message']}, ensure_ascii=False)}\n\n"
        except Exception as exc:                      # noqa: BLE001
            yield f"data: {json.dumps({'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")