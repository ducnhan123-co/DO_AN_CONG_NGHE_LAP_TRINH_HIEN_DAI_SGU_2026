"""Controller: upload tài liệu và xem thông tin tài liệu."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy.orm import Session

from backend.app.models import document_model
from backend.app.models.database import get_db
from backend.app.views.schemas import DocumentCreated, DocumentOut, errors

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/documents", tags=["documents"], response_model=DocumentCreated, status_code=202,
             summary="Upload PDF và bắt đầu xử lý", responses=errors(400, 413, 415, 422))
def upload_document(response: Response, db: DbSession,
                    file: UploadFile = File(..., description="File PDF toán")):
    doc, job = document_model.create_document(db, file)
    job_url = f"/jobs/{job.id}"
    response.headers["Location"] = job_url
    return DocumentCreated(document_id=doc.id, job_id=job.id, filename=doc.filename,
                           status=doc.status, job_url=job_url)


@router.get("/documents/{document_id}", tags=["documents"], response_model=DocumentOut,
            summary="Xem thông tin và trạng thái tài liệu", responses=errors(404))
def get_document(document_id: str, db: DbSession):
    return document_model.document_out(db, document_id)