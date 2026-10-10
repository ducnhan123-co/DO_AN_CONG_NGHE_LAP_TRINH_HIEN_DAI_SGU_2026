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
 
    llm_name = None
    if s.llm_backend == "qwen_local":
        from llm.src.config import LLM_NAME
        llm_name = s.llm_name or LLM_NAME
    elif s.llm_backend == "ollama":
        llm_name = s.ollama_model
 
    return {"status": "ok", "database": "ok", "llm_backend": s.llm_backend,
           "ok": True, "llm": llm_name}
 
__all__ = ["router"]
 