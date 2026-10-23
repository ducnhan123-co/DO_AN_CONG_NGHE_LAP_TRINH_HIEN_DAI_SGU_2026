"""Tầng Controller: nhận request, gọi Model, trả về qua Views."""
from typing import Annotated
 
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
 
from backend.app.controllers import (chat_controller, compat_controller, document_controller,
                                     export_controller, job_controller, library_controller)
from backend.app.core.config import get_settings
from backend.app.models.database import get_db
 
router = APIRouter()
 
for _module in (document_controller, job_controller, chat_controller, export_controller,
                compat_controller, library_controller):
    router.include_router(_module.router)
 
@router.get("/health", tags=["health"], summary="Kiểm tra server")
def health(db: Annotated[Session, Depends(get_db)]):
    db.execute(text("SELECT 1"))
    s = get_settings()
 
    from llm.src.config import (MINERU_BACKEND, MINERU_DEVICE,
                                MINERU_METHOD, MINERU_TIER)
    return {"status": "ok", "database": "ok",
            "ok": True, "ai_pipeline_enabled": s.ai_pipeline_enabled,
            "search_backend": "keyword_bm25", "llm": None,
            "mineru": {"backend": MINERU_BACKEND, "device": MINERU_DEVICE,
                       "method": MINERU_METHOD, "tier": MINERU_TIER}}
 
__all__ = ["router"]
 