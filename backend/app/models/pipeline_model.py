"""Chạy nền 1 job/lần, gọi pipeline llm/src/* (MinerU -> structured -> chunk block -> LlamaIndex).

Đây là file DUY NHẤT import trực tiếp llm/.
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

_lock = threading.Lock()
_index_cache: Dict[str, Any] = {}          # doc_id -> LlamaIndex VectorStoreIndex đã nạp
_executor: Optional[ThreadPoolExecutor] = None


#  nạp / tìm chỉ mục
def clear_cache() -> None:
    with _lock:
        _index_cache.clear()


def load_index(doc_id: str) -> Any:
    with _lock:
        if doc_id in _index_cache:
            return _index_cache[doc_id]
    rag_dir = get_settings().rag_dir(doc_id)
    if not rag_dir.exists() or not any(rag_dir.iterdir()):
        raise AppError(500, "INDEX_NOT_FOUND", "Không tìm thấy chỉ mục của tài liệu.")
    from llm.src.config import EMBED_MODEL
    from llm.src.llama_rag import load_index as _load_index
    idx = _load_index(rag_dir, EMBED_MODEL)
    with _lock:
        _index_cache[doc_id] = idx
    return idx


def search(doc_id: str, question: str, top_k: int) -> List[dict]:
    """Trả về list dict: node_id, score, source, page, section, formula_latex, text."""
    from llm.src.llama_rag import retrieve
    idx = load_index(doc_id)
    return retrieve(idx, question, top_k)


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
            # Import muộn: tránh nạp MinerU/torch/LlamaIndex khi chỉ chạy API hoặc test.
            from llm.latex_norm import fix_vni, normalize_math_in_text
            from llm.src.build_docx import md_to_docx, prepare_work_md
            from llm.src.chunking import build_chunks
            from llm.src.config import EMBED_MODEL, MAX_CHARS, MINERU_TIER, OVERLAP
            from llm.src.llama_rag import build_index, chunks_to_nodes
            from llm.src.run_mineru import (find_content_list,
                                            find_mineru_outputs, run_mineru)
            from llm.src.structured import (load_raw, normalize_blocks,
                                            save_structured)
            from llm.src.validate import validate_chunks

            pdf_path = settings.pdf_path(doc.id)
            mineru_dir = settings.mineru_dir(doc.id)
            rag_dir = settings.rag_dir(doc.id)
            docx_path = settings.docx_path(doc.id)
            doc_dir = settings.doc_dir(doc.id)
            for d in (mineru_dir, rag_dir):
                d.mkdir(parents=True, exist_ok=True)

            # 1. MinerU (mineru-kit parse). Tự bỏ qua nếu run này đã có output (vd. sau retry).
            _running(db, doc, job, DocumentStatus.mineru_parsing, 5)
            run_mineru(pdf_path, mineru_dir, tier=MINERU_TIER)
            content_list_path = find_content_list(mineru_dir)
            md_path, _, _ = find_mineru_outputs(mineru_dir)
            # Sửa VNI + chuẩn hoá công thức để Pandoc ra Equation, và để structured/RAG
            # dùng chung một bản Markdown sạch (không lệch giữa DOCX và chat).
            markdown_text = normalize_math_in_text(fix_vni(
                md_path.read_text(encoding="utf-8", errors="ignore")))
            if not markdown_text.strip():
                raise PipelineError("EMPTY_MARKDOWN", "MinerU không trích xuất được nội dung.")

            # 2. Markdown -> DOCX
            _running(db, doc, job, DocumentStatus.building_docx, 40)
            work_md = doc_dir / "work_for_docx.md"
            prepare_work_md(markdown_text, md_path, work_md)
            md_to_docx(work_md, docx_path, md_path.parent)
            if not docx_path.exists():
                raise PipelineError("DOCX_NOT_CREATED", "Không tạo được file DOCX.")

            # 3. Structured blocks + chunk theo BLOCK (có trang thật, không base64,
            #    công thức/table không bị cắt đôi)
            _running(db, doc, job, DocumentStatus.indexing, 65)
            raw = load_raw(content_list_path, md_path, md_text=markdown_text)
            blocks = normalize_blocks(raw, source=doc.filename, doc_id=doc.id)
            save_structured(blocks, doc_dir / "structured_data.json")
            chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
            if not chunks:
                raise PipelineError("NO_CHUNKS", "Tài liệu không có nội dung để lập chỉ mục.")

            report = validate_chunks(chunks, doc.filename, doc.id)
            (doc_dir / "validation.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not report["ok"]:
                logger.warning("Tài liệu %s: %d vấn đề validate_chunks (%s)",
                               doc.id, len(report["problems"]), report["problems"][:5])

            # 4. LlamaIndex (E5) — tự lưu persist_dir, không cần tự ghi file như FAISS trước
            nodes = chunks_to_nodes(chunks)
            build_index(nodes, EMBED_MODEL, rag_dir)
            with _lock:
                _index_cache.pop(doc.id, None)   # xoá cache cũ nếu đây là lần retry

            n_sections = len({c["section"] for c in chunks})
            _succeeded(db, doc, job, n_sections, len(chunks))
            logger.info("Hoàn tất tài liệu %s: %d sections, %d chunks",
                        doc.id, n_sections, len(chunks))
        except PipelineError as e:
            db.rollback()
            _failed(db, doc, job, e.code, e.message)
        except Exception as e:                       # noqa: BLE001
            logger.exception("Pipeline lỗi (doc=%s)", document_id)
            db.rollback()
            _failed(db, doc, job, "PIPELINE_FAILED", str(e)[:500])


# hàng đợi nền
def submit_pipeline(document_id: str, job_id: str):
    """MinerU rất nặng: chỉ cho chạy 1 job tại một thời điểm."""
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