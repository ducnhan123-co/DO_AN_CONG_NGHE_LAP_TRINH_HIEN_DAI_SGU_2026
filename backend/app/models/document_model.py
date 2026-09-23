"""Nghiệp vụ tài liệu và job: upload, đọc trạng thái, xuất DOCX."""
import logging
import shutil
from pathlib import Path
from typing import Optional, Tuple

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError, document_not_found, job_not_found
from backend.app.models import pipeline_model
from backend.app.models.database import Document, DocumentStatus, Job
from backend.app.views.schemas import DocumentOut, ErrorInfo, JobOut

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


# document
def get_document(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise document_not_found(document_id)
    return doc


def _latest_job(db: Session, document_id: str) -> Optional[Job]:
    return db.scalar(select(Job).where(Job.document_id == document_id)
                     .order_by(Job.created_at.desc()).limit(1))


def create_document(db: Session, upload: UploadFile) -> Tuple[Document, Job]:
    settings = get_settings()
    filename = Path(upload.filename or "").name[:255]
    if not filename.lower().endswith(".pdf") or (upload.content_type or "") not in PDF_TYPES:
        raise AppError(415, "INVALID_FILE_TYPE", "Chỉ chấp nhận file PDF (.pdf).")

    first = upload.file.read(CHUNK)
    if not first:
        raise AppError(400, "EMPTY_FILE", "File rỗng.")
    if not first.startswith(b"%PDF-"):
        raise AppError(415, "INVALID_FILE_TYPE", "Nội dung file không phải PDF hợp lệ.")

    doc = Document(filename=filename)
    db.add(doc)
    db.flush()                                    # để có doc.id
    pdf_path = settings.pdf_path(doc.id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with open(pdf_path, "wb") as out:
            chunk = first
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise AppError(413, "FILE_TOO_LARGE",
                                   f"File vượt quá giới hạn {settings.max_upload_mb} MB.")
                out.write(chunk)
                chunk = upload.file.read(CHUNK)
        job = Job(document_id=doc.id)
        db.add(job)
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(settings.doc_dir(doc.id), ignore_errors=True)
        raise

    pipeline_model.submit_pipeline(doc.id, job.id)
    logger.info("Đã nhận tài liệu %s (%d bytes), job %s", doc.id, size, job.id)
    return doc, job


def document_out(db: Session, document_id: str) -> DocumentOut:
    doc = get_document(db, document_id)
    job = _latest_job(db, doc.id)
    err = ErrorInfo(code=doc.error_code, message=doc.error_message or "") if doc.error_code else None
    return DocumentOut(
        id=doc.id, filename=doc.filename, status=doc.status, error=err,
        num_sections=doc.num_sections, num_chunks=doc.num_chunks,
        latest_job_id=job.id if job else None,
        docx_available=get_settings().docx_path(doc.id).exists(),
        created_at=doc.created_at, updated_at=doc.updated_at)


# job
def job_out(db: Session, job_id: str) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise job_not_found(job_id)
    err = ErrorInfo(code=job.error_code, message=job.error_message or "") if job.error_code else None
    return JobOut(id=job.id, document_id=job.document_id, status=job.status, stage=job.stage,
                  progress=job.progress, error=err, created_at=job.created_at,
                  started_at=job.started_at, finished_at=job.finished_at)


# export
def get_docx(db: Session, document_id: str) -> Tuple[Path, str]:
    """Trả về (đường dẫn file DOCX, tên file tải xuống)."""
    doc = get_document(db, document_id)
    path = get_settings().docx_path(doc.id)
    if not path.exists():
        if doc.status == DocumentStatus.failed:
            raise AppError(409, "DOCUMENT_FAILED",
                           "Xử lý tài liệu thất bại nên không có file DOCX.",
                           {"error": doc.error_code})
        raise AppError(409, "DOCUMENT_NOT_READY",
                       "File DOCX chưa được tạo. Hãy theo dõi trạng thái qua GET /jobs/{id}.",
                       {"status": doc.status})
    return path, f"{Path(doc.filename).stem}.docx"