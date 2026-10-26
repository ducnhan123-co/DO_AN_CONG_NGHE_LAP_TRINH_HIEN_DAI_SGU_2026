"""API mỏng quanh engine: nhận PDF, chạy pipeline, trả DOCX + audit.

Chạy (từ thư mục gốc repo):
    uvicorn backend.app.main:app --port 8000
    # mở http://127.0.0.1:8000  (frontend/ được phục vụ tĩnh)
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = Path(os.environ.get("PDF2DOCX_STORAGE", ROOT / "storage")) / "jobs"
TIERS = ("flash", "basic", "standard", "advanced")
MAX_UPLOAD = 80 * 1024 * 1024

# ponytail: 1 worker = hàng đợi tuần tự; MinerU ngốn RAM/CPU nên chạy song song nhiều job không lợi.
EXECUTOR = ThreadPoolExecutor(max_workers=1)
app = FastAPI(title="pdf2docx")


def job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise HTTPException(404, "Không có job")
    d = JOBS_DIR / job_id
    if not (d / "job.json").exists():
        raise HTTPException(404, "Không có job")
    return d


def read_job(d: Path) -> dict:
    return json.loads((d / "job.json").read_text(encoding="utf-8"))


def write_job(d: Path, **fields) -> dict:
    job = {**read_job(d), **fields} if (d / "job.json").exists() else fields
    (d / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return job


def run_job(d: Path) -> None:
    job = write_job(d, status="running", started=time.time())
    out = d / "out"
    cmd = [sys.executable, "-m", "pdf2docx_engine.pipeline", "--pdf", str(d / "input.pdf"),
           "--out", str(out), "--tier", job["tier"], "--workers", str(job["workers"])]
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT / "engine" / "src"), os.environ.get("PYTHONPATH")])),
           # mineru-kit nằm cạnh python của venv
           "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])}
    with open(d / "log.txt", "w", encoding="utf-8") as log:
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT).returncode
    docx = next(out.glob("*.docx"), None)
    write_job(d, status="done" if rc == 0 and docx else "failed", finished=time.time(), returncode=rc)


# Job đang queued/running mà server đã tắt -> không bao giờ xong nữa.
JOBS_DIR.mkdir(parents=True, exist_ok=True)
for _d in JOBS_DIR.iterdir():
    if (_d / "job.json").exists() and read_job(_d)["status"] in ("queued", "running"):
        write_job(_d, status="failed", error="Server khởi động lại khi job đang chạy")


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), tier: str = Form("advanced"), workers: int = Form(2)):
    if tier not in TIERS:
        raise HTTPException(400, f"tier phải thuộc {TIERS}")
    if not 1 <= workers <= 4:
        raise HTTPException(400, "workers trong khoảng 1-4")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "PDF quá 80 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "File không phải PDF")
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True)
    (d / "input.pdf").write_bytes(data)
    job = write_job(d, id=job_id, name=Path(file.filename or "input.pdf").name, tier=tier,
                    workers=workers, status="queued", created=time.time())
    EXECUTOR.submit(run_job, d)
    return job


@app.get("/api/jobs")
def list_jobs():
    jobs = [read_job(d) for d in JOBS_DIR.iterdir() if (d / "job.json").exists()]
    return sorted(jobs, key=lambda j: j["created"], reverse=True)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    d = job_dir(job_id)
    log = d / "log.txt"
    audit = d / "out" / "audit.json"
    return {**read_job(d),
            "log": "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]) if log.exists() else "",
            "audit": json.loads(audit.read_text(encoding="utf-8")) if audit.exists() else None}


@app.get("/api/jobs/{job_id}/docx")
def download_docx(job_id: str):
    d = job_dir(job_id)
    docx = next((d / "out").glob("*.docx"), None)
    if not docx:
        raise HTTPException(404, "Chưa có DOCX")
    return FileResponse(docx, filename=Path(read_job(d)["name"]).stem + ".docx")


app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
