"""FastAPI + hàng đợi tài liệu tuần tự; MinerU có thể parse song song theo từng PDF.

Chạy từ thư mục dự án:

    uvicorn backend.app.main:app --port 8000          (CHỈ 1 worker: hàng đợi nằm trong tiến trình này)
"""
import os
from pathlib import Path

os.environ.setdefault("PYTHONUTF8", "1")      # tiến trình con (MinerU, Pandoc) đọc/ghi UTF-8, tránh lỗi 'charmap' trên Windows

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.app.controllers import (document_controller, export_controller, job_controller, system_controller)
from backend.app.core.config import get_settings
from backend.app.core.errors import register_exception_handlers
from backend.app.models.database import Document, Job, SessionLocal, engine, init_db
from backend.app.models.storage import sync_all_documents
from backend.app.models.pipeline import Pipeline, set_pipeline

logger = logging.getLogger(__name__)

DESCRIPTION = """
Chuyển PDF toán sang DOCX có công thức Equation thật: **MinerU → Markdown → Pandoc → DOCX**.

`POST /documents` (1 hoặc nhiều file) → MinerU song song → Markdown/structured/chunks → Pandoc/DOCX → kiểm tra.
Theo dõi qua `GET /documents` hoặc `GET /jobs/{id}/events` (SSE); tải qua `GET /documents/{id}/docx`.
Mỗi lúc chỉ xử lý một tài liệu; các phần trang trong tài liệu đó có thể chạy đồng thời.
"""


def setup_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    (s.data_dir / "documents").mkdir(parents=True, exist_ok=True)
    logger.info("Thư mục dữ liệu backend: %s", s.data_dir.resolve())
    if engine.dialect.name == "sqlite" and engine.url.database and engine.url.database != ":memory:":
        logger.info("File database SQLite: %s", Path(engine.url.database).expanduser().resolve())
    init_db()
    (s.data_dir / "input").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "docx_output").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "runs").mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        documents = db.scalars(select(Document)).all()
        sync_all_documents(s, [(doc, max(doc.jobs, key=lambda job: job.created_at) if doc.jobs else None)
                               for doc in documents])
    pipeline = Pipeline(s)
    set_pipeline(pipeline)
    pipeline.start()
    yield
    pipeline.stop()
    set_pipeline(None)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, description=DESCRIPTION, version="2.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition"])
    register_exception_handlers(app)
    api = APIRouter()
    for mod in (document_controller, export_controller, job_controller, system_controller):
        api.include_router(mod.router)
    app.include_router(api, prefix=s.api_prefix)
    if s.frontend_dir.exists():          # phục vụ luôn giao diện: mở http://127.0.0.1:8000/
        app.mount("/", StaticFiles(directory=str(s.frontend_dir), html=True), name="frontend")
    return app


app = create_app()
