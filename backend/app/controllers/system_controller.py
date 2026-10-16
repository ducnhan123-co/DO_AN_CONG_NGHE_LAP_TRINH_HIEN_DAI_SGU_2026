"""Controller: kiểm tra server + thống kê hàng đợi/slot."""
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.engine import rag_toan
from backend.app.engine.mineru_runner import kit_command
from backend.app.models.database import Document, get_db
from backend.app.models.pipeline import get_pipeline

router = APIRouter(tags=["system"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/health", summary="Kiểm tra server, CSDL và công cụ ngoài (Pandoc, mineru-kit)")
def health(db: DbSession):
    db.execute(text("SELECT 1"))
    s = get_settings()
    kit = kit_command(s.mineru_cmd)
    return {"status": "ok", "database": "ok", "pandoc": bool(shutil.which("pandoc")),
            "mineru_cmd": s.mineru_cmd, "mineru_found": bool(shutil.which(kit[0]) or __import__("os").path.exists(kit[0])),
            "mineru_tier": s.mineru_tier, "mineru_format": s.mineru_format, "engine": rag_toan.engine_info(),
            "engine_found": rag_toan.engine_info()["found"]}


@router.get("/system/stats", summary="Slot đang chạy, độ dài hàng đợi, tài nguyên máy")
def stats(db: DbSession):
    by_status = dict(db.execute(select(Document.status, func.count()).group_by(Document.status)).all())
    return {**get_pipeline().stats(), "documents": by_status}
