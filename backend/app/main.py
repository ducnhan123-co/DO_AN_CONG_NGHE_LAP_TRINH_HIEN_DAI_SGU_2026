"""Minimal HTTP boundary for the PDF-to-RAG pipeline."""
import os
import re
import shutil
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from llm.service import answer_question, process_pdf

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("APP_DATA_DIR", ROOT / "runtime" / "documents"))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_ORIGINS = [origin for origin in os.getenv(
    "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
).split(",") if origin]
DOCUMENTS: dict[str, dict] = {}

app = FastAPI(title="SGU PDF RAG API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _document_dir(document_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", document_id):
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return DATA_DIR / document_id


def _run_pipeline(document_id: str) -> None:
    document = DOCUMENTS[document_id]
    document["status"] = "processing"
    try:
        document["result"] = process_pdf(Path(document["pdf_path"]), _document_dir(document_id))
        document["status"] = "ready"
    except Exception as exc:
        document["status"] = "failed"
        document["error"] = str(exc)[:500]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/documents", status_code=202)
def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)) -> dict:
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(415, "Chỉ nhận tệp PDF.")
    document_id = uuid.uuid4().hex
    directory = _document_dir(document_id)
    directory.mkdir(parents=True, exist_ok=False)
    pdf_path = directory / "input.pdf"
    try:
        with pdf_path.open("wb") as output:
            while content := file.file.read(1024 * 1024):
                if output.tell() + len(content) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "PDF vượt giới hạn 50 MB.")
                output.write(content)
        with pdf_path.open("rb") as uploaded:
            signature = uploaded.read(5)
        if not signature.startswith(b"%PDF-"):
            raise HTTPException(415, "Tệp tải lên không phải PDF hợp lệ.")
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        file.file.close()
    DOCUMENTS[document_id] = {"status": "queued", "pdf_path": str(pdf_path), "name": file.filename}
    background_tasks.add_task(_run_pipeline, document_id)
    return {"id": document_id, "status": "queued"}


@app.get("/api/documents/{document_id}")
def document_status(document_id: str) -> dict:
    _document_dir(document_id)
    document = DOCUMENTS.get(document_id)
    if not document:
        raise HTTPException(404, "Không tìm thấy tài liệu trong phiên chạy này.")
    return {"id": document_id, "status": document["status"], "error": document.get("error")}


@app.post("/api/documents/{document_id}/questions")
def ask(document_id: str, payload: Question) -> dict:
    directory = _document_dir(document_id)
    document = DOCUMENTS.get(document_id)
    if not document or document["status"] != "ready":
        raise HTTPException(409, "Tài liệu chưa sẵn sàng để hỏi đáp.")
    return answer_question(directory, payload.question, os.getenv("ENABLE_LOCAL_LLM") == "1")
