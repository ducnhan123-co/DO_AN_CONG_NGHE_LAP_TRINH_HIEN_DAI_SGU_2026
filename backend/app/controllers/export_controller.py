"""Controller: xem PDF gốc (inline, hỗ trợ Range) và tải DOCX."""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.config import DOCX_MIME, get_settings
from backend.app.core.errors import AppError
from backend.app.models import document_model as dm
from backend.app.models.database import Status, get_db
from backend.app.views.schemas import errors

router = APIRouter(prefix="/documents", tags=["files"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{document_id}/pdf", summary="PDF gốc (xem inline)", response_class=FileResponse, responses=errors(404))
def pdf(document_id: str, db: DbSession):
    doc = dm.get_document(db, document_id)
    path = get_settings().pdf_path(doc.id)
    if not path.exists():
        raise AppError(404, "PDF_MISSING", "Không còn file PDF gốc.")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename, content_disposition_type="inline")


@router.get("/{document_id}/docx", summary="Tải file DOCX", response_class=FileResponse,
            responses={200: {"content": {DOCX_MIME: {}}, "description": "File DOCX"}, **errors(404, 409)})
def docx(document_id: str, db: DbSession):
    doc = dm.get_document(db, document_id)
    path = get_settings().docx_path(doc.id)
    if doc.status != Status.done.value or not path.exists():
        code = "DOCUMENT_FAILED" if doc.status in (Status.failed.value, Status.cancelled.value) else "DOCX_NOT_READY"
        raise AppError(409, code, "Chưa có file DOCX: tài liệu chưa xử lý xong hoặc xử lý thất bại.",
                       {"status": doc.status, "error": doc.error_code})
    return FileResponse(path, media_type=DOCX_MIME, filename=Path(doc.display_name or doc.filename).stem + ".docx")
