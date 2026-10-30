"""API thư viện tài liệu quanh engine PDF -> DOCX.

Chạy (từ thư mục gốc repo):
    uvicorn backend.app.main:app --port 8000
    # mở http://127.0.0.1:8000  (giao diện trong frontend/ được phục vụ tĩnh)

Hợp đồng JSON khớp `frontend/app.js`, `frontend/index.html`, `frontend/reader.html`
(cùng bộ giao diện của nhánh Nghia): mọi trường frontend đọc đều do `jobs.render()` trả.
"""
import re
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import jobs
from .errors import AppError, install_handlers

ROOT = jobs.ROOT
FRONTEND_DIR = ROOT / "frontend"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

app = FastAPI(title="PDF → Word", version="1.0.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])
install_handlers(app)
jobs.mark_interrupted()


class RenameBody(BaseModel):
    display_name: str


# --------------------------------------------------------------------------- hệ thống
@app.get("/api/health")
def health():
    return {"ok": True,
            "engine_found": jobs.ENGINE_SRC.is_dir(),
            "pandoc": bool(jobs.which_tool("pandoc")),
            "mineru_found": bool(jobs.which_tool("mineru-kit")),
            "mineru_cmd": "mineru-kit",
            "tesseract": bool(jobs.which_tool("tesseract")),
            "tier": jobs.DEFAULT_TIER,
            "workers_per_doc": jobs.DEFAULT_WORKERS,
            "rag_index": False}


@app.get("/api/system/stats")
def system_stats():
    return jobs.stats()


# --------------------------------------------------------------------------- thư viện
@app.get("/api/documents")
def list_documents(limit: int = Query(200, ge=1, le=500)):
    items = [jobs.render(job) for job in jobs.list_jobs(limit)]
    return {"items": items, "total": len(items)}


@app.post("/api/documents", status_code=202)
async def upload_documents(files: List[UploadFile] = File(...),
                           tier: str = Form(jobs.DEFAULT_TIER),
                           workers: int = Form(jobs.DEFAULT_WORKERS)):
    if tier not in jobs.TIERS:
        raise AppError(400, "INVALID_TIER", f"tier phải thuộc {jobs.TIERS}")
    if not 1 <= workers <= 8:
        raise AppError(400, "INVALID_WORKERS", "workers trong khoảng 1-8")
    items, rejected = [], []
    for i, f in enumerate(files):
        name = jobs.clean_filename(f.filename) or "(không tên)"
        if i >= jobs.MAX_FILES_PER_REQUEST:
            rejected.append({"filename": name, "message": f"vượt quá {jobs.MAX_FILES_PER_REQUEST} file mỗi lần tải"})
            continue
        try:
            staged = await jobs.stage_upload(f)
            job = jobs.register(staged, Path(name).stem, tier, workers)
            items.append(jobs.render(job))
        except AppError as ex:
            rejected.append({"filename": name, "message": ex.message})
    if not items:
        msg = "; ".join(f"{r['filename']}: {r['message']}" for r in rejected) or "Không có file nào được nhận."
        raise AppError(400, "UPLOAD_REJECTED", msg)
    return {"items": items, "rejected": rejected}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    return jobs.render(jobs.get_job(doc_id))


@app.patch("/api/documents/{doc_id}")
def rename_document(doc_id: str, body: RenameBody):
    return jobs.render(jobs.rename(doc_id, body.display_name))


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str):
    jobs.delete(doc_id)
    return Response(status_code=204)


@app.post("/api/documents/{doc_id}/cancel")
def cancel_document(doc_id: str):
    return jobs.render(jobs.cancel(doc_id))


@app.post("/api/documents/{doc_id}/retry")
def retry_document(doc_id: str, force: bool = Query(False)):
    return jobs.render(jobs.retry(doc_id, force=force))


# --------------------------------------------------------------------------- tải file
# 2 endpoint này dùng bằng <a href> / <iframe src> nên trình duyệt không gửi header gì thêm.
@app.get("/api/documents/{doc_id}/docx")
def download_docx(doc_id: str):
    job = jobs.get_job(doc_id)
    path = jobs.docx_path(jobs.job_dir(doc_id))
    if path is None:
        raise AppError(409, "DOCX_NOT_READY", "File Word chưa sẵn sàng.")
    stem = re.sub(r'[\\/:*?"<>|]', "_", (job.get("filename") or doc_id).rsplit(".", 1)[0]) or doc_id
    return FileResponse(path, media_type=DOCX_MIME, filename=f"{stem}.docx")


@app.get("/api/documents/{doc_id}/pdf")
def view_pdf(doc_id: str):
    job = jobs.get_job(doc_id)
    path = jobs.job_dir(doc_id) / "input.pdf"
    if not path.is_file():
        raise AppError(404, "NOT_FOUND", "Không có PDF gốc cho tài liệu này.")
    return FileResponse(path, media_type="application/pdf", filename=job.get("filename") or "input.pdf",
                        content_disposition_type="inline")


@app.get("/api/documents/{doc_id}/log")
def get_log(doc_id: str, tail_kb: int = Query(64, ge=1, le=1024)):
    jobs.get_job(doc_id)
    path = jobs.job_dir(doc_id) / "log.txt"
    if not path.is_file():
        return PlainTextResponse("")
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - tail_kb * 1024))
        return PlainTextResponse(f.read().decode("utf-8", errors="replace"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
