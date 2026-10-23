"""Nghiệp vụ tài liệu và job: upload, đọc trạng thái, thử lại, liệt kê, xuất DOCX."""
import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from pypdf import PdfReader, PdfWriter

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError, document_not_found, job_not_found
from backend.app.models import pipeline_model
from backend.app.models.database import (DOC_ID_LEN, Document, DocumentStatus, Job,
                                         JobStatus, Message)
from backend.app.views.schemas import DocumentOut, ErrorInfo, JobOut

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
DOC_ID_RETRIES = 5   # số lần sinh lại doc_id nếu trùng (ID chỉ 10 ký tự hex = 40 bit)


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
    if not settings.ai_pipeline_enabled:
        raise AppError(503, "AI_WORKER_UNAVAILABLE",
                       "Máy chủ này chỉ chạy API; MinerU/RAG cần worker AI đủ RAM. "
                       "Hãy cấu hình AI_PIPELINE_ENABLED=true trên server đủ tài nguyên.")

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

    for _ in range(DOC_ID_RETRIES):
        doc = Document(filename=filename)         # id = new_doc_id(): 10 ký tự hex
        db.add(doc)
        try:
            db.flush()                            # để có doc.id (và phát hiện trùng khoá chính)
            break
        except IntegrityError:
            db.rollback()                         # trùng id (cực hiếm) -> sinh id khác
    else:
        raise AppError(500, "DOC_ID_GENERATION_FAILED",
                       f"Không sinh được doc_id {DOC_ID_LEN} ký tự không trùng, vui lòng thử lại.")
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
    if not settings.ai_pipeline_enabled:
        raise AppError(503, "AI_WORKER_UNAVAILABLE",
                       "Không thể retry vì máy chủ không chạy MinerU/RAG.")

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


def split_document(db: Session, document_id: str, ranges: List[dict]) -> List[Tuple[Document, Job]]:
    """Cắt PDF gốc thành nhiều Document con độc lập theo khoảng trang (1-based, bao gồm cả 2 đầu).
    ranges: [{"from": 1, "to": 20, "name": "Chương 1"}, ...]"""
    parent = get_document(db, document_id)
    settings = get_settings()
    if not settings.ai_pipeline_enabled:
        raise AppError(503, "AI_WORKER_UNAVAILABLE",
                       "Không thể xử lý PDF con vì AI pipeline chưa được bật.")
    src_path = settings.pdf_path(parent.id)
    if not src_path.exists():
        raise AppError(409, "PDF_MISSING", "Không tìm thấy PDF gốc để cắt.")

    reader = PdfReader(str(src_path))
    total_pages = len(reader.pages)

    for i, r in enumerate(ranges):
        f, t = r.get("from"), r.get("to")
        if not isinstance(f, int) or not isinstance(t, int) or f < 1 or t < f or t > total_pages:
            raise AppError(422, "INVALID_RANGE",
                           f"Khoảng trang #{i + 1} không hợp lệ (file có {total_pages} trang).",
                           {"range": r, "total_pages": total_pages})

    pending = pipeline_model.queue_depth(db)
    if pending + len(ranges) > settings.max_queued_jobs:
        raise AppError(429, "TOO_MANY_JOBS_QUEUED",
                       f"Cắt thành {len(ranges)} phần sẽ vượt giới hạn hàng đợi "
                       f"({settings.max_queued_jobs}). Giảm số phần hoặc thử lại sau.",
                       {"pending": pending, "requested": len(ranges)})

    results: List[Tuple[Document, Job]] = []
    for i, r in enumerate(ranges):
        name = (r.get("name") or f"{Path(parent.filename).stem} - phần {i + 1}").strip()
        filename = name if name.lower().endswith(".pdf") else f"{name}.pdf"
        filename = filename[:255]

        for _ in range(DOC_ID_RETRIES):
            child = Document(filename=filename, parent_document_id=parent.id)
            db.add(child)
            try:
                db.flush()
                break
            except IntegrityError:
                db.rollback()
        else:
            raise AppError(500, "DOC_ID_GENERATION_FAILED", "Không sinh được doc_id cho phần cắt.")

        writer = PdfWriter()
        for p in range(r["from"] - 1, r["to"]):
            writer.add_page(reader.pages[p])
        child_pdf_path = settings.pdf_path(child.id)
        child_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        with open(child_pdf_path, "wb") as f:
            writer.write(f)

        job = Job(document_id=child.id)
        db.add(job)
        db.commit()

        pipeline_model.submit_pipeline(child.id, job.id)
        results.append((child, job))
        logger.info("Cắt tài liệu %s -> phần %s '%s' (trang %d-%d)",
                    parent.id, child.id, filename, r["from"], r["to"])

    return results


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
        parent_document_id=doc.parent_document_id,
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


def delete_document(db: Session, document_id: str) -> None:
    doc = get_document(db, document_id)
    shutil.rmtree(get_settings().doc_dir(doc.id), ignore_errors=True)
    db.delete(doc)   # cascade xóa luôn Job, Message liên quan (đã khai báo ondelete="CASCADE")
    db.commit()


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