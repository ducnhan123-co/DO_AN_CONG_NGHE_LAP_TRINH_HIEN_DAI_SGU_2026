"""Chạy nền 1 job/lần, gọi pipeline llm/src/* (MinerU -> structured -> chunk block -> LlamaIndex).

Đây là file DUY NHẤT import trực tiếp llm/.
"""
import json
import logging
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
_fast_executor: Optional[ThreadPoolExecutor] = None   # giai đoạn 1: đọc nhanh bằng pypdf -> chat được sớm
_executor: Optional[ThreadPoolExecutor] = None        # giai đoạn 2: MinerU + chỉ mục chuẩn (nâng cấp ngầm)
_docx_executor: Optional[ThreadPoolExecutor] = None   # DOCX: 1 worker riêng, không tranh CPU với chat/index

# MinerU và embedding đều rất nặng CPU/GPU: dù có nhiều worker pipeline thì mỗi loại
# vẫn chỉ chạy 1 tài liệu một lúc, nhưng tài liệu A đang embed thì B đã được chạy MinerU.
_mineru_lock = threading.Lock()
_embed_lock = threading.Lock()
_rag_swap_lock = threading.Lock()   # đọc chỉ mục từ đĩa và hoán đổi chỉ mục nhanh -> chuẩn không được chồng nhau

PARSER_FILE = "parser.txt"          # 'pypdf' (đang chạy bản nhanh, chờ MinerU) | 'mineru' | 'mineru_failed'

#  nạp / tìm chỉ mục
def clear_cache() -> None:
    with _lock:
        _index_cache.clear()


def load_index(doc_id: str) -> Any:
    with _lock:
        if doc_id in _index_cache:
            return _index_cache[doc_id]
    rag_dir = get_settings().rag_dir(doc_id)
    with _rag_swap_lock:     # không đọc giữa lúc đang hoán đổi chỉ mục nhanh -> chuẩn
        if not rag_dir.exists() or not any(rag_dir.iterdir()):
            raise AppError(500, "INDEX_NOT_FOUND", "Không tìm thấy chỉ mục của tài liệu.")
        from llm.src.config import EMBED_MODEL
        from llm.src.llama_rag import load_index as _load_index
        idx = _load_index(rag_dir, EMBED_MODEL)
        with _lock:
            _index_cache[doc_id] = idx
    return idx


