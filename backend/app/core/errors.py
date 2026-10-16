"""Lỗi chuẩn: AppError + exception handler. Body luôn có {"error": {code, message, details}, "detail": message}."""
import logging
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


def document_not_found(document_id: str) -> AppError:
    return AppError(404, "DOCUMENT_NOT_FOUND", f"Không tìm thấy tài liệu '{document_id}'.")


def job_not_found(job_id: str) -> AppError:
    return AppError(404, "JOB_NOT_FOUND", f"Không tìm thấy job '{job_id}'.")


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}, "detail": message}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body("VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Lỗi không xử lý: %s", exc)
        return JSONResponse(_body("INTERNAL_ERROR", "Lỗi hệ thống. Vui lòng thử lại sau."), status_code=500)
