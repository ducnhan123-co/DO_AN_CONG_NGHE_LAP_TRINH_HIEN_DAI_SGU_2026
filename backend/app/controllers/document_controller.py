"""Controller: upload, liệt kê, xem thông tin, thử lại tài liệu."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from backend.app.models import document_model
from backend.app.models.database import get_db
from backend.app.views.schemas import (DocumentCreated, DocumentListItem,
                                       DocumentListOut, DocumentOut, errors)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/documents", tags=["documents"], response_model=DocumentCreated, status_code=202,
             summary="Upload PDF và bắt đầu xử lý", responses=errors(400, 413, 415, 422, 429))
def upload_document(response: Response, db: DbSession,
                    file: UploadFile = File(..., description="File PDF toán")):
    doc, job = document_model.create_document(db, file)
    job_url = f"/jobs/{job.id}"
    response.headers["Location"] = job_url
    return DocumentCreated(document_id=doc.id, job_id=job.id, filename=doc.filename,
                           status=doc.status, job_url=job_url)


@router.get("/documents", tags=["documents"], response_model=DocumentListOut,
            summary="Liệt kê tài liệu (mới nhất trước)")
def list_documents(db: DbSession, limit: int = 20, offset: int = 0):
    rows, total = document_model.list_documents(db, limit, offset)
    items = [DocumentListItem(id=r.id, filename=r.filename, status=r.status,
                              created_at=r.created_at) for r in rows]
    return DocumentListOut(items=items, total=total)


@router.get("/documents/{document_id}", tags=["documents"], response_model=DocumentOut,
            summary="Xem thông tin và trạng thái tài liệu", responses=errors(404))
def get_document(document_id: str, db: DbSession):
    return document_model.document_out(db, document_id)


@router.post("/documents/{document_id}/retry", tags=["documents"], response_model=DocumentCreated,
             status_code=202,
             summary="Thử lại xử lý tài liệu đã failed (dùng lại PDF đã lưu, không cần upload lại)",
             responses=errors(404, 409, 429))
def retry_document(document_id: str, response: Response, db: DbSession):
    doc, job = document_model.retry_document(db, document_id)
    job_url = f"/jobs/{job.id}"
    response.headers["Location"] = job_url
    return DocumentCreated(document_id=doc.id, job_id=job.id, filename=doc.filename,
                           status=doc.status, job_url=job_url)