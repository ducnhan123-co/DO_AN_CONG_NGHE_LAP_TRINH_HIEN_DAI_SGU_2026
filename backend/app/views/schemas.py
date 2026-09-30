"""Toàn bộ schema request/response (View)."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


#  lỗi
class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[object] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ErrorInfo(BaseModel):
    code: str
    message: str


_DESC = {
    400: "Yêu cầu không hợp lệ",
    404: "Không tìm thấy",
    409: "Tài liệu chưa sẵn sàng hoặc xử lý thất bại",
    413: "File quá lớn",
    415: "Định dạng file không được hỗ trợ",
    422: "Dữ liệu gửi lên không hợp lệ",
    429: "Quá nhiều job đang chờ xử lý",
    500: "Lỗi hệ thống",
    503: "Mô hình ngôn ngữ không khả dụng",
}


def errors(*codes: int) -> dict:
    """Khai báo response lỗi chuẩn cho OpenAPI."""
    return {c: {"model": ErrorResponse, "description": _DESC[c]} for c in codes}


#  document và job
class DocumentCreated(BaseModel):
    document_id: str
    job_id: str
    filename: str
    status: str
    job_url: str


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    error: Optional[ErrorInfo] = None
    num_sections: int
    num_chunks: int
    latest_job_id: Optional[str] = None
    docx_available: bool
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    id: str
    filename: str
    status: str
    created_at: datetime


class DocumentListOut(BaseModel):
    items: List[DocumentListItem]
    total: int


class JobOut(BaseModel):
    id: str
    document_id: str
    status: str            # queued | running | succeeded | failed
    stage: str             # queued | mineru_parsing | building_docx | indexing | ready | failed
    progress: int          # 0-100
    error: Optional[ErrorInfo] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


#  chat
class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(..., min_length=1, max_length=2000,
                          examples=["Định nghĩa đạo hàm trong tài liệu là gì?"])
    top_k: Optional[int] = Field(None, ge=1, le=20, description="Số đoạn truy xuất")
    stream: bool = Field(False, description="true: trả SSE (thinking/token/citations/done)")


class Citation(BaseModel):
    index: int                    # số [n] xuất hiện trong câu trả lời
    chunk_id: Optional[int] = None
    heading: str
    score: float
    snippet: str


class ThinkingStep(BaseModel):
    step: str                     # analyze | retrieve | retrieved | generate
    text: str


class ChatResponse(BaseModel):
    message_id: str
    document_id: str
    answer: str
    citations: List[Citation]
    thinking: List[ThinkingStep]