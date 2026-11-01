"""Kho tài liệu (jobs) + chạy engine + dựng JSON cho frontend.

Một tài liệu = một thư mục `storage/jobs/<id>/`:
    input.pdf     PDF gốc
    job.json      trạng thái, tên hiển thị, tier, thời gian, lỗi...
    log.txt       stdout/stderr của engine
    out/          kết quả engine: mineru/, *.docx, audit.json, repair_report.json...
    mineru_parts/ các phần MinerU chạy song song (engine tự tạo)

Engine được gọi đúng như CLI (subprocess) để hủy được và không treo server;
tiến độ đọc từ đĩa (phần MinerU nào có .done) và từ log, không bịa số.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from .errors import AppError

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = Path(os.environ.get("PDF2DOCX_STORAGE", ROOT / "storage")) / "jobs"
ENGINE_SRC = ROOT / "engine" / "src"

TIERS = ("flash", "basic", "standard", "advanced")
DEFAULT_TIER = os.environ.get("MINERU_TIER", "advanced")
if DEFAULT_TIER not in TIERS:
    DEFAULT_TIER = "advanced"
DEFAULT_WORKERS = 2
MAX_UPLOAD_MB = 100
MAX_FILES_PER_REQUEST = 20
MAX_PAGES = 1000
MIN_PAGES_PER_WORKER = 5
ID_RE = re.compile(r"^[0-9a-f]{12}$")

ACTIVE = ("queued", "running")
# stage -> (mã lỗi, nhãn) để frontend tô đúng bước
STAGE_ERROR = {"parsing": "MINERU_FAILED", "merging": "MERGE_FAILED", "preparing": "PREPARE_FAILED",
               "building": "DOCX_BUILD_FAILED", "validating": "DOCX_INVALID"}

_lock = threading.Lock()
_procs: Dict[str, subprocess.Popen] = {}
_queue: "queue.Queue[tuple]" = queue.Queue()
_worker: Optional[threading.Thread] = None


# --------------------------------------------------------------------------- tiện ích
def clean_filename(name: Optional[str]) -> str:
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return base[:200]


def valid_id(job_id: str) -> bool:
    return bool(ID_RE.match(job_id or ""))


def job_dir(job_id: str) -> Path:
    if not valid_id(job_id):
        raise AppError(404, "NOT_FOUND", "Tài liệu không tồn tại.")
    return JOBS_DIR / job_id


def get_job(job_id: str) -> dict:
    d = job_dir(job_id)
    if not (d / "job.json").is_file():
        raise AppError(404, "NOT_FOUND", "Tài liệu không tồn tại hoặc đã bị xóa.")
    return read_job(d)


def read_job(d: Path) -> dict:
    try:
        return json.loads((d / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_job(d: Path, **fields) -> dict:
    with _lock:
        job = read_job(d)
        job.update(fields)
        tmp = d / ".job.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, d / "job.json")
    return job


def count_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 - PDF hỏng thì để engine báo lỗi sau
        return 0


def tail_text(path: Path, limit: int = 65536) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def which_tool(cmd: str) -> Optional[str]:
    """Tìm lệnh như lúc chạy engine: có thêm bin/ của venv đang chạy server."""
    return shutil.which(cmd, path=os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]))


def docx_path(d: Path) -> Optional[Path]:
    out = d / "out"
    return next(out.glob("*.docx"), None) if out.is_dir() else None


# --------------------------------------------------------------------------- nhận file (stream)
class Staged:
    def __init__(self, path: Path, filename: str, sha256: str, size: int, pages: int):
        self.path, self.filename, self.sha256, self.size, self.pages = path, filename, sha256, size, pages


async def stage_upload(upload) -> Staged:
    filename = clean_filename(getattr(upload, "filename", None)) or "(không tên)"
    if not filename.lower().endswith(".pdf"):
        raise AppError(400, "UPLOAD_REJECTED", "không phải file PDF")
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = JOBS_DIR / f".upload-{uuid.uuid4().hex}.part"
    limit, digest, size, head = MAX_UPLOAD_MB * (1 << 20), hashlib.sha256(), 0, b""
    try:
        with open(tmp, "wb") as f:
            while True:
                block = await upload.read(1 << 20)
                if not block:
                    break
                size += len(block)
                if size > limit:
                    raise AppError(413, "UPLOAD_REJECTED", f"file lớn hơn {MAX_UPLOAD_MB} MB")
                if len(head) < 1024:
                    head += block[: 1024 - len(head)]
                digest.update(block)
                f.write(block)
        if size == 0:
            raise AppError(400, "UPLOAD_REJECTED", "file rỗng")
        if b"%PDF-" not in head:
            raise AppError(400, "UPLOAD_REJECTED", "nội dung không phải PDF")
        pages = count_pages(tmp)
        if pages < 1:
            raise AppError(400, "UPLOAD_REJECTED", "PDF bị hỏng hoặc không đọc được")
        if pages > MAX_PAGES:
            raise AppError(400, "UPLOAD_REJECTED", f"PDF {pages} trang, vượt giới hạn {MAX_PAGES} trang")
        return Staged(tmp, filename, digest.hexdigest(), size, pages)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- thư viện
def list_jobs(limit: int = 200) -> List[dict]:
    if not JOBS_DIR.is_dir():
        return []
    jobs = []
    for d in JOBS_DIR.iterdir():
        if d.is_dir() and valid_id(d.name) and (d / "job.json").is_file():
            job = read_job(d)
            if job:
                jobs.append(job)
    jobs.sort(key=lambda j: j.get("created") or 0, reverse=True)
    return jobs[:limit]


def find_cached(sha256: str) -> Optional[Path]:
    """Tài liệu đã xong cùng nội dung -> dùng lại DOCX, không chạy lại MinerU."""
    for job in list_jobs(1000):
        if job.get("sha256") != sha256 or job.get("status") != "done":
            continue
        d = JOBS_DIR / job["id"]
        if docx_path(d) is not None:
            return d
    return None


def register(staged: Staged, display_name: str, tier: str, workers: int) -> dict:
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=False)
    os.replace(staged.path, d / "input.pdf")
    display = (display_name or Path(staged.filename).stem)[:200] or job_id
    job = write_job(d, id=job_id, name=display, filename=staged.filename, sha256=staged.sha256,
                    size_bytes=staged.size, num_pages=staged.pages, tier=tier, workers=workers,
                    status="queued", created=time.time(), started=None, finished=None,
                    returncode=None, error_code=None, error_message=None, cache_hit=False, cancelled=False)
    cached = find_cached(staged.sha256)
    if cached is not None:                           # cùng nội dung đã chuyển xong -> chép DOCX sang, không chạy lại
        (d / "out").mkdir(exist_ok=True)
        copy = d / "out" / "cached.docx"
        shutil.copy2(docx_path(cached), copy)
        job = write_job(d, status="done", cache_hit=True, progress=100.0,
                        finished=time.time(), started=time.time(), docx_size=copy.stat().st_size)
    else:
        submit(job_id)
    return job


def rename(job_id: str, name: str) -> dict:
    get_job(job_id)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()
    if not name or len(name) > 200:
        raise AppError(400, "INVALID_NAME", "Tên hiển thị phải dài từ 1 đến 200 ký tự.")
    return write_job(job_dir(job_id), name=name)


def cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if job.get("status") not in ACTIVE:
        raise AppError(409, "NOT_ACTIVE", "Tài liệu không đang được xử lý.")
    write_job(job_dir(job_id), cancelled=True)
    with _lock:
        proc = _procs.get(job_id)
    if proc is not None and proc.poll() is None:
        _kill(proc)
    else:                                            # còn trong hàng đợi -> worker sẽ bỏ qua
        write_job(job_dir(job_id), status="cancelled", finished=time.time(), progress=0.0)
    return get_job(job_id)


def retry(job_id: str, force: bool = False) -> dict:
    job = get_job(job_id)
    status = job.get("status")
    if status not in ("failed", "cancelled") and not (force and status == "done"):
        raise AppError(409, "NOT_RETRYABLE", "Chỉ chạy lại được tài liệu bị lỗi hoặc đã hủy.")
    d = job_dir(job_id)
    if not (d / "input.pdf").is_file():
        raise AppError(409, "INPUT_MISSING", "Mất file PDF gốc, hãy xóa rồi tải lại.")
    if force:
        shutil.rmtree(d / "out" / "mineru_parts", ignore_errors=True)
        shutil.rmtree(d / "out" / "mineru", ignore_errors=True)
    job = write_job(d, status="queued", progress=0.0, cancelled=False, cache_hit=False,
                    started=None, finished=None, returncode=None, error_code=None, error_message=None)
    submit(job_id, force=force)
    return job


def delete(job_id: str) -> None:
    job = get_job(job_id)
    if job.get("status") in ACTIVE:
        cancel(job_id)
        deadline = time.time() + 15
        while time.time() < deadline:
            with _lock:
                proc = _procs.get(job_id)
            if proc is None or proc.poll() is not None:
                break
            time.sleep(0.2)
    shutil.rmtree(job_dir(job_id), ignore_errors=True)


# --------------------------------------------------------------------------- chạy engine
def submit(job_id: str, force: bool = False) -> None:
    _ensure_worker()
    _queue.put((job_id, force))


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="pdf2docx-worker", daemon=True)
            _worker.start()


def _worker_loop() -> None:
    while True:
        job_id, force = _queue.get()
        try:
            job = get_job(job_id)                    # tài liệu có thể đã bị xóa trong lúc chờ
            if job.get("status") != "queued" or job.get("cancelled"):
                continue
            _run(job_id, force)
        except AppError:
            continue
        except Exception:  # noqa: BLE001 - worker không được chết
            import traceback
            traceback.print_exc()
        finally:
            _queue.task_done()


def _run(job_id: str, force: bool) -> None:
    d = job_dir(job_id)
    job = read_job(d)
    out = d / "out"
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pdf2docx_engine.pipeline",
           "--pdf", str(d / "input.pdf"), "--out", str(out), "--docx-dir", str(out),
           "--tier", str(job.get("tier") or DEFAULT_TIER), "--workers", str(int(job.get("workers") or DEFAULT_WORKERS))]
    if force:
        cmd.append("--force")
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ENGINE_SRC), os.environ.get("PYTHONPATH")])),
           "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])}
    write_job(d, status="running", started=time.time(), finished=None, cancelled=False,
              returncode=None, error_code=None, error_message=None, pid=None)
    with open(d / "log.txt", "w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT,
                                    start_new_session=True)
        except OSError as ex:
            write_job(d, status="failed", finished=time.time(), error_code="ENGINE_NOT_FOUND",
                      error_message=f"Không chạy được engine: {ex}")
            return
        with _lock:
            _procs[job_id] = proc
        write_job(d, pid=proc.pid)
        if read_job(d).get("cancelled"):             # người dùng bấm Hủy đúng lúc vừa khởi chạy
            _kill(proc)
        rc = proc.wait()
    with _lock:
        _procs.pop(job_id, None)
    job = read_job(d)
    docx = docx_path(d)
    if job.get("cancelled"):
        write_job(d, status="cancelled", finished=time.time(), returncode=rc)
    elif rc == 0 and docx is not None:
        write_job(d, status="done", finished=time.time(), returncode=rc, progress=100.0,
                  docx_size=docx.stat().st_size)
    else:
        log = tail_text(d / "log.txt")
        code, message = _failure(log, rc)
        write_job(d, status="failed", finished=time.time(), returncode=rc,
                  error_code=code, error_message=message)


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        return
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            pass


def _failure(log: str, rc: int) -> tuple[str, str]:
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    tail = lines[-1] if lines else f"engine thoát với mã {rc}"
    low = log.lower()
    if "pandoc tạo docx thất bại" in low or "pandoc_not_found" in low:
        return "PANDOC_FAILED", tail
    if "mineru" in low:
        return "MINERU_FAILED", tail
    return "PIPELINE_ERROR", tail


# --------------------------------------------------------------------------- dựng JSON cho frontend
def _part_shards(d: Path) -> List[dict]:
    parts_root = d / "out" / "mineru_parts" / "out"
    shards = []
    if not parts_root.is_dir():
        return shards
    for p in sorted(parts_root.iterdir()):
        m = re.match(r"part_(\d+)_p(\d+)-(\d+)", p.name)
        if not m or not p.is_dir():
            continue
        done = (p / ".done").is_file()
        shards.append({"index": int(m.group(1)), "page_from": int(m.group(2)), "page_to": int(m.group(3)),
                       "status": "done" if done else "running", "progress": 100.0 if done else 0.0,
                       "elapsed_s": None, "peak_ram_gb": None, "error": None})
    return shards


def _stage(d: Path, log: str) -> str:
    """Bước hiện tại, suy từ file kết quả + log engine (không đoán bừa)."""
    if docx_path(d) is not None:
        return "validating"
    if any(mark in log for mark in ("[repair]", "[image]", "[math_repair]")):
        return "preparing"
    if "Đã ghép" in log or "phần xong" in log:
        return "merging"
    return "parsing"


def _progress(stage: str, shards: List[dict]) -> float:
    if stage == "parsing":
        if shards:
            return round(2 + 68 * sum(1 for s in shards if s["status"] == "done") / len(shards), 1)
        return 30.0
    return {"merging": 72.0, "preparing": 80.0, "building": 88.0, "validating": 95.0}.get(stage, 0.0)


def _stages(stage: str, status: str, shards: List[dict], job: dict, d: Path) -> List[dict]:
    """Timeline 5 bước như frontend vẽ; chỉ bước đang chạy mới có started_at."""
    order = ["parsing", "merging", "preparing", "building", "validating"]
    names = {"parsing": "parse", "merging": "merge", "preparing": "prepare", "building": "build", "validating": "validate"}
    cur = order.index(stage) if stage in order else -1
    stages = []
    for i, key in enumerate(order):
        if status == "done":
            rec_status = "done"
        elif status == "failed":
            rec_status = "done" if i < cur else ("failed" if i == cur else "planned")
        elif status in ("cancelled", "queued"):
            rec_status = "done" if i < cur else "planned"
        else:
            rec_status = "done" if i < cur else ("running" if i == cur else "planned")
        note = {"parts": len(shards), "pages": job.get("num_pages")} if key == "parsing" and shards else None
        stages.append({"stage": names[key], "status": rec_status,
                       "started_at": job.get("started") if i == 0 else None,
                       "duration_s": None, "note": note})
    if status == "done":
        stages[0]["duration_s"] = _elapsed(job)
        audit = _audit(d)
        docx = audit.get("docx") or {}
        note = {"equations_docx": docx.get("equations"), "raw_latex_paragraphs": docx.get("raw_latex_paragraphs")}
        extra = []
        if audit.get("dropped_pages"):
            extra.append(f"MinerU bỏ khối ở {len(audit['dropped_pages'])} trang")
        if audit.get("numbering_gaps"):
            extra.append(f"{len(audit['numbering_gaps'])} chỗ nhảy số/thiếu ý")
        if docx.get("raw_latex_paragraphs"):
            extra.append(f"{docx['raw_latex_paragraphs']} đoạn còn LaTeX thô")
        if extra:
            note["warning"] = "; ".join(extra) + " (xem audit.json)."
        stages[4]["note"] = note
    return stages


def _audit(d: Path) -> dict:
    p = d / "out" / "audit.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _elapsed(job: dict) -> Optional[float]:
    start = job.get("started")
    if not start:
        return 0.0
    end = time.time() if job.get("status") in ACTIVE else (job.get("finished") or time.time())
    return round(max(0.0, end - start), 1)


def render(job: dict) -> dict:
    d = JOBS_DIR / job["id"]
    status = job.get("status") or "queued"
    log = tail_text(d / "log.txt")
    shards = _part_shards(d)
    stage = _stage(d, log) if status not in ("queued",) else "queued"
    docx = docx_path(d)
    shown = {"queued": "queued", "running": stage, "done": "done",
             "failed": "failed", "cancelled": "cancelled"}.get(status, "queued")
    progress = 100.0 if status == "done" else (0.0 if status == "queued" else _progress(stage, shards))
    error = None
    if status == "failed":
        error = {"code": job.get("error_code") or STAGE_ERROR.get(stage, "PIPELINE_ERROR"),
                 "message": job.get("error_message") or "Engine dừng bất thường, xem log."}
    return {
        "id": job["id"],
        "name": job.get("name") or job.get("filename") or job["id"],
        "filename": job.get("filename") or "input.pdf",
        "num_pages": job.get("num_pages") or 0,
        "size_bytes": job.get("size_bytes") or 0,
        "status": shown,
        "progress": progress,
        "error": error,
        "docx_available": bool(status == "done" and docx is not None),
        "docx_size": docx.stat().st_size if docx is not None else job.get("docx_size"),
        "elapsed_s": _elapsed(job),
        "cache_hit": bool(job.get("cache_hit")),
        "tier": job.get("tier") or DEFAULT_TIER,
        "created_at": job.get("created") or 0,
        "shards": shards,
        "stages": _stages(stage, status, shards, job, d),
        "rag": {"ok": None, "note": None},
    }


def stats() -> dict:
    jobs = list_jobs(1000)
    running = [j["id"] for j in jobs if j.get("status") == "running"]
    queued = [j["id"] for j in jobs if j.get("status") == "queued"]
    procs = sum(int(j.get("workers") or DEFAULT_WORKERS) for j in jobs if j.get("status") == "running")
    return {"running": running, "main_slots": 1, "aux_mode": "off", "mineru_processes": procs,
            "queued_tasks": len(queued),
            "last_decision": f"Đang chạy {len(running)} tài liệu" if running else "Chưa có tài liệu nào chạy"}


def mark_interrupted() -> None:
    """Server khởi động lại khi job đang chạy -> job đó sẽ không bao giờ xong nữa."""
    for job in list_jobs(1000):
        if job.get("status") in ACTIVE:
            write_job(JOBS_DIR / job["id"], status="failed", finished=time.time(),
                      error_code="SERVER_RESTART", error_message="Server khởi động lại khi tài liệu đang chạy.")
