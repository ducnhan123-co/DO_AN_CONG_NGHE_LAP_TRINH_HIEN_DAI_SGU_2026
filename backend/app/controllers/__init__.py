"""Tầng Controller: nhận request, gọi Model, trả về qua Views.

Gom router của từng controller và khai báo thêm /health (kiểm tra server).
"""
from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Annotated
from fastapi import Depends

from backend.app.controllers import (chat_controller, document_controller,
                                     export_controller, job_controller)
from backend.app.core.config import get_settings
from backend.app.models.database import get_db

router = APIRouter()

for _module in (document_controller, job_controller, chat_controller, export_controller):
    router.include_router(_module.router)


@router.get("/health", tags=["health"], summary="Kiểm tra server")
def health(db: Annotated[Session, Depends(get_db)]):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "llm_backend": get_settings().llm_backend}


__all__ = ["router"]