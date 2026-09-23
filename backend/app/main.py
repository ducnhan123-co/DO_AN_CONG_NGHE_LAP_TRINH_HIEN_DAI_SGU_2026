"""Khởi động ứng dụng: tạo FastAPI app, gắn router, quản lý lifespan."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.controllers import router
from backend.app.core.config import get_settings, setup_logging
from backend.app.core.errors import register_exception_handlers
from backend.app.core.llm import LLMError, get_llm
from backend.app.models import SessionLocal, init_db
from backend.app.models import pipeline_model

logger = logging.getLogger(__name__)

DESCRIPTION = """
Upload PDF toán → MinerU → DOCX → RAG hỏi đáp có trích dẫn.

**Luồng dùng:** `POST /documents` → theo dõi `GET /jobs/{id}` đến khi `succeeded`
→ `POST /documents/{id}/chat` → `GET /documents/{id}/export/docx`.

**Chat stream:** gửi `stream=true` để nhận SSE gồm các sự kiện `thinking`, `token`, `citations`, `done`, `error`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    (s.data_dir / "documents").mkdir(parents=True, exist_ok=True)
    init_db()
    with SessionLocal() as db:
        n = pipeline_model.fail_stale_jobs(db)
        if n:
            logger.warning("Đã đánh dấu %d job dở dang là failed", n)
    if s.preload_llm and s.llm_backend != "none":
        try:
            get_llm()
        except LLMError as e:
            logger.warning("Preload LLM thất bại: %s", e)
    yield
    pipeline_model.shutdown()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, description=DESCRIPTION, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins,
                       allow_methods=["*"], allow_headers=["*"])
    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()