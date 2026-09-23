"""Tầng View: định dạng dữ liệu vào/ra (Pydantic schemas).

Re-export để controller import gọn: `from backend.app.views import ChatRequest`.
"""
from backend.app.views.schemas import (ChatRequest, ChatResponse, Citation, DocumentCreated, 
                                       DocumentOut, ErrorInfo, ErrorResponse, JobOut, ThinkingStep, errors)

__all__ = [
    "ChatRequest", "ChatResponse", "Citation", "DocumentCreated", "DocumentOut",
    "ErrorInfo", "ErrorResponse", "JobOut", "ThinkingStep", "errors",
]