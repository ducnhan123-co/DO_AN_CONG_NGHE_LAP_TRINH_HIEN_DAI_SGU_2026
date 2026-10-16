"""Trạng thái job/stage_run trong app.db và ước lượng tiến độ."""
import json
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.database import ACTIVE, Document, Job, StageRun, Status, TERMINAL, now

# mức tiến độ (%) khi vào từng giai đoạn sau MinerU
PROGRESS = {"queued": 0, "parsing": 5, "merging": 82, "preparing": 86, "building": 90, "validating": 96, "done": 100}


def set_status(db: Session, job: Job, doc: Document, status: str, progress: Optional[int] = None,
               error_code: Optional[str] = None, error_message: Optional[str] = None) -> None:
    """Cập nhật đồng bộ job và document (document luôn phản chiếu job mới nhất)."""
    t = now()
    job.status = doc.status = status
    if progress is not None:
        job.progress = progress
    if status != Status.queued.value and job.started_at is None:
        job.started_at = t
    if status in TERMINAL:
        job.finished_at = doc.finished_at = t
    else:
        doc.finished_at = None
    if status == Status.done.value:
        job.progress = 100
        job.error_code = job.error_message = doc.error_code = doc.error_message = None
    elif status in (Status.failed.value, Status.cancelled.value):
        job.error_code = doc.error_code = error_code
        job.error_message = doc.error_message = error_message
    else:
        job.error_code = job.error_message = doc.error_code = doc.error_message = None


def create_job(db: Session, doc: Document, plan_json: Optional[str] = None, attempt: int = 1,
               status: str = Status.queued.value) -> Job:
    job = Job(document_id=doc.id, status=status, attempt=attempt, plan_json=plan_json)
    db.add(job)
    db.flush()
    return job


def latest_job(db: Session, doc_id: str) -> Optional[Job]:
    return (db.query(Job).filter(Job.document_id == doc_id).order_by(Job.created_at.desc(), Job.id.desc()).first())


def note_json(run: StageRun) -> Optional[dict]:
    if not run.note:
        return None
    try:
        return json.loads(run.note)
    except ValueError:
        return {"text": run.note}


# giây/trang đã đo trên máy của bạn (xem README): standard ~6,5 s/trang (46 trang, 1 tiến trình); advanced ~14-17 s/trang
SPP_BY_TIER = {"standard": 6.5, "advanced": 15.0}


def default_spp(tier: Optional[str], settings: Settings) -> float:
    return settings.est_seconds_per_page if settings.est_seconds_per_page > 0 else SPP_BY_TIER.get(tier or "", 10.0)


def estimate_progress(job: Job, runs: List[StageRun], settings: Settings, t: Optional[float] = None,
                      tier: Optional[str] = None) -> float:
    """Tiến độ 0-100 để hiển thị. Đang parse: tính theo số trang của các phần đã xong + phần đang chạy (ước theo tốc độ đã đo)."""
    t = t or now()
    if job.status == Status.done.value:
        return 100.0
    if job.status != Status.parsing.value:
        return float(job.progress or PROGRESS.get(job.status, 0))
    parse = [r for r in runs if r.stage == "parse" and r.page_from and r.page_to]
    total = sum(r.page_to - r.page_from + 1 for r in parse)
    if not total:
        return float(job.progress or 5)
    live_parts = []
    for run in parse:
        note = note_json(run) or {}
        live_parts.extend(note.get("parts", []))
    if live_parts:
        credited = sum(
            (part["page_to"] - part["page_from"] + 1) * max(0.0, min(100.0, part.get("progress", 0.0))) / 100
            for part in live_parts
        )
        return round(5 + 75 * credited / total, 1)
    measured = [r.duration_s / (r.page_to - r.page_from + 1) for r in parse
                if r.status == "done" and r.duration_s and not (r.note and '"reuse"' in r.note)]
    spp = (sum(measured) / len(measured)) if measured else default_spp(tier, settings)
    credited = 0.0
    for r in parse:
        pages = r.page_to - r.page_from + 1
        if r.status == "done":
            credited += pages
        elif r.status == "running" and r.started_at:
            expected = 15 + pages * spp
            credited += pages * min(0.92, max(0.0, (t - r.started_at) / expected))
    return round(5 + 75 * credited / total, 1)