def parser_state(doc_id: str) -> Optional[str]:
    """'pypdf' | 'mineru' | 'mineru_failed' | None (tài liệu cũ, chưa có file đánh dấu)."""
    try:
        return (get_settings().doc_dir(doc_id) / PARSER_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _set_parser(doc_id: str, value: str) -> None:
    try:
        (get_settings().doc_dir(doc_id) / PARSER_FILE).write_text(value, encoding="utf-8")
    except OSError:
        logger.warning("Không ghi được %s cho %s", PARSER_FILE, doc_id)


def search(doc_id: str, question: str, top_k: int) -> List[dict]:
    from llm.src.llama_rag import retrieve
    idx = load_index(doc_id)
    return retrieve(idx, question, top_k)


#  trạng thái job
def _running(db: Session, doc: Document, job: Job, stage: DocumentStatus, progress: int,
             touch_doc: bool = True) -> None:
    """touch_doc=False: đang nâng cấp ngầm lên MinerU, tài liệu đã 'ready' bằng bản nhanh -> chỉ
    cập nhật tiến độ job, KHÔNG đổi trạng thái tài liệu (nếu không chat sẽ bị khóa lại)."""
    job.status = JobStatus.running.value
    job.stage = stage.value
    job.progress = progress
    if job.started_at is None:
        job.started_at = utcnow()
    if touch_doc:
        doc.status = stage.value
    db.commit()


def _fast_ready(db: Session, doc: Document, job: Job, num_sections: int, num_chunks: int) -> None:
    """Bản đọc nhanh xong: tài liệu chat được ngay; job vẫn 'running' (MinerU nâng cấp ở nền)."""
    doc.status = DocumentStatus.ready.value
    doc.num_sections = num_sections
    doc.num_chunks = num_chunks
    doc.error_code = doc.error_message = None
    job.stage = DocumentStatus.mineru_parsing.value
    job.progress = 10
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
        message = ("Máy chủ khởi động lại khi đang xử lý. Vui lòng thử lại (POST /documents/{id}/retry) "
                   "hoặc upload lại nếu file gốc không còn.")
        doc = job.document
        if doc.status == DocumentStatus.ready.value:
            # đã có bản đọc nhanh phục vụ chat: chỉ báo nâng cấp MinerU bị gián đoạn, tài liệu vẫn dùng được
            job.status = JobStatus.failed.value
            job.error_code, job.error_message = "SERVER_RESTARTED", message
            job.finished_at = utcnow()
            db.commit()
            _set_parser(doc.id, "mineru_failed")
        else:
            _failed(db, doc, job, "SERVER_RESTARTED", message)
    return len(stale)


def queue_depth(db: Session) -> int:
    from sqlalchemy import func
    return db.scalar(select(func.count()).select_from(Job).where(
        Job.status.in_([JobStatus.queued.value, JobStatus.running.value]))) or 0


#  DOCX chạy nền (không chặn chat)
def _build_docx_background(doc_id: str, work_md, docx_path, images_dir, flag_path) -> None:
    """Chạy trong executor DOCX riêng. Lỗi KHÔNG làm fail cả tài liệu — chỉ ghi cờ
    docx_failed.flag để compat_controller báo docx='failed', chat vẫn dùng được.

    Ghi ra file tạm rồi os.replace: md_to_docx còn hậu xử lý (font, canh lề...) sau khi
    pandoc xong, nên không được để output.docx xuất hiện khi chưa hoàn chỉnh (nếu không
    API sẽ báo docx='ready' và cho tải file dở). Tên tạm phải kết thúc .docx để pandoc
    suy ra định dạng."""
    tmp_path = docx_path.with_name(docx_path.stem + ".building.docx")
    try:
        flag_path.unlink(missing_ok=True)
        docx_path.unlink(missing_ok=True)     # bản cũ (vd. sau retry) -> trạng thái 'building' đúng thực tế
        tmp_path.unlink(missing_ok=True)
        from llm.src.build_docx import md_to_docx
        md_to_docx(work_md, tmp_path, images_dir)
        os.replace(tmp_path, docx_path)
        logger.info("DOCX xong (nền): %s", docx_path)
    except Exception as e:                            # noqa: BLE001
        logger.exception("Xuất DOCX lỗi (doc=%s)", doc_id)
        tmp_path.unlink(missing_ok=True)
        flag_path.write_text(str(e)[:500], encoding="utf-8")


#  chạy pipeline
class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


MIN_FAST_CHARS_PER_PAGE = 80   # dưới mức này coi như PDF scan -> không có đường đọc nhanh


def _fast_raw_blocks(pdf_path: Path) -> List[dict]:
    """Đọc nhanh PDF chữ bằng pypdf -> block kiểu content_list của MinerU (có page_idx), để dùng
    chung structured/chunking/LlamaIndex. Trả [] nếu là PDF scan hoặc lớp chữ quá nghèo."""
    from pypdf import PdfReader
    from llm.latex_norm import fix_vni
    reader = PdfReader(str(pdf_path))
    n_pages = len(reader.pages)
    raw: List[dict] = []
    pages_with_text = total = 0
    for i, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:                      # noqa: BLE001
            text = ""
        total += len(text)
        if len(text) >= 50:
            pages_with_text += 1
        if not text:
            continue
        for para in re.split(r"\n\s*\n", fix_vni(text)):
            para = re.sub(r"\s*\n\s*", " ", para).strip()
            if len(para) >= 2:
                raw.append({"type": "text", "text": para, "page_idx": i})
    if n_pages == 0 or pages_with_text < 0.6 * n_pages or total < MIN_FAST_CHARS_PER_PAGE * n_pages:
        return []
    return raw


def _swap_rag(doc_id: str, new_dir: Path, live_dir: Path) -> None:
    """Thay chỉ mục nhanh bằng chỉ mục MinerU. Chat đang đọc thì chờ khóa vài ms; lỗi giữa chừng thì hoàn tác."""
    old = live_dir.with_name("rag_old")
    with _rag_swap_lock:
        shutil.rmtree(old, ignore_errors=True)
        os.replace(live_dir, old)
        try:
            os.replace(new_dir, live_dir)
        except Exception:
            os.replace(old, live_dir)
            raise
        with _lock:
            _index_cache.pop(doc_id, None)
    shutil.rmtree(old, ignore_errors=True)


def _fast_phase(document_id: str, job_id: str) -> bool:
    """Giai đoạn 1: pypdf -> chunk -> chỉ mục. Xong là tài liệu 'ready' (chat được) trong vài chục giây,
    không chờ MinerU/DOCX. Mọi lỗi ở đây chỉ có nghĩa 'không có đường nhanh' -> trả False, MinerU vẫn chạy."""
    settings = get_settings()
    doc_dir, rag_dir = settings.doc_dir(document_id), settings.rag_dir(document_id)
    with SessionLocal() as db:
        doc, job = db.get(Document, document_id), db.get(Job, job_id)
        if doc is None or job is None:
            logger.error("Không tìm thấy document/job (%s, %s)", document_id, job_id)
            return False
        try:
            from llm.src.chunking import build_chunks
            from llm.src.config import EMBED_MODEL, MAX_CHARS, OVERLAP
            from llm.src.llama_rag import build_index, chunks_to_nodes
            from llm.src.structured import normalize_blocks, save_structured

            _running(db, doc, job, DocumentStatus.indexing, 5)
            raw = _fast_raw_blocks(settings.pdf_path(document_id))
            if not raw:
                logger.info("Tài liệu %s: không có lớp chữ đủ tốt -> bỏ qua đọc nhanh, chờ MinerU", document_id)
                return False
            blocks = normalize_blocks(raw, source=doc.filename, doc_id=document_id)
            chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
            if not chunks:
                return False
            save_structured(blocks, doc_dir / "structured_data.json")
            shutil.rmtree(rag_dir, ignore_errors=True)
            rag_dir.mkdir(parents=True, exist_ok=True)
            with _embed_lock:
                build_index(chunks_to_nodes(chunks), EMBED_MODEL, rag_dir)
            with _lock:
                _index_cache.pop(document_id, None)
            _set_parser(document_id, "pypdf")
            _fast_ready(db, doc, job, len({c["section"] for c in chunks}), len(chunks))
            logger.info("Tài liệu %s: ĐỌC NHANH xong (%d chunks) -> chat được, MinerU nâng cấp ở nền",
                        document_id, len(chunks))
            return True
        except Exception:                          # noqa: BLE001
            logger.exception("Đọc nhanh lỗi (doc=%s) -> chờ MinerU", document_id)
            db.rollback()
            shutil.rmtree(rag_dir, ignore_errors=True)
            (doc_dir / PARSER_FILE).unlink(missing_ok=True)
            return False


def _upgrade_failed(document_id: str, job_id: str, code: str, message: str) -> None:
    """MinerU hỏng khi tài liệu đã chat được bằng bản nhanh: báo job lỗi nhưng GIỮ tài liệu 'ready'."""
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.failed.value
                job.error_code, job.error_message = code, message
                job.finished_at = utcnow()
                db.commit()
    except Exception:                              # noqa: BLE001
        logger.exception("Không ghi được lỗi nâng cấp (doc=%s)", document_id)
    _set_parser(document_id, "mineru_failed")


def _full_phase(document_id: str, job_id: str, upgrade: bool) -> None:
    """Giai đoạn 2: MinerU -> (DOCX nền) -> structured -> chunk -> chỉ mục chuẩn.
    upgrade=True: đã có bản nhanh -> không đổi trạng thái tài liệu, dựng chỉ mục mới rồi hoán đổi."""
    settings = get_settings()
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        job = db.get(Job, job_id)
        if doc is None or job is None:
            logger.error("Không tìm thấy document/job (%s, %s)", document_id, job_id)
            return
        touch = not upgrade
        try:
            from llm.src.build_docx import fix_legacy_tex_bf, prepare_work_md
            from llm.src.chunking import build_chunks
            from llm.src.config import (EMBED_MODEL, MAX_CHARS, MINERU_DEVICE,
                                        MINERU_LANG, MINERU_METHOD, MINERU_TIER,
                                        OVERLAP)
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
            _running(db, doc, job, DocumentStatus.mineru_parsing, 10, touch_doc=touch)
            _method = MINERU_METHOD
            if _method == "auto":
                _method = "txt" if has_extractable_text(pdf_path) else "ocr"
                logger.info("Tài liệu %s: PDF %s -> MinerU method=%s",
                            doc.id, "chữ" if _method == "txt" else "scan", _method)
            with _mineru_lock:
                run_mineru(pdf_path, mineru_dir, tier=MINERU_TIER, method=_method,
                           lang=MINERU_LANG, device=MINERU_DEVICE)
            content_list_path = find_content_list(mineru_dir)
            md_path, _, _ = find_mineru_outputs(mineru_dir)
            markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
            # Fix `{\bf X}` -> `\mathbf{X}`: pandoc/texmath không hiểu \bf, công thức
            # bị fallback về text thô nếu không fix -- dùng chung cho DOCX lẫn RAG.
            markdown_text = fix_legacy_tex_bf(markdown_text)
            if not markdown_text.strip():
                raise PipelineError("EMPTY_MARKDOWN", "MinerU không trích xuất được nội dung.")

            # 2. Chuẩn bị Markdown cho DOCX rồi XUẤT WORD Ở NỀN (executor riêng) -- không chặn bước 3-4.
            _running(db, doc, job, DocumentStatus.building_docx, 30, touch_doc=touch)
            work_md = doc_dir / "work_for_docx.md"
            prepare_work_md(markdown_text, md_path, work_md)
            docx_future = _submit_docx(doc.id, work_md, docx_path, md_path.parent, docx_flag)

            # 3. Structured blocks + chunk theo BLOCK -- chạy NGAY, song song với DOCX
            _running(db, doc, job, DocumentStatus.indexing, 55, touch_doc=touch)
            raw = load_raw(content_list_path, md_path, md_text=markdown_text)
            blocks = normalize_blocks(raw, source=doc.filename, doc_id=doc.id)
            chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
            if not chunks:
                raise PipelineError("NO_CHUNKS", "Tài liệu không có nội dung để lập chỉ mục.")

            report = validate_chunks(chunks, doc.filename, doc.id)
            (doc_dir / "validation.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not report["ok"]:
                logger.warning("Tài liệu %s: %d vấn đề validate_chunks (%s)",
                               doc.id, len(report["problems"]), report["problems"][:5])

            # 4. LlamaIndex. Có bản nhanh: dựng vào rag_new rồi hoán đổi (chat không bị gián đoạn).
            nodes = chunks_to_nodes(chunks)
            target = doc_dir / "rag_new" if upgrade else rag_dir
            if upgrade:
                shutil.rmtree(target, ignore_errors=True)
            with _embed_lock:
                build_index(nodes, EMBED_MODEL, target)
            if upgrade:
                _swap_rag(doc.id, target, rag_dir)
                save_structured(blocks, doc_dir / "structured_data.json")   # _page_blocks đọc file này
            else:
                save_structured(blocks, doc_dir / "structured_data.json")
                with _lock:
                    _index_cache.pop(doc.id, None)

            n_sections = len({c["section"] for c in chunks})
            _succeeded(db, doc, job, n_sections, len(chunks))
            _set_parser(doc.id, "mineru")
            logger.info("Hoàn tất tài liệu %s: %d sections, %d chunks (DOCX %s)",
                        doc.id, n_sections, len(chunks),
                        "vẫn đang xuất ở nền" if not docx_future.done() else "đã xong")
        except PipelineError as e:
            db.rollback()
            if upgrade:
                _upgrade_failed(document_id, job_id, e.code, e.message)
            else:
                _failed(db, doc, job, e.code, e.message)
        except Exception as e:                       # noqa: BLE001
            logger.exception("Pipeline lỗi (doc=%s)", document_id)
            db.rollback()
            if upgrade:
                _upgrade_failed(document_id, job_id, "PIPELINE_FAILED", str(e)[:500])
            else:
                _failed(db, doc, job, "PIPELINE_FAILED", str(e)[:500])


def _run_fast_stage(document_id: str, job_id: str) -> None:
    try:
        fast_ok = _fast_phase(document_id, job_id)
    except Exception:                                # noqa: BLE001
        logger.exception("Giai đoạn đọc nhanh lỗi (doc=%s)", document_id)
        fast_ok = False
    try:
        _get_executor().submit(_full_phase, document_id, job_id, fast_ok)
    except RuntimeError:                             # executor đã đóng (server đang tắt)
        logger.warning("Bỏ giai đoạn MinerU của %s vì server đang tắt", document_id)


def run_pipeline(document_id: str, job_id: str) -> None:
    """Chạy đồng bộ cả 2 giai đoạn (dùng cho test/CLI). Production dùng submit_pipeline."""
    fast_ok = _fast_phase(document_id, job_id)
    _full_phase(document_id, job_id, fast_ok)


# hàng đợi nền
def _get_fast_executor() -> ThreadPoolExecutor:
    global _fast_executor
    with _lock:
        if _fast_executor is None:
            _fast_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fastread")
        return _fast_executor


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            workers = max(1, int(getattr(get_settings(), "pipeline_workers", 2)))
            _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pipeline")
        return _executor


def submit_pipeline(document_id: str, job_id: str):
    # đọc nhanh có hàng đợi riêng: tài liệu mới chat được ngay cả khi MinerU của tài liệu trước còn chạy
    return _get_fast_executor().submit(_run_fast_stage, document_id, job_id)


def _submit_docx(doc_id: str, work_md, docx_path, images_dir, flag_path):
    global _docx_executor
    with _lock:
        if _docx_executor is None:
            _docx_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docx")
        ex = _docx_executor
    return ex.submit(_build_docx_background, doc_id, work_md, docx_path, images_dir, flag_path)


def shutdown() -> None:
    global _fast_executor, _executor, _docx_executor
    with _lock:
        pools = (_fast_executor, _executor, _docx_executor)
        _fast_executor = _executor = _docx_executor = None
    for ex in pools:
        if ex is not None:
            ex.shutdown(wait=False, cancel_futures=True)