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
    message_count: int = 0
    parent_document_id: Optional[str] = None
    latest_job_id: Optional[str] = None
    docx_available: bool
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    id: str
    filename: str
    status: str
    message_count: int = 0 
    created_at: datetime


class DocumentListOut(BaseModel):
    items: List[DocumentListItem]
    total: int


class Citation(BaseModel):
    index: int                    # thứ tự trong danh sách trích dẫn (1, 2, 3...)
    page: Optional[int] = None    # số trang PDF thật, khớp [số trang] trong câu trả lời
    section: str                  # tên mục/section trong tài liệu
    score: float
    snippet: str
    # chỉ có khi chat nhiều tài liệu (nhóm)
    doc_id: Optional[str] = None
    doc_no: Optional[int] = None      # số thứ tự tài liệu trong nhóm (khớp nhãn [n:trang])
    filename: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: List[Citation] = []
    created_at: datetime


class MessageListOut(BaseModel):
    items: List[MessageOut]


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


class ThinkingStep(BaseModel):
    step: str                     # analyze | retrieve | retrieved | generate
    text: str


class ChatResponse(BaseModel):
    message_id: str
    document_id: str
    document_ids: List[str] = []      # chat nhóm: toàn bộ tài liệu được hỏi
    answer: str
    citations: List[Citation]
    thinking: List[ThinkingStep]


class SplitRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_page: int = Field(..., alias="from", ge=1, description="Trang bắt đầu (1-based)")
    to_page: int = Field(..., alias="to", ge=1, description="Trang kết thúc (bao gồm)")
    name: Optional[str] = Field(None, max_length=200, description="Tên phần, vd 'Chương 1'")


class SplitRequest(BaseModel):
    ranges: List[SplitRange] = Field(..., min_length=1, max_length=20)


class SplitResultItem(BaseModel):
    document_id: str
    job_id: str
    filename: str
    status: str


class SplitResponse(BaseModel):
    parent_document_id: str
    parts: List[SplitResultItem]