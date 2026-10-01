"""Nghiệp vụ tài liệu và job: upload, đọc trạng thái, thử lại, liệt kê, xuất DOCX."""
import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError, document_not_found, job_not_found
from backend.app.models import pipeline_model
from backend.app.models.database import Document, DocumentStatus, Job, JobStatus, Message
from backend.app.views.schemas import DocumentOut, ErrorInfo, JobOut

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


#  document
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

    pending = pipeline_model.queue_depth(db)
    if pending >= settings.max_queued_jobs:
        raise AppError(429, "TOO_MANY_JOBS_QUEUED",
                       f"Đang có {pending} job chờ xử lý, vượt giới hạn {settings.max_queued_jobs}. "
                       "Vui lòng thử lại sau.", {"pending": pending})

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


def retry_document(db: Session, document_id: str) -> Tuple[Document, Job]:
    """Thử lại pipeline cho tài liệu đã failed, dùng lại PDF đã lưu, không cần upload lại."""
    doc = get_document(db, document_id)
    settings = get_settings()

    if doc.status != DocumentStatus.failed.value:
        raise AppError(409, "DOCUMENT_NOT_FAILED",
                       "Chỉ có thể thử lại tài liệu ở trạng thái failed.",
                       {"status": doc.status})
    if not settings.pdf_path(doc.id).exists():
        raise AppError(409, "PDF_MISSING", "Không còn tìm thấy file PDF gốc, cần upload lại.")

    pending = pipeline_model.queue_depth(db)
    if pending >= settings.max_queued_jobs:
        raise AppError(429, "TOO_MANY_JOBS_QUEUED",
                       f"Đang có {pending} job chờ xử lý, vượt giới hạn {settings.max_queued_jobs}. "
                       "Vui lòng thử lại sau.", {"pending": pending})

    job = Job(document_id=doc.id)
    db.add(job)
    doc.status = DocumentStatus.queued.value
    doc.error_code = doc.error_message = None
    db.commit()

    pipeline_model.submit_pipeline(doc.id, job.id)
    logger.info("Thử lại tài liệu %s, job mới %s", doc.id, job.id)
    return doc, job


def list_documents(db: Session, limit: int = 20, offset: int = 0) -> Tuple[List[Document], int]:
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    rows = db.scalars(select(Document).order_by(Document.created_at.desc())
                      .limit(limit).offset(offset)).all()
    return rows, total


def document_out(db: Session, document_id: str) -> DocumentOut:
    doc = get_document(db, document_id)
    job = _latest_job(db, doc.id)
    err = ErrorInfo(code=doc.error_code, message=doc.error_message or "") if doc.error_code else None
    return DocumentOut(
        id=doc.id, filename=doc.filename, status=doc.status, error=err,
        num_sections=doc.num_sections, num_chunks=doc.num_chunks,
        message_count=_message_count(db, doc.id),  
        latest_job_id=job.id if job else None,
        docx_available=get_settings().docx_path(doc.id).exists(),
        created_at=doc.created_at, updated_at=doc.updated_at)


def _message_count(db: Session, document_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Message)
                     .where(Message.document_id == document_id)) or 0


def list_messages(db: Session, document_id: str) -> List[Message]:
    get_document(db, document_id)      # 404 nếu document không tồn tại
    return db.scalars(select(Message).where(Message.document_id == document_id)
                      .order_by(Message.created_at.asc())).all()


#  job
def job_out(db: Session, job_id: str) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise job_not_found(job_id)
    err = ErrorInfo(code=job.error_code, message=job.error_message or "") if job.error_code else None
    return JobOut(id=job.id, document_id=job.document_id, status=job.status, stage=job.stage,
                  progress=job.progress, error=err, created_at=job.created_at,
                  started_at=job.started_at, finished_at=job.finished_at)


#  export
def get_docx(db: Session, document_id: str) -> Tuple[Path, str]:
    """Trả về (đường dẫn file DOCX, tên file tải xuống)."""
    doc = get_document(db, document_id)
    path = get_settings().docx_path(doc.id)
    if not path.exists():
        if doc.status == DocumentStatus.failed.value:
            raise AppError(409, "DOCUMENT_FAILED",
                           "Xử lý tài liệu thất bại nên không có file DOCX.",
                           {"error": doc.error_code})
        raise AppError(409, "DOCUMENT_NOT_READY",
                       "File DOCX chưa được tạo. Hãy theo dõi trạng thái qua GET /jobs/{id}.",
                       {"status": doc.status})
    return path, f"{Path(doc.filename).stem}.docx"