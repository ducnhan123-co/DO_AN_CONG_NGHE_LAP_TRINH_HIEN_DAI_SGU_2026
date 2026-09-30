"""Chạy nền 1 job/lần, gọi pipeline gốc src/ (MinerU -> DOCX -> FAISS), lưu và tìm chỉ mục.

Đây là file DUY NHẤT import trực tiếp src/.
"""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.models.database import (Document, DocumentStatus, Job,
                                          JobStatus, SessionLocal, utcnow)

logger = logging.getLogger(__name__)

INDEX_FILE = "index.faiss"
CHUNKS_FILE = "chunks.json"

_lock = threading.Lock()
_cache: Dict[str, Tuple[Any, list]] = {}
_embedder: Optional[Any] = None
_executor: Optional[ThreadPoolExecutor] = None


#  lưu / nạp / tìm FAISS
def set_embedder(embedder: Any) -> None:
    global _embedder
    if embedder is not None:
        with _lock:
            _embedder = embedder


def get_embedder() -> Any:
    global _embedder
    with _lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer
            from src.config import EMBED_MODEL
            _embedder = SentenceTransformer(EMBED_MODEL)
        return _embedder


def save_index(doc_id: str, index: Any, chunks: list) -> None:
    import faiss
    d = get_settings().rag_dir(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(d / INDEX_FILE))
    (d / CHUNKS_FILE).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    with _lock:
        _cache.pop(doc_id, None)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def load_index(doc_id: str) -> Tuple[Any, list]:
    with _lock:
        if doc_id in _cache:
            return _cache[doc_id]
    d = get_settings().rag_dir(doc_id)
    if not (d / INDEX_FILE).exists() or not (d / CHUNKS_FILE).exists():
        raise AppError(500, "INDEX_NOT_FOUND", "Không tìm thấy chỉ mục của tài liệu.")
    import faiss
    index = faiss.read_index(str(d / INDEX_FILE))
    chunks = json.loads((d / CHUNKS_FILE).read_text(encoding="utf-8"))
    with _lock:
        _cache[doc_id] = (index, chunks)
    return index, chunks


def _text_of(chunk: Any) -> str:
    return chunk.get("text", "") if isinstance(chunk, dict) else str(chunk)


def search(doc_id: str, question: str, top_k: int) -> List[dict]:
    """Trả về list dict: chunk_id, heading, text, score."""
    from src.build_rag import retrieve

    index, chunks = load_index(doc_id)
    results = retrieve(question, get_embedder(), index, chunks, top_k)
    hits = []
    for r in results:
        text = r.get("text", "")
        chunk_id = r.get("chunk_id", r.get("id"))
        if chunk_id is None:
            chunk_id = next((i for i, c in enumerate(chunks) if _text_of(c) == text), None)
        hits.append({"chunk_id": chunk_id, "heading": r.get("heading") or "",
                     "text": text, "score": float(r.get("score", 0.0))})
    return hits


#  trạng thái job
def _running(db: Session, doc: Document, job: Job, stage: DocumentStatus, progress: int) -> None:
    job.status = JobStatus.running.value
    job.stage = stage.value
    job.progress = progress
    if job.started_at is None:
        job.started_at = utcnow()
    doc.status = stage.value
    db.commit()


def _succeeded(db: Session, doc: Document, job: Job, num_sections: int, num_chunks: int) -> None:
    job.status = JobStatus.succeeded.value
    job.stage = DocumentStatus.ready.value
    job.progress = 100
    job.finished_at = utcnow()
    doc.status = DocumentStatus.ready.value
    doc.num_sections = num_sections
    doc.num_chunks = num_chunks
    doc.error_code = doc.error_message = None
    db.commit()


def _failed(db: Session, doc: Document, job: Job, code: str, message: str) -> None:
    job.status = JobStatus.failed.value      # giữ nguyên job.stage = bước bị lỗi
    job.error_code = code
    job.error_message = message
    job.finished_at = utcnow()
    doc.status = DocumentStatus.failed.value
    doc.error_code = code
    doc.error_message = message
    db.commit()


