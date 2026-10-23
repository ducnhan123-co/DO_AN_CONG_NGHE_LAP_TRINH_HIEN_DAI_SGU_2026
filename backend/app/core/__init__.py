"""Tầng hạ tầng dùng chung: cấu hình (.env), lỗi chuẩn, mô hình ngôn ngữ."""
from backend.app.core.config import DOCX_MIME, Settings, get_settings, setup_logging
from backend.app.core.errors import (AppError, document_not_found, job_not_found,
                                     register_exception_handlers)

__all__ = [
    "DOCX_MIME", "Settings", "get_settings", "setup_logging",
    "AppError", "document_not_found", "job_not_found", "register_exception_handlers",
]