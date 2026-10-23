"""FastAPI: MinerU PDF/DOCX and keyword search; optional same-origin Mac demo UI."""
import os
 
# Bắt buộc đặt TRƯỚC mọi import khác: ép Python (kể cả subprocess con như MinerU)
# đọc/ghi UTF-8, tránh UnicodeDecodeError 'charmap' khi chạy trên Windows.
os.environ.setdefault("PYTHONUTF8", "1")
 
import logging
from contextlib import asynccontextmanager
 
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
 
from backend.app.controllers import router
from backend.app.core.config import get_settings, setup_logging
from backend.app.core.errors import register_exception_handlers
from backend.app.models import SessionLocal, init_db
from backend.app.models import library_db, pipeline_model
 
logger = logging.getLogger(__name__)
 
DESCRIPTION = """
Upload PDF toán → MinerU → DOCX → RAG hỏi đáp có trích dẫn.
 
**Luồng dùng:** `POST /documents` → theo dõi `GET /jobs/{id}` đến khi `succeeded`
→ `POST /documents/{id}/chat` → `GET /documents/{id}/export/docx`.
 
**Chat stream:** gửi `stream=true` để nhận SSE gồm các sự kiện `thinking`, `token`,
`citations`, `done`, `error`.
 
**Thử lại tài liệu lỗi:** `POST /documents/{id}/retry` dùng lại PDF đã lưu, không cần upload lại.
 
**Thư viện (header `X-Client-Id`):** `/doc`, `/doc/{id}/sessions`, `/session/{sid}/messages`,
`/doc/{id}/ingest|context|docx|activity` — tài liệu, phiên chat, công thức, lịch sử DOCX.
"""
 
 
@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    setup_logging(s.log_level)
    (s.data_dir / "documents").mkdir(parents=True, exist_ok=True)
    init_db()
    library_db.connect().close()   # tạo / migrate library.db ngay khi khởi động
    with SessionLocal() as db:
        n = pipeline_model.fail_stale_jobs(db)
        if n:
            logger.warning("Đã đánh dấu %d job dở dang là failed", n)
    import threading as _threading
    # Start optional MinerU pool only when MINERU_PREWARM=true.
    def _warm_mineru() -> None:
        try:
            from llm.src.config import MINERU_DEVICE, MINERU_LANG, MINERU_WORKERS
            if MINERU_WORKERS > 0:
                from llm.src.mineru_pool import prewarm
                prewarm(MINERU_WORKERS, MINERU_DEVICE, MINERU_LANG)
                logger.info("Preload MinerU xong (%d server nóng)", MINERU_WORKERS)
        except Exception as e:                            # noqa: BLE001
            logger.warning("Preload MinerU thất bại: %s", e)

    if s.mineru_prewarm:
        _threading.Thread(target=_warm_mineru, daemon=True, name="warm-mineru").start()
    yield
    pipeline_model.shutdown()
 
 
def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, description=DESCRIPTION, version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins,
                       allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"])  # PDF Range
    register_exception_handlers(app)
    if bool(s.demo_auth_user) != bool(s.demo_auth_password):
        raise RuntimeError("DEMO_AUTH_USER and DEMO_AUTH_PASSWORD must both be set")

    if s.demo_auth_user and s.demo_auth_password:
        # The tunnel exposes a real Mac to the Internet; protect every route,
        # including static HTML, /docs and /api/ paths, with HTTP Basic.
        import base64
        import binascii
        import secrets

        @app.middleware("http")
        async def demo_basic_auth(request: Request, call_next):
            raw = request.headers.get("authorization", "")
            granted = False
            if raw.startswith("Basic "):
                try:
                    decoded = base64.b64decode(raw[6:], validate=True).decode("utf-8")
                    username, separator, password = decoded.partition(":")
                    granted = bool(separator) and (
                        secrets.compare_digest(username, s.demo_auth_user) and
                        secrets.compare_digest(password, s.demo_auth_password))
                except (binascii.Error, UnicodeDecodeError, ValueError):
                    granted = False
            if not granted:
                return Response(status_code=401, headers={
                    "WWW-Authenticate": 'Basic realm="SGU MathPDF Demo"',
                    "Cache-Control": "no-store",
                })
            return await call_next(request)

    app.include_router(router, prefix=s.api_prefix)
    if s.serve_frontend:
        # Serving FE from the same backend origin avoids cross-site auth/CORS issues.
        # The public tunnel URL is discovered by the browser at request time.
        async def runtime_config():
            body = ("window.MATCHPDF_API_BASE = window.location.origin;\n"
                    "window.MATCHPDF_LIB_BASE = window.location.origin;\n")
            return PlainTextResponse(
                body, media_type="application/javascript",
                headers={"Cache-Control": "no-store"})

        from backend.app.core.config import ROOT_DIR
        app.add_api_route("/config.js", runtime_config, include_in_schema=False)
        app.mount("/", StaticFiles(directory=str(ROOT_DIR / "frontend"), html=True),
                  name="frontend")
    return app
 
 
app = create_app()