def fail_stale_jobs(db: Session) -> int:
    """Job đang chạy dở khi server tắt đột ngột -> đánh dấu failed."""
    stale = db.scalars(select(Job).where(
        Job.status.in_([JobStatus.queued.value, JobStatus.running.value]))).all()
    for job in stale:
        _failed(db, job.document, job, "SERVER_RESTARTED",
                "Máy chủ khởi động lại khi đang xử lý. Vui lòng thử lại (POST /documents/{id}/retry) "
                "hoặc upload lại nếu file gốc không còn.")
    return len(stale)


def queue_depth(db: Session) -> int:
    """Số job đang queued hoặc running (dùng để giới hạn hàng đợi)."""
    from sqlalchemy import func
    return db.scalar(select(func.count()).select_from(Job).where(
        Job.status.in_([JobStatus.queued.value, JobStatus.running.value]))) or 0


#  chạy pipeline
class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def run_pipeline(document_id: str, job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        job = db.get(Job, job_id)
        if doc is None or job is None:
            logger.error("Không tìm thấy document/job (%s, %s)", document_id, job_id)
            return
        try:
            # Import muộn: tránh nạp MinerU/torch khi chỉ chạy API hoặc test.
            from src.build_docx import md_to_docx, prepare_work_md
            from src.build_rag import (build_index, make_chunks,
                                       split_markdown_sections)
            from src.config import EMBED_MODEL, MAX_CHARS, MINERU_BACKEND, OVERLAP
            from src.run_mineru import find_mineru_outputs, run_mineru

            pdf_path = settings.pdf_path(doc.id)
            mineru_dir = settings.mineru_dir(doc.id)
            rag_dir = settings.rag_dir(doc.id)
            docx_path = settings.docx_path(doc.id)
            for d in (mineru_dir, rag_dir):
                d.mkdir(parents=True, exist_ok=True)

            # 1. MinerU: PDF -> Markdown (bỏ qua nếu đã có kết quả từ lần chạy trước, vd. sau retry)
            _running(db, doc, job, DocumentStatus.mineru_parsing, 5)
            try:
                md_path, _, _ = find_mineru_outputs(mineru_dir)
                markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
                logger.info("Bỏ qua MinerU: đã có Markdown từ lần chạy trước (%s)", doc.id)
            except Exception:
                run_mineru(pdf_path, mineru_dir, backend=MINERU_BACKEND)
                md_path, _, _ = find_mineru_outputs(mineru_dir)
                markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
            if not markdown_text.strip():
                raise PipelineError("EMPTY_MARKDOWN", "MinerU không trích xuất được nội dung.")

            # 2. Markdown -> DOCX (bỏ qua nếu output.docx đã tồn tại)
            _running(db, doc, job, DocumentStatus.building_docx, 40)
            if not docx_path.exists():
                work_md = settings.doc_dir(doc.id) / "work_for_docx.md"
                prepare_work_md(markdown_text, md_path, work_md)
                md_to_docx(work_md, docx_path, md_path.parent)
            if not docx_path.exists():
                raise PipelineError("DOCX_NOT_CREATED", "Không tạo được file DOCX.")

            # 3. Chunk + embedding + FAISS
            _running(db, doc, job, DocumentStatus.indexing, 65)
            sections = split_markdown_sections(markdown_text)
            chunks = make_chunks(sections, max_chars=MAX_CHARS, overlap=OVERLAP)
            if not chunks:
                raise PipelineError("NO_CHUNKS", "Tài liệu không có nội dung để lập chỉ mục.")
            index, embedder, _, _ = build_index(chunks, EMBED_MODEL, rag_dir)
            set_embedder(embedder)
            save_index(doc.id, index, chunks)

            _succeeded(db, doc, job, len(sections), len(chunks))
            logger.info("Hoàn tất tài liệu %s: %d sections, %d chunks",
                        doc.id, len(sections), len(chunks))
        except PipelineError as e:
            db.rollback()
            _failed(db, doc, job, e.code, e.message)
        except Exception as e:                       # noqa: BLE001
            logger.exception("Pipeline lỗi (doc=%s)", document_id)
            db.rollback()
            _failed(db, doc, job, "PIPELINE_FAILED", str(e)[:500])


#  hàng đợi nền
def submit_pipeline(document_id: str, job_id: str):
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline")
        ex = _executor
    return ex.submit(run_pipeline, document_id, job_id)


def shutdown() -> None:
    global _executor
    with _lock:
        ex, _executor = _executor, None
    if ex is not None:
        ex.shutdown(wait=False, cancel_futures=True)