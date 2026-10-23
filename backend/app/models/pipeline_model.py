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

DOCX_FAILED_FLAG = "docx_failed.flag"

_lock = threading.Lock()
_index_cache: Dict[str, Any] = {}
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
    job.status = JobStatus.failed.value
    job.error_code = code
    job.error_message = message
    job.finished_at = utcnow()
    doc.status = DocumentStatus.failed.value
    doc.error_code = code
    doc.error_message = message
    db.commit()


def fail_stale_jobs(db: Session) -> int:
    stale = db.scalars(select(Job).where(
        Job.status.in_([JobStatus.queued.value, JobStatus.running.value]))).all()
    for job in stale:
        _failed(db, job.document, job, "SERVER_RESTARTED",
                "Máy chủ khởi động lại khi đang xử lý. Vui lòng thử lại (POST /documents/{id}/retry) "
                "hoặc upload lại nếu file gốc không còn.")
    return len(stale)


def queue_depth(db: Session) -> int:
    from sqlalchemy import func
    return db.scalar(select(func.count()).select_from(Job).where(
        Job.status.in_([JobStatus.queued.value, JobStatus.running.value]))) or 0


#  DOCX chạy nền (không chặn chat)
def _build_docx_background(doc_id: str, work_md, docx_path, images_dir, flag_path) -> None:
    """Chạy trong thread riêng. Lỗi KHÔNG làm fail cả tài liệu — chỉ ghi cờ
    docx_failed.flag để compat_controller báo docx='failed', chat vẫn dùng được."""
    import zipfile
    from pathlib import Path

    docx_path = Path(docx_path)
    building_path = docx_path.with_name(f".{docx_path.stem}.building.docx")
    try:
        flag_path.unlink(missing_ok=True)
        building_path.unlink(missing_ok=True)
        from llm.src.build_docx import md_to_docx
        md_to_docx(work_md, building_path, images_dir)
        if not building_path.is_file() or building_path.stat().st_size == 0:
            raise ValueError("DOCX empty or missing")
        with zipfile.ZipFile(building_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"DOCX damaged member: {bad_member}")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("DOCX missing word/document.xml")
        # V3: only publish a complete valid DOCX, never a partial file.
        building_path.replace(docx_path)
        logger.info("Validated DOCX ready: %s", docx_path)
    except Exception as exc:
        logger.exception("DOCX generation failed for doc=%s", doc_id)
        flag_path.write_text(str(exc)[:500], encoding="utf-8")
    finally:
        building_path.unlink(missing_ok=True)


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
            from llm.src.build_docx import fix_legacy_tex_bf, prepare_work_md
            from llm.src.chunking import build_chunks
            from llm.src.config import (EMBED_MODEL, MAX_CHARS, MINERU_DEVICE,
                                        MINERU_LANG, MINERU_METHOD, MINERU_TIER,
                                        MINERU_WORKERS, OVERLAP)
            from llm.src.llama_rag import build_index, chunks_to_nodes
            from llm.src.run_mineru import (find_content_list,
                                            find_mineru_outputs,
                                            has_extractable_text, run_mineru)
            from llm.src.structured import (load_raw, normalize_blocks,
                                            save_structured)
            from llm.src.validate import validate_chunks

            pdf_path = settings.pdf_path(doc.id)
            mineru_dir = settings.mineru_dir(doc.id)
            rag_dir = settings.rag_dir(doc.id)
            docx_path = settings.docx_path(doc.id)
            doc_dir = settings.doc_dir(doc.id)
            docx_flag = doc_dir / DOCX_FAILED_FLAG
            for d in (mineru_dir, rag_dir):
                d.mkdir(parents=True, exist_ok=True)

            # 1. MinerU (tự bỏ qua nếu run này đã có output, vd. sau retry).
            # PDF chữ -> method 'txt' (bỏ OCR, nhanh gấp nhiều lần); PDF scan -> 'ocr'.
            _running(db, doc, job, DocumentStatus.mineru_parsing, 10)
            _method = MINERU_METHOD
            if _method == "auto":
                _method = "txt" if has_extractable_text(pdf_path) else "ocr"
                logger.info("Tài liệu %s: PDF %s -> MinerU method=%s",
                            doc.id, "chữ" if _method == "txt" else "scan", _method)
            run_mineru(pdf_path, mineru_dir, tier=MINERU_TIER, method=_method,
                       lang=MINERU_LANG, device=MINERU_DEVICE, workers=MINERU_WORKERS)
            content_list_path = find_content_list(mineru_dir)
            md_path, _, _ = find_mineru_outputs(mineru_dir)
            markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
            # Fix `{\bf X}` -> `\mathbf{X}`: pandoc/texmath không hiểu \bf, công thức
            # bị fallback về text thô nếu không fix -- dùng chung cho DOCX lẫn RAG.
            markdown_text = fix_legacy_tex_bf(markdown_text)
            if not markdown_text.strip():
                raise PipelineError("EMPTY_MARKDOWN", "MinerU không trích xuất được nội dung.")

            # 2. Chuẩn bị Markdown cho DOCX rồi XUẤT WORD Ở NỀN -- không chặn bước 3-4.
            # DOCX (pandoc) có thể mất vài phút với file dài; RAG index nhanh hơn nhiều
            # -> tách luồng để chat dùng được ngay khi index xong.
            _running(db, doc, job, DocumentStatus.building_docx, 30)
            work_md = doc_dir / "work_for_docx.md"
            prepare_work_md(markdown_text, md_path, work_md)
            docx_thread = threading.Thread(
                target=_build_docx_background,
                args=(doc.id, work_md, docx_path, md_path.parent, docx_flag),
                daemon=True, name=f"docx-{doc.id}")
            docx_thread.start()

            # 3. Structured blocks + chunk theo BLOCK -- chạy NGAY, song song với DOCX
            _running(db, doc, job, DocumentStatus.indexing, 55)
            raw = load_raw(content_list_path, md_path, md_text=markdown_text)
            blocks = normalize_blocks(raw, source=doc.filename, doc_id=doc.id)
            save_structured(blocks, doc_dir / "structured_data.json")
            chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
            if not chunks:
                raise PipelineError("NO_CHUNKS", "Tài liệu không có nội dung để lập chỉ mục.")

            # V3 artifacts: make chunks visible even if building the E5 index fails.
            (doc_dir / "chunks.json").write_text(
                json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
            doc.num_chunks = len(chunks)
            db.commit()

            report = validate_chunks(chunks, doc.filename, doc.id)
            (doc_dir / "validation.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not report["ok"]:
                logger.warning("Tài liệu %s: %d vấn đề validate_chunks (%s)",
                               doc.id, len(report["problems"]), report["problems"][:5])

            # 4. LlamaIndex -- xong bước này là CHAT DÙNG ĐƯỢC, bất kể docx_thread
            # (bước 2) đã xong hay chưa.
            nodes = chunks_to_nodes(chunks)
            build_index(nodes, EMBED_MODEL, rag_dir)
            with _lock:
                _index_cache.pop(doc.id, None)

            n_sections = len({c["section"] for c in chunks})
            _succeeded(db, doc, job, n_sections, len(chunks))
            logger.info("Hoàn tất tài liệu %s: %d sections, %d chunks (DOCX %s)",
                        doc.id, n_sections, len(chunks),
                        "vẫn đang xuất ở nền" if docx_thread.is_alive() else "đã xong")
        except PipelineError as e:
            db.rollback()
            _failed(db, doc, job, e.code, e.message)
        except Exception as e:                       # noqa: BLE001
            logger.exception("Pipeline lỗi (doc=%s)", document_id)
            db.rollback()
            _failed(db, doc, job, "PIPELINE_FAILED", str(e)[:500])


# hàng đợi nền
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