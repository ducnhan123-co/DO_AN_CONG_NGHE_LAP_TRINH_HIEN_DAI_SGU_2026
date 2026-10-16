"""Sequential PDF-to-DOCX job processing."""
import json
import contextlib
import hashlib
import io
import logging
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy import select

from backend.app.core.config import Settings, get_settings
from backend.app.engine import rag_toan
from backend.app.engine.mineru_runner import MinerUCancelled, MinerUError
from backend.app.models import job_model
from backend.app.models import storage
from backend.app.models.database import ACTIVE, Document, Job, SessionLocal, StageRun, Status, now

logger = logging.getLogger(__name__)
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


class Cancelled(Exception):
    pass


class PandocMissing(RuntimeError):
    pass


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@contextlib.contextmanager
def _captured_stdout(log_path: Path):
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            yield
    finally:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(output.getvalue())


def _count_md_formulas(text: str) -> int:
    display = re.findall(r"\$\$.+?\$\$", text, flags=re.S)
    remainder = re.sub(r"\$\$.+?\$\$", " ", text, flags=re.S)
    inline = re.findall(r"(?<![\\$])\$[^$\n]+?\$", remainder)
    return len(display) + len(inline)


def _prepare_markdown(markdown_path: Path, work_path: Path, log_path: Path, *,
                      content_list_path: Optional[Path], source: str, doc_id: str,
                      output_dir: Path) -> dict:
    text = markdown_path.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        raise ValueError("MinerU không trích xuất được nội dung (markdown rỗng).")
    text = rag_toan.fix_legacy_tex_bf(text)
    with _captured_stdout(log_path):
        rag_toan.prepare_work_md(text, markdown_path, work_path)
        assets = rag_toan.build_structured_assets(
            content_list_path, markdown_path, text, source, doc_id, output_dir)
    return {"md_chars": len(text), "formulas_md": _count_md_formulas(text), **assets}


def _build_docx(work_path: Path, resource_dir: Path, docx_path: Path, timeout_s: int,
                log_path: Path) -> dict:
    temporary = docx_path.with_name(docx_path.stem + ".building.docx")
    temporary.unlink(missing_ok=True)
    try:
        with _captured_stdout(log_path):
            rag_toan.md_to_docx(work_path, temporary, resource_dir, timeout_s=timeout_s)
    except FileNotFoundError as exc:
        temporary.unlink(missing_ok=True)
        raise PandocMissing("Chưa cài Pandoc hoặc không có trong PATH.") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(docx_path)
    return {"docx_bytes": docx_path.stat().st_size}


