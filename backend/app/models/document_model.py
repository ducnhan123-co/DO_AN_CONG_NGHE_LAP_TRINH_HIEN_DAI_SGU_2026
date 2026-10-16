"""Nghiệp vụ tài liệu: upload (kiểm tra, băm sha256, đếm trang, cache), liệt kê, đổi tên, hủy, thử lại, xóa."""
import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError, document_not_found, job_not_found
from backend.app.models import job_model
from backend.app.models.database import ACTIVE, DOC_ID_LEN, Document, Job, StageRun, Status, now
from backend.app.models.pipeline import get_pipeline
from backend.app.models import storage
from backend.app.views.schemas import (DocumentDetail, DocumentOut, ErrorInfo, JobOut, ShardOut, StageRunOut,
                                       UploadItem, UploadRejected)

logger = logging.getLogger(__name__)

CHUNK = 1024 * 1024
PDF_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
DOC_ID_RETRIES = 5
CLIENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{0,64}")


def clean_client_id(value: Optional[str]) -> str:
    return value if value and CLIENT_ID_RE.fullmatch(value) else ""


# ------------------------------------------------------------------ truy vấn
def get_document(db: Session, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise document_not_found(doc_id)
    return doc


def active_job_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE))) or 0


def list_documents(db: Session, client_id: str = "", status: str = "", q: str = "",
                   limit: int = 50, offset: int = 0) -> Tuple[List[Document], int]:
    stmt = select(Document)
    if client_id:
        stmt = stmt.where(Document.client_id == client_id)
    if status == "active":
        stmt = stmt.where(Document.status.in_(ACTIVE))
    elif status == "failed":
        stmt = stmt.where(Document.status.in_([Status.failed.value, Status.cancelled.value]))
    elif status:
        stmt = stmt.where(Document.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.filename.ilike(like), Document.display_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return list(rows), total


# ------------------------------------------------------------------ tạo tài liệu
def _count_pages(path: Path) -> int:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise AppError(422, "PDF_ENCRYPTED", "PDF có mật khẩu, không thể xử lý.")
        n = len(reader.pages)
    except AppError:
        raise
    except Exception as exc:                                    # noqa: BLE001
        raise AppError(422, "INVALID_PDF", f"Không đọc được PDF: {str(exc)[:150]}") from exc
    if n < 1:
        raise AppError(422, "INVALID_PDF", "PDF không có trang nào.")
    return n


def _find_cached(db: Session, doc: Document) -> Optional[Document]:
    s = get_settings()
    rows = db.scalars(select(Document).where(Document.sha256 == doc.sha256, Document.tier == doc.tier,
                                             Document.status == Status.done.value, Document.id != doc.id)
                      .order_by(Document.finished_at.desc())).all()
    return next((r for r in rows if s.docx_path(r.id).exists()), None)


def create_document(db: Session, upload: UploadFile, client_id: str = "", force: bool = False) -> Tuple[Document, Job]:
    s = get_settings()
    if active_job_count(db) >= s.max_active_jobs:
        raise AppError(429, "TOO_MANY_JOBS", f"Đang có {s.max_active_jobs} file chờ xử lý. Vui lòng thử lại sau.")
    filename = Path(upload.filename or "").name[:255]
    if not filename.lower().endswith(".pdf") or (upload.content_type or "") not in PDF_TYPES:
        raise AppError(415, "INVALID_FILE_TYPE", "Chỉ chấp nhận file PDF (.pdf).")
    first = upload.file.read(CHUNK)
    if not first:
        raise AppError(400, "EMPTY_FILE", "File rỗng.")
    if not first.startswith(b"%PDF-"):
        raise AppError(415, "INVALID_FILE_TYPE", "Nội dung file không phải PDF hợp lệ.")

    doc = None
    for _ in range(DOC_ID_RETRIES):
        doc = Document(filename=filename, client_id=client_id, sha256="", tier=s.mineru_tier)
        db.add(doc)
        try:
            db.flush()
            break
        except IntegrityError:
            db.rollback()
            doc = None
    if doc is None:
        raise AppError(500, "DOC_ID_GENERATION_FAILED", f"Không sinh được mã tài liệu {DOC_ID_LEN} ký tự, thử lại.")
    pdf_path = s.pdf_path(doc.id)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    limit = s.max_upload_mb * 1024 * 1024
    h, size = hashlib.sha256(), 0
    try:
        with open(pdf_path, "wb") as out:
            chunk = first
            while chunk:
                size += len(chunk)
                if size > limit:
                    raise AppError(413, "FILE_TOO_LARGE", f"File vượt quá giới hạn {s.max_upload_mb} MB.")
                h.update(chunk)
                out.write(chunk)
                chunk = upload.file.read(CHUNK)
        doc.sha256, doc.size_bytes = h.hexdigest(), size
        doc.num_pages = _count_pages(pdf_path)

        cached = None if force else _find_cached(db, doc)
        if cached is not None:
            shutil.copy2(s.docx_path(cached.id), s.docx_path(doc.id))
            job = job_model.create_job(db, doc, status=Status.done.value, attempt=1)
            doc.cache_hit, doc.docx_size, doc.docx_sha256 = True, cached.docx_size, cached.docx_sha256
            job_model.set_status(db, job, doc, Status.done.value)
            db.add(StageRun(job_id=job.id, stage="cache", status="done", started_at=now(), finished_at=now(),
                            duration_s=0.0, note=json.dumps({"from_document": cached.id})))
            storage.sync_document(s, doc, job, list(job.stage_runs), artifacts=True, outputs=True)
            db.commit()
            logger.info("Tài liệu %s trùng sha256 với %s -> dùng lại DOCX", doc.id, cached.id)
            return doc, job
        job = job_model.create_job(db, doc)
        storage.sync_document(s, doc, job, list(job.stage_runs))
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(s.doc_dir(doc.id), ignore_errors=True)
        storage.remove_document_mirrors(s, doc)
        raise
    get_pipeline().submit(job.id)
    logger.info("Đã nhận %s (%d trang, %d bytes), job %s", doc.id, doc.num_pages, size, job.id)
    return doc, job


def create_documents(db: Session, uploads: List[UploadFile], client_id: str = "", force: bool = False):
    items: List[UploadItem] = []
    rejected: List[UploadRejected] = []
    first_error: Optional[AppError] = None
    for up in uploads:
        try:
            doc, job = create_document(db, up, client_id, force)
            items.append(UploadItem(document_id=doc.id, job_id=job.id, filename=doc.filename, status=doc.status,
                                    cache_hit=doc.cache_hit))
        except AppError as exc:
            first_error = first_error or exc
            rejected.append(UploadRejected(filename=Path(up.filename or "").name or "(không tên)", code=exc.code,
                                           message=exc.message))
    if not items and first_error is not None:
        raise first_error                  # không file nào nhận được: trả đúng mã lỗi HTTP của file đầu tiên
    return items, rejected


# ------------------------------------------------------------------ thao tác
def rename_document(db: Session, doc_id: str, display_name: str) -> Document:
    doc = get_document(db, doc_id)
    doc.display_name = display_name.strip() or None
    db.commit()
    job = job_model.latest_job(db, doc.id)
    storage.sync_document(get_settings(), doc, job, list(job.stage_runs) if job else [], outputs=True)
    return doc


def delete_document(db: Session, doc_id: str) -> None:
    doc = get_document(db, doc_id)
    job = job_model.latest_job(db, doc.id)
    if doc.status in ACTIVE and job is not None:
        get_pipeline().cancel_job(job.id, wait_s=20)
    settings = get_settings()
    storage.remove_document_mirrors(settings, doc)
    shutil.rmtree(settings.doc_dir(doc.id))
    db.expire_all()
    db.delete(db.get(Document, doc_id))
    db.commit()


def cancel_document(db: Session, doc_id: str) -> Document:
    doc = get_document(db, doc_id)
    job = job_model.latest_job(db, doc.id)
    if doc.status not in ACTIVE or job is None:
        raise AppError(409, "DOCUMENT_NOT_ACTIVE", "Tài liệu không còn đang xử lý nên không thể hủy.", {"status": doc.status})
    job.cancel_requested = True
    db.commit()
    get_pipeline().cancel_job(job.id)
    db.expire_all()
    return get_document(db, doc_id)


def retry_document(db: Session, doc_id: str) -> Tuple[Document, Job]:
    s = get_settings()
    doc = get_document(db, doc_id)
    if doc.status not in (Status.failed.value, Status.cancelled.value):
        raise AppError(409, "DOCUMENT_NOT_RETRYABLE", "Chỉ thử lại được tài liệu đã lỗi hoặc đã hủy.", {"status": doc.status})
    if not s.pdf_path(doc.id).exists():
        raise AppError(409, "PDF_MISSING", "Không còn file PDF gốc, cần upload lại.")
    if active_job_count(db) >= s.max_active_jobs:
        raise AppError(429, "TOO_MANY_JOBS", f"Đang có {s.max_active_jobs} file chờ xử lý. Vui lòng thử lại sau.")
    last = job_model.latest_job(db, doc.id)
    job = job_model.create_job(db, doc, attempt=(last.attempt + 1) if last else 1)
    job_model.set_status(db, job, doc, Status.queued.value, progress=0)
    db.commit()
    storage.sync_document(s, doc, job, list(job.stage_runs))
    get_pipeline().submit(job.id)
    return doc, job


# ------------------------------------------------------------------ chuyển sang schema
def _stage_out(r: StageRun) -> StageRunOut:
    return StageRunOut(id=r.id, stage=r.stage, shard_index=r.shard_index, page_from=r.page_from, page_to=r.page_to,
                       slot=r.slot, status=r.status, attempt=r.attempt, started_at=r.started_at, finished_at=r.finished_at,
                       duration_s=r.duration_s, peak_ram_gb=r.peak_ram_gb, note=job_model.note_json(r))


def document_out(db: Session, doc: Document, detail: bool = False):
    s = get_settings()
    job = job_model.latest_job(db, doc.id)
    runs = list(job.stage_runs) if job else []
    t = now()
    shards = []
    for run in runs:
        if run.stage != "parse":
            continue
        parts = (job_model.note_json(run) or {}).get("parts", [])
        if parts:
            shards.extend(
                ShardOut(
                    index=part["index"],
                    page_from=part["page_from"],
                    page_to=part["page_to"],
                    status=part["status"],
                    progress=part.get("progress", 0.0),
                    elapsed_s=part.get("elapsed_s"),
                    peak_ram_gb=part.get("peak_ram_gb"),
                    error=part.get("error"),
                )
                for part in parts
            )
        elif run.shard_index:
            shards.append(ShardOut(index=run.shard_index, page_from=run.page_from or 0, page_to=run.page_to or 0,
                                   status=run.status, slot=run.slot, duration_s=run.duration_s,
                                   progress=100.0 if run.status == "done" else 0.0))
    shards.sort(key=lambda x: x.index)
    err = ErrorInfo(code=doc.error_code, message=doc.error_message or "") if doc.error_code else None
    end = doc.finished_at if doc.status not in ACTIVE else t
    base = dict(id=doc.id, filename=doc.filename, display_name=doc.display_name, name=doc.display_name or doc.filename,
                status=doc.status, progress=job_model.estimate_progress(job, runs, s, t, doc.tier) if job else 0.0,
                num_pages=doc.num_pages, size_bytes=doc.size_bytes, tier=doc.tier, error=err, cache_hit=doc.cache_hit,
                docx_available=doc.status == Status.done.value and s.docx_path(doc.id).exists(), docx_size=doc.docx_size,
                created_at=doc.created_at, updated_at=doc.updated_at, finished_at=doc.finished_at,
                elapsed_s=round(max(0.0, (end or t) - doc.created_at), 1), job_id=job.id if job else None, shards=shards)
    if detail:
        return DocumentDetail(**base, stages=[_stage_out(r) for r in runs])
    return DocumentOut(**base)


def job_out(db: Session, job_id: str) -> JobOut:
    job = db.get(Job, job_id)
    if job is None:
        raise job_not_found(job_id)
    runs = list(job.stage_runs)
    err = ErrorInfo(code=job.error_code, message=job.error_message or "") if job.error_code else None
    return JobOut(id=job.id, document_id=job.document_id, status=job.status,
                  progress=job_model.estimate_progress(job, runs, get_settings(), tier=job.document.tier), attempt=job.attempt, error=err,
                  created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
                  stages=[_stage_out(r) for r in runs])
