"""Kho tài liệu (jobs) + chạy engine + dựng JSON cho frontend.

Một tài liệu = một thư mục `storage/jobs/<id>/`:
    input.pdf     PDF gốc
    job.json      trạng thái, tên hiển thị, tier, thời gian, lỗi...
    log.txt       stdout/stderr của engine
    out/          kết quả engine: mineru/, *.docx, audit.json, repair_report.json...
    mineru_parts/ các phần MinerU chạy song song (engine tự tạo)

Engine được gọi đúng như CLI (subprocess) để hủy được và không treo server;
tiến độ đọc từ đĩa (phần MinerU nào có .done) và từ log, không bịa số.

Lưu trữ theo NỘI DUNG: một PDF (sha256) + một tier = đúng một tài liệu. id của tài liệu mới được tính từ
sha256(nội dung):tier, nên tải cùng một file nhiều lần (dù lần trước đang chờ/đang chạy/đã xong/lỗi) chỉ
trả về tài liệu đã có thay vì tạo thêm thư mục, thêm bản input.pdf và chạy lại engine.
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

_lock = threading.Lock()                 # bảo vệ job.json và bảng tiến trình
_reg_lock = threading.RLock()            # tuần tự hóa việc đăng ký/tái dùng tài liệu (chống 2 lần tải chạy đua)
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


def job_key(sha256: str, tier: str) -> str:
    """id của tài liệu mới: cùng nội dung + cùng tier -> cùng id (12 ký tự hex, hợp với ID_RE)."""
    return hashlib.sha256(f"{sha256}:{tier}".encode()).hexdigest()[:12]


def _rank(job: dict) -> tuple:
    """Thứ tự ưu tiên khi có nhiều tài liệu cùng nội dung: xong có DOCX < đang chạy/chờ < còn lại; rồi cũ nhất."""
    d = JOBS_DIR / job["id"]
    status = job.get("status")
    if status == "done" and docx_path(d) is not None:
        group = 0
    elif status in ACTIVE:
        group = 1
    else:
        group = 2
    return group, job.get("created") or 0


def find_existing(sha256: str, tier: str) -> Optional[dict]:
    """Tài liệu đã có cùng nội dung + tier, ở BẤT KỲ trạng thái nào (kể cả đang chờ/đang chạy).

    Quét cả tài liệu cũ có id ngẫu nhiên (tạo trước khi có id theo nội dung)."""
    same = [j for j in list_jobs(10_000) if j.get("sha256") == sha256 and (j.get("tier") or DEFAULT_TIER) == tier]
    return min(same, key=_rank) if same else None


def register(staged: Staged, display_name: str, tier: str, workers: int) -> tuple:
    """Đăng ký PDF vừa nhận. Trả (job, reused):

        reused = ""         tài liệu MỚI, đã xếp hàng chạy
        reused = "done"     đã có kết quả sẵn -> dùng lại, không chạy
        reused = "active"   cùng file đang chờ/đang chạy -> dùng chung, không chạy thêm
        reused = "requeued" cùng file từng lỗi/hủy (hoặc mất DOCX) -> chạy lại tài liệu CŨ (tiếp tục phần đã xong)

    Không bao giờ tạo thêm thư mục hay thêm bản input.pdf cho nội dung đã có."""
    with _reg_lock:
        existing = find_existing(staged.sha256, tier)
        if existing is not None:
            d = JOBS_DIR / existing["id"]
            if not (d / "input.pdf").is_file():          # mất PDF gốc (xóa tay?) -> khôi phục từ bản vừa nhận
                os.replace(staged.path, d / "input.pdf")
            else:
                staged.path.unlink(missing_ok=True)       # đã có đúng nội dung này rồi, không giữ bản thứ hai
            status = existing.get("status")
            if status in ACTIVE:
                return existing, "active"
            if status == "done" and docx_path(d) is not None:
                return existing, "done"
            return _requeue(existing["id"]), "requeued"

        job_id = job_key(staged.sha256, tier)
        d = JOBS_DIR / job_id
        if d.exists():
            if (d / "job.json").is_file():               # va chạm id (xác suất ~0) -> id ngẫu nhiên
                job_id = uuid.uuid4().hex[:12]
                d = JOBS_DIR / job_id
            else:                                        # thư mục dở dang từ lần sập trước
                shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=False)
        os.replace(staged.path, d / "input.pdf")
        display = (display_name or Path(staged.filename).stem)[:200] or job_id
        job = write_job(d, id=job_id, name=display, filename=staged.filename, sha256=staged.sha256,
                        size_bytes=staged.size, num_pages=staged.pages, tier=tier, workers=workers,
                        status="queued", created=time.time(), started=None, finished=None,
                        returncode=None, error_code=None, error_message=None, cache_hit=False, cancelled=False)
        submit(job_id)
        return job, ""


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


def _requeue(job_id: str, force: bool = False) -> dict:
    """Đưa tài liệu đã có về hàng đợi (dùng cho Thử lại và cho việc tải lại cùng file sau khi lỗi/hủy)."""
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


def retry(job_id: str, force: bool = False) -> dict:
    job = get_job(job_id)
    status = job.get("status")
    if status not in ("failed", "cancelled") and not (force and status == "done"):
        raise AppError(409, "NOT_RETRYABLE", "Chỉ chạy lại được tài liệu bị lỗi hoặc đã hủy.")
    return _requeue(job_id, force=force)


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
           "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")]),
           # stdout ghi ra file thì Python đệm (buffer) tới khi đầy/kết thúc: mốc "[repair]", "[audit]"... sẽ tới trễ và
           # giao diện hiện sai bước. Chỉ đổi cách tiến trình con xả log, không đổi hành vi của engine.
           "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    problem = _preflight()
    if problem:                                      # thiếu công cụ: báo ngay, đừng đợi MinerU chạy xong mới lỗi ở Pandoc
        write_job(d, status="failed", started=time.time(), finished=time.time(), cancelled=False, returncode=None,
                  error_code=problem[0], error_message=problem[1])
        return
    _clean_stale_outputs(out)
    write_job(d, status="running", started=time.time(), finished=None, cancelled=False,
              returncode=None, error_code=None, error_message=None, pid=None)
    with open(d / "log.txt", "w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT, **_POPEN_KW)
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
        log = tail_text(d / "log.txt", 262144)
        code, message = _failure(log, rc, _stage(d, log))
        write_job(d, status="failed", finished=time.time(), returncode=rc,
                  error_code=code, error_message=message)


def _preflight() -> Optional[tuple]:
    """(mã lỗi, thông báo) nếu thiếu công cụ ngoài mà engine bắt buộc phải có."""
    if which_tool("pandoc") is None:
        return "PANDOC_NOT_FOUND", "Không tìm thấy Pandoc (chưa cài hoặc không có trong PATH)."
    if which_tool("mineru-kit") is None:
        return "MINERU_NOT_FOUND", "Không tìm thấy lệnh mineru-kit (pip install mineru, hoặc kích hoạt đúng môi trường)."
    return None


def _clean_stale_outputs(out: Path) -> None:
    """Xóa file Word/audit của lần chạy TRƯỚC. Nếu để lại thì `docx_path()` thấy ngay một .docx cũ: giao diện sẽ báo
    sai bước (nhảy thẳng tới 'kiểm tra') và tải được file cũ trong lúc đang chạy lại. Phần MinerU đã xong vẫn giữ
    để engine tiếp tục (resume)."""
    for f in out.glob("*.docx"):
        f.unlink(missing_ok=True)
    (out / "audit.json").unlink(missing_ok=True)


# Tiến trình engine ở nhóm riêng để hủy được cả cây tiến trình con (mineru-kit...).
_POPEN_KW = ({"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)} if os.name == "nt"
             else {"start_new_session": True})


def _kill(proc: subprocess.Popen) -> None:
    if os.name == "nt":                              # Windows không có killpg/SIGKILL
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        return
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


def _failure(log: str, rc: int, stage: str = "parsing") -> tuple:
    """(mã lỗi, thông báo). Mã lỗi theo BƯỚC đang chạy lúc dừng để giao diện tô đúng bước; trước đây chỉ cần log có chữ
    "mineru" (gần như log nào cũng có) là bị coi là lỗi MinerU."""
    lines = [ln.strip() for ln in log.splitlines() if ln.strip()]
    tail = lines[-1] if lines else f"engine thoát với mã {rc}"
    low = log.lower()
    if "pandoc tạo docx thất bại" in low or "pandoc_not_found" in low:
        return "PANDOC_FAILED", tail
    return STAGE_ERROR.get(stage, "PIPELINE_ERROR"), tail


# --------------------------------------------------------------------------- dựng JSON cho frontend
def _part_shards(d: Path) -> List[dict]:
    """Các phần MinerU: lấy tổng số phần từ mineru_parts/pdf (engine cắt sẵn tất cả), nên phần chưa bắt đầu
    (do --stagger) hiện là 'pending' thay vì biến mất khỏi danh sách."""
    parts_root = d / "out" / "mineru_parts"
    found: Dict[int, dict] = {}
    for sub in ("pdf", "out"):
        base = parts_root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            m = re.match(r"part_(\d+)_p(\d+)-(\d+)", p.name)
            if not m:
                continue
            idx = int(m.group(1))
            rec = found.setdefault(idx, {"index": idx, "page_from": int(m.group(2)), "page_to": int(m.group(3)),
                                         "status": "pending", "progress": 0.0, "elapsed_s": None,
                                         "peak_ram_gb": None, "error": None})
            if sub == "out" and p.is_dir():
                rec["status"] = "done" if (p / ".done").is_file() else "running"
                rec["progress"] = 100.0 if rec["status"] == "done" else 0.0
    return [found[k] for k in sorted(found)]


def _stage(d: Path, log: str) -> str:
    """Bước hiện tại, suy từ file kết quả + log engine (không đoán bừa).
    parsing -> merging -> preparing -> building (Pandoc + chỉnh DOCX) -> validating (audit)."""
    if "[audit]" in log:
        return "validating"
    if docx_path(d) is not None:
        return "building"
    if any(mark in log for mark in ("[repair]", "[image]", "[math_repair]", "[frame]", "Working Markdown")):
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
    # Log chỉ cần để biết "đang ở bước nào": với tài liệu đã xong/hủy/đang chờ thì khỏi đọc (danh sách được hỏi mỗi
    # ~1,2 giây cho MỌI tài liệu nên đọc log của từng cái rất phí).
    log = tail_text(d / "log.txt", 262144) if status in ("running", "failed", "cancelled") else ""
    shards = _part_shards(d) if status != "queued" else []
    stage = _stage(d, log) if status in ("running", "failed", "cancelled") else ("queued" if status == "queued" else "")
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
    """Gọi khi server khởi động.

    * dọn file tạm do lần chạy trước bị sập giữa chừng (.upload-*.part, .job.json.tmp);
    * tài liệu đang chạy dở -> 'failed' (bấm Thử lại là engine tiếp tục các phần MinerU đã xong);
    * tài liệu mới chỉ đang CHỜ -> xếp hàng lại (chưa chạy gì nên không có lý do bắt người dùng tải lại)."""
    if JOBS_DIR.is_dir():
        for f in JOBS_DIR.glob(".upload-*.part"):
            f.unlink(missing_ok=True)
    waiting = []
    for job in sorted(list_jobs(10_000), key=lambda j: j.get("created") or 0):
        d = JOBS_DIR / job["id"]
        (d / ".job.json.tmp").unlink(missing_ok=True)
        if job.get("status") == "running":
            write_job(d, status="failed", finished=time.time(),
                      error_code="SERVER_RESTART", error_message="Server khởi động lại khi tài liệu đang chạy.")
        elif job.get("status") == "queued" and not job.get("cancelled") and (d / "input.pdf").is_file():
            waiting.append(job["id"])
    for job_id in waiting:
        submit(job_id)


# --------------------------------------------------------------------------- dọn tài liệu trùng (dữ liệu cũ)
def find_duplicates() -> List[dict]:
    """Nhóm các tài liệu CÙNG NỘI DUNG + cùng tier (do bản cũ tạo ra mỗi lần tải một thư mục riêng).
    Mỗi nhóm giữ 1 bản tốt nhất (đã xong có DOCX > đang chạy > còn lại; cùng hạng thì cũ nhất)."""
    groups: Dict[tuple, List[dict]] = {}
    for job in list_jobs(10_000):
        if job.get("sha256"):
            groups.setdefault((job["sha256"], job.get("tier") or DEFAULT_TIER), []).append(job)
    result = []
    for (sha, tier), jobs_ in groups.items():
        if len(jobs_) < 2:
            continue
        jobs_.sort(key=_rank)
        keep, extra = jobs_[0], [j for j in jobs_[1:] if j.get("status") not in ACTIVE]   # không bao giờ xóa bản đang chạy
        size = sum(_dir_size(JOBS_DIR / j["id"]) for j in extra)
        result.append({"keep": keep["id"], "name": keep.get("name"), "remove": [j["id"] for j in extra], "bytes": size})
    return result


def _dir_size(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def dedupe_storage(apply: bool = False) -> dict:
    """Xóa các bản trùng (apply=True) hoặc chỉ báo cáo (mặc định). Dùng: python -m backend.app.jobs --dedupe [--apply]"""
    groups = find_duplicates()
    removed = 0
    if apply:
        with _reg_lock:
            for g in groups:
                for job_id in g["remove"]:
                    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
                    removed += 1
    return {"groups": groups, "removed": removed, "freed_bytes": sum(g["bytes"] for g in groups) if apply else 0,
            "reclaimable_bytes": sum(g["bytes"] for g in groups)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Dọn các tài liệu trùng nội dung trong storage/jobs")
    ap.add_argument("--dedupe", action="store_true", help="liệt kê các nhóm trùng")
    ap.add_argument("--apply", action="store_true", help="thật sự xóa (mặc định chỉ báo cáo)")
    a = ap.parse_args()
    if not a.dedupe:
        ap.error("dùng --dedupe")
    res = dedupe_storage(apply=a.apply)
    for g in res["groups"]:
        print(f"giữ {g['keep']} ({g['name']}) | {'xóa' if a.apply else 'sẽ xóa'}: {', '.join(g['remove']) or '-'} | {g['bytes'] / 1e6:.1f} MB")
    print(f"{len(res['groups'])} nhóm trùng; " + (f"đã xóa {res['removed']} thư mục, giải phóng {res['freed_bytes'] / 1e6:.1f} MB"
          if a.apply else f"có thể giải phóng {res['reclaimable_bytes'] / 1e6:.1f} MB (thêm --apply để xóa)"))