def _validate_docx(docx_path: Path, markdown: str) -> dict:
    from docx import Document as WordDocument

    doc = WordDocument(str(docx_path))
    paragraphs, tables, images = len(doc.paragraphs), len(doc.tables), len(doc.inline_shapes)
    equations = sum(1 for _ in doc.element.body.iter("{%s}oMath" % M_NS))
    if paragraphs == 0 and equations == 0 and tables == 0:
        raise ValueError("DOCX không có nội dung.")
    formulas = _count_md_formulas(markdown)
    info = {"paragraphs": paragraphs, "tables": tables, "images": images, "equations_docx": equations,
            "formulas_md": formulas, "bytes": docx_path.stat().st_size}
    if formulas and equations < 0.5 * formulas:
        info["warning"] = f"Chỉ {equations}/{formulas} công thức thành Equation."
    return info


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Pipeline:
    """Run one queued document at a time; HTTP handlers only enqueue jobs."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        self._queued = set()
        self._cancel_events: Dict[str, threading.Event] = {}
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._shutdown = False
        self._running_job: Optional[str] = None
        self._running_document: Optional[str] = None

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._shutdown = False
            self._recover()
            self._worker = threading.Thread(target=self._work, name="document-pipeline", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        with self._lock:
            self._shutdown = True
            self._stop.set()
            for event in self._cancel_events.values():
                event.set()
        if self._worker:
            self._worker.join(timeout=10)

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._queued or job_id == self._running_job:
                return
            self._queued.add(job_id)
            self._queue.put(job_id)

    def cancel_job(self, job_id: str, wait_s: float = 0) -> None:
        with self._lock:
            event = self._cancel_events.get(job_id)
            running = self._running_job == job_id
            if event:
                event.set()
        if not running:
            self._set_cancelled(job_id)
            return
        if wait_s:
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                with self._lock:
                    if self._running_job != job_id:
                        break
                time.sleep(0.05)

    def stats(self) -> dict:
        with self._lock:
            running = []
            mineru_processes = 0
            if self._running_job:
                running.append({"job_id": self._running_job, "document_id": self._running_document,
                                "stage": self._status_for_job(self._running_job)})
                with SessionLocal() as db:
                    parse_run = db.scalar(
                        select(StageRun).where(StageRun.job_id == self._running_job, StageRun.stage == "parse")
                        .order_by(StageRun.id.desc()).limit(1)
                    )
                    parts = (job_model.note_json(parse_run) or {}).get("parts", []) if parse_run else []
                    mineru_processes = sum(part.get("status") == "running" for part in parts)
            return {"main_slots": 1, "aux_mode": "off", "running": running,
                    "queued_tasks": self._queue.qsize(), "pending_jobs": self._queue.qsize(),
                    "active_jobs": self._queue.qsize() + len(running),
                    "mineru_processes": mineru_processes,
                    "mineru_workers": self.settings.mineru_workers,
                    "last_decision": "Đang xử lý một job; MinerU có thể chạy song song" if running else "Chờ job",
                    "resources": None}

    def _status_for_job(self, job_id: str) -> str:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            return job.status if job else "unknown"

    def _recover(self) -> None:
        ids = []
        with SessionLocal() as db:
            for job in db.scalars(select(Job).where(Job.status.in_(ACTIVE))).all():
                doc = db.get(Document, job.document_id)
                if doc is None:
                    continue
                if job.cancel_requested:
                    job_model.set_status(db, job, doc, Status.cancelled.value, error_code="CANCELLED",
                                         error_message="Đã hủy.")
                    continue
                for run in job.stage_runs:
                    if run.status == "running":
                        run.status = "failed"
                        run.finished_at = now()
                        run.note = json.dumps({"message": "Server khởi động lại khi bước đang chạy."})
                job_model.set_status(db, job, doc, Status.queued.value, progress=0)
                ids.append(job.id)
            db.commit()
        for job_id in ids:
            self.submit(job_id)
        if ids:
            logger.warning("Khôi phục %d job dở dang sau khi khởi động lại", len(ids))

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            with self._lock:
                self._queued.discard(job_id)
                event = self._cancel_events.setdefault(job_id, threading.Event())
                self._running_job = job_id
            try:
                self._run_job(job_id, event)
            except Exception:
                logger.exception("Pipeline lỗi ngoài dự kiến (job=%s)", job_id)
                self._fail_job(job_id, "PIPELINE_FAILED", "Pipeline gặp lỗi ngoài dự kiến; xem log backend để biết chi tiết.")
            finally:
                with self._lock:
                    self._cancel_events.pop(job_id, None)
                    self._running_job = None
                    self._running_document = None
                    self._queue.task_done()

    def _run_job(self, job_id: str, cancel: threading.Event) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            doc = db.get(Document, job.document_id)
            if doc is None or job.status not in ACTIVE:
                return
            doc_id = doc.id
            filename = doc.filename
            self._running_document = doc_id
            if job.cancel_requested:
                cancel.set()
        if cancel.is_set():
            if not self._shutdown:
                self._set_cancelled(job_id)
            return

        s = self.settings
        mineru_dir = s.mineru_dir(doc_id)
        log_path = s.logs_dir(doc_id) / "mineru.log"
        try:
            shutil.rmtree(mineru_dir, ignore_errors=True)
            shutil.rmtree(s.doc_dir(doc_id) / "mineru_parts", ignore_errors=True)
            mineru_dir.mkdir(parents=True, exist_ok=True)
            parse_run = self._start_stage(job_id, doc_id, "parse", Status.parsing.value, 5,
                                          page_from=1)
            with SessionLocal() as db:
                doc = db.get(Document, doc_id)
                run = db.get(StageRun, parse_run)
                if doc is None or run is None:
                    raise Cancelled()
                run.page_to = doc.num_pages
                db.commit()
                timeout_s = max(s.mineru_timeout_min_s, doc.num_pages * s.mineru_timeout_per_page_s)
                tier = doc.tier
            try:
                result = rag_toan.run_mineru_parallel(
                    s.pdf_path(doc_id), mineru_dir, cmd=s.mineru_cmd, tier=tier,
                    ocr_mode=s.mineru_ocr_mode, timeout_s=timeout_s, log_path=log_path,
                    cancel=cancel, workers=s.mineru_workers,
                    min_pages_per_worker=s.mineru_min_pages_per_worker,
                    stagger_s=s.mineru_stagger_s, fmt=s.mineru_format,
                    on_progress=lambda parts: self._update_parse_progress(parse_run, parts))
            except (MinerUError, MinerUCancelled) as exc:
                self._finish_stage(parse_run, "cancelled" if isinstance(exc, MinerUCancelled) else "failed",
                                   {"message": str(exc)})
                raise
            md_candidates = [p for p in mineru_dir.rglob("*.md") if p.is_file() and p.stat().st_size]
            if not md_candidates:
                self._finish_stage(parse_run, "failed", {"message": "MinerU không tạo markdown."})
                raise MinerUError("MINERU_BAD_OUTPUT", "MinerU không tạo file markdown không rỗng.")
            md_path = max(md_candidates, key=lambda p: p.stat().st_size)
            document_md = mineru_dir / "document.md"
            if md_path.resolve() != document_md.resolve():
                shutil.copy2(md_path, document_md)
            self._finish_stage(parse_run, "done", result)

            markdown = document_md.read_text(encoding="utf-8", errors="ignore")
            content_list_path = rag_toan.find_content_list(mineru_dir)
            self._run_step(job_id, doc_id, "prepare", Status.preparing.value, 86,
                           lambda log: _prepare_markdown(
                               document_md, s.work_md(doc_id), log,
                               content_list_path=content_list_path, source=filename,
                               doc_id=doc_id, output_dir=s.doc_dir(doc_id)))
            info = self._run_step(job_id, doc_id, "build", Status.building.value, 90,
                                  lambda log: _build_docx(s.work_md(doc_id), mineru_dir,
                                                          s.docx_path(doc_id), s.pandoc_timeout_s, log))
            validation = self._run_step(job_id, doc_id, "validate", Status.validating.value, 96,
                                        lambda _log: _validate_docx(s.docx_path(doc_id), markdown))
            info.update(validation)
            info["sha256"] = _sha256_file(s.docx_path(doc_id))
            if cancel.is_set():
                raise Cancelled()
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                doc = db.get(Document, doc_id)
                if job is None or doc is None:
                    return
                doc.docx_size = s.docx_path(doc_id).stat().st_size
                doc.docx_sha256 = info["sha256"]
                job_model.set_status(db, job, doc, Status.done.value)
                db.commit()
                storage.sync_document(s, doc, job, list(job.stage_runs))
            logger.info("Hoàn tất %s: %s", doc_id, {k: v for k, v in info.items() if k != "sha256"})
        except Cancelled:
            if not self._shutdown:
                self._set_cancelled(job_id)
        except MinerUCancelled:
            if not self._shutdown:
                self._set_cancelled(job_id)
        except MinerUError as exc:
            self._fail_job(job_id, exc.code, exc.message)
        except PipelineError as exc:
            self._fail_job(job_id, exc.code, str(exc))
        except PandocMissing as exc:
            self._fail_job(job_id, "PANDOC_NOT_FOUND", str(exc))
        except Exception as exc:
            logger.exception("Giai đoạn dựng DOCX lỗi (job=%s)", job_id)
            self._fail_job(job_id, "PIPELINE_FAILED", str(exc)[:500])

    def _start_stage(self, job_id: str, doc_id: str, stage: str, status: str, progress: int, **fields) -> int:
        with SessionLocal() as db:
            job, doc = db.get(Job, job_id), db.get(Document, doc_id)
            if job is None or doc is None or job.cancel_requested:
                raise Cancelled()
            job_model.set_status(db, job, doc, status, progress=progress)
            run = StageRun(job_id=job_id, stage=stage, status="running", started_at=now(), **fields)
            db.add(run)
            db.commit()
            storage.sync_document(self.settings, doc, job, list(job.stage_runs))
            return run.id

    def _finish_stage(self, run_id: int, status: str, note: dict) -> None:
        with SessionLocal() as db:
            run = db.get(StageRun, run_id)
            if run is None:
                return
            run.status = status
            run.finished_at = now()
            run.duration_s = max(0.0, run.finished_at - (run.started_at or run.finished_at))
            if "peak_ram_gb" in note:
                run.peak_ram_gb = note["peak_ram_gb"]
            merged_note = job_model.note_json(run) or {}
            merged_note.update(note)
            run.note = json.dumps(merged_note, ensure_ascii=False)
            db.commit()
            storage.sync_document(self.settings, run.job.document, run.job, list(run.job.stage_runs),
                                  artifacts=run.stage in ("parse", "prepare", "build"),
                                  outputs=run.stage in ("prepare", "build"))

    def _update_parse_progress(self, run_id: int, parts: list) -> None:
        with SessionLocal() as db:
            run = db.get(StageRun, run_id)
            if run is None or run.status != "running":
                return
            note = job_model.note_json(run) or {}
            note["parts"] = parts
            run.note = json.dumps(note, ensure_ascii=False)
            db.commit()
            storage.sync_document(self.settings, run.job.document, run.job, list(run.job.stage_runs))

    def _run_step(self, job_id: str, doc_id: str, stage: str, status: str, progress: int, action):
        run_id = self._start_stage(job_id, doc_id, stage, status, progress)
        started = time.perf_counter()
        try:
            result = action(self.settings.logs_dir(doc_id) / "post.log")
        except (Cancelled, PandocMissing):
            self._finish_stage(run_id, "failed", {"message": "Bước bị hủy hoặc thiếu Pandoc."})
            raise
        except Exception as exc:
            self._finish_stage(run_id, "failed", {"message": str(exc)[:500]})
            code = {"prepare": "PREPARE_FAILED", "build": "PANDOC_FAILED",
                    "validate": "DOCX_INVALID"}.get(stage, "PIPELINE_FAILED")
            raise PipelineError(code, str(exc)[:500]) from exc
        self._finish_stage(run_id, "done", {**result, "elapsed_s": round(time.perf_counter() - started, 2)})
        return result

    def _set_cancelled(self, job_id: str) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            doc = db.get(Document, job.document_id) if job else None
            if job and doc and job.status not in (Status.done.value, Status.failed.value, Status.cancelled.value):
                job_model.set_status(db, job, doc, Status.cancelled.value, error_code="CANCELLED",
                                     error_message="Đã hủy.")
                db.commit()
                storage.sync_document(self.settings, doc, job, list(job.stage_runs))

    def _fail_job(self, job_id: str, code: str, message: str) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            doc = db.get(Document, job.document_id) if job else None
            if job and doc and job.status not in (Status.done.value, Status.cancelled.value):
                job_model.set_status(db, job, doc, Status.failed.value, error_code=code,
                                     error_message=message[:500])
                db.commit()
                storage.sync_document(self.settings, doc, job, list(job.stage_runs))


_pipeline: Optional[Pipeline] = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> Pipeline:
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = Pipeline()
        return _pipeline


def set_pipeline(pipeline: Optional[Pipeline]) -> None:
    global _pipeline
    with _pipeline_lock:
        _pipeline = pipeline
