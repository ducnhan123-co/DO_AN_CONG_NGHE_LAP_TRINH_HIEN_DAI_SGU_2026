"""FastAPI boundary for the MatchPDF frontend and the local RAG/LLM service."""
import json
import os
import re
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from llm.matchpdf import DEFAULT_MODEL, MatchPdfStore

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("APP_DATA_DIR", ROOT / "runtime" / "documents"))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ORIGINS = [origin for origin in os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:8080,http://localhost:8080,http://127.0.0.1:5173,http://localhost:5173"
).split(",") if origin]

app = FastAPI(title="SGU MatchPDF API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"])
store = MatchPdfStore(DATA_DIR)


class WarmRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=100)


class ChatRequest(BaseModel):
    doc_id: str = Field(pattern=r"^[0-9a-f]{10}$")
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=100)
    history: list[dict] = Field(default_factory=list, max_length=12)


def _doc_id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", value):
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return value


@app.get("/api/health")
def health() -> dict:
    return store.health()


@app.post("/api/upload")
async def upload(background_tasks: BackgroundTasks, f: UploadFile = File(...)) -> dict:
    if not f.filename or Path(f.filename).suffix.lower() != ".pdf":
        raise HTTPException(415, "Chỉ nhận file PDF.")
    doc_id = uuid.uuid4().hex[:10]
    path = DATA_DIR / f"{doc_id}.pdf"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("wb") as destination:
            while chunk := await f.read(1024 * 1024):
                if destination.tell() + len(chunk) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "PDF vượt giới hạn 50 MB.")
                destination.write(chunk)
        if not path.read_bytes()[:5].startswith(b"%PDF-"):
            raise HTTPException(415, "Tệp tải lên không phải PDF hợp lệ.")
        result = store.index_upload(doc_id, f.filename, path)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"Không thể xử lý PDF: {str(exc)[:300]}") from exc
    finally:
        await f.close()
    result["parser"] = "mineru_running"
    store.docs[doc_id]["parser"] = "mineru_running"
    store._save(doc_id)
    background_tasks.add_task(store.upgrade_mineru, doc_id)
    return result


@app.get("/api/doc/{doc_id}")
def doc_info(doc_id: str) -> dict:
    doc_id = _doc_id(doc_id)
    if not store.load(doc_id):
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return store.info(doc_id)


@app.get("/api/file/{doc_id}")
def file(doc_id: str):
    doc_id = _doc_id(doc_id)
    if not store.load(doc_id):
        raise HTTPException(404, "Tài liệu không tồn tại.")
    document = store.docs[doc_id]
    return FileResponse(document["file"], media_type="application/pdf", filename=document["name"],
                        content_disposition_type="inline")


@app.post("/api/warm")
def warm(payload: WarmRequest) -> dict:
    try:
        store.warm(payload.model)
        return {"ok": True, "model": payload.model}
    except Exception as exc:
        raise HTTPException(502, f"Ollama lỗi: {str(exc)[:300]}") from exc


@app.post("/api/chat_stream")
def chat_stream(payload: ChatRequest):
    if not store.load(payload.doc_id):
        raise HTTPException(404, "Tài liệu không tồn tại.")

    def events():
        try:
            for event in store.stream_chat(payload.doc_id, payload.question, payload.history, payload.top_k, payload.model):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
