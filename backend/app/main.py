"""Khởi tạo ứng dụng FastAPI (điểm ghép MVC):

    Model       app/models        SQLite (app.db) + thực thể + repository
    View        app/views         JSON đúng định dạng frontend
    Controller  app/controllers   các route /api/...
    Service     app/services      pipeline rag_toan, MinerU, hàng đợi, upload, lưu trữ data/
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from .controllers import documents_controller, system_controller
from .core import log_router
from .core.config import Settings, load_settings
from .core.container import build_container
from .core.errors import install_handlers

log = logging.getLogger("app")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_router.install()                       # print() của rag_toan -> log từng tài liệu
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container.scheduler.start()
        e = container.engine
        log.info("Data: %s | rag_toan: %s (%s) | pandoc: %s | %s: %s",
                 settings.data_dir, settings.engine_dir, "OK" if e.found else "KHÔNG THẤY",
                 "OK" if e.pandoc_found else "THIẾU", e.mineru_argv0, "OK" if e.mineru_found else "THIẾU")
        yield
        container.scheduler.stop()

    app = FastAPI(title="PDF → Word backend", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.container = container

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["*"],
        expose_headers=["Content-Disposition"])
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)   # danh sách 246 KB -> ~5 KB
    install_handlers(app)
    app.include_router(system_controller.router)
    app.include_router(documents_controller.router)

    # Phục vụ luôn giao diện: mở http://127.0.0.1:8000/ là dùng được, khớp frontend/config.js (cùng nguồn gốc)
    if settings.serve_frontend and settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
    return app