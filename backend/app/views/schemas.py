"""Schema request/response (View)."""
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody
    detail: Optional[str] = None


_DESC = {
    400: "Yêu cầu không hợp lệ", 404: "Không tìm thấy", 409: "Trạng thái hiện tại không cho phép thao tác này",
    413: "File quá lớn", 415: "Định dạng file không được hỗ trợ", 422: "Dữ liệu gửi lên không hợp lệ",
    429: "Quá nhiều job đang xử lý", 500: "Lỗi hệ thống",
}


def errors(*codes: int) -> dict:
    return {c: {"model": ErrorResponse, "description": _DESC[c]} for c in codes}


class ErrorInfo(BaseModel):
    code: str
    message: str


class ShardOut(BaseModel):
    index: int
    page_from: int
    page_to: int
    status: str                          # planned | running | done | failed | cancelled
    slot: Optional[str] = None           # main | aux
    duration_s: Optional[float] = None
    progress: float = 0.0
    elapsed_s: Optional[float] = None
    peak_ram_gb: Optional[float] = None
    error: Optional[str] = None


class StageRunOut(BaseModel):
    id: int
    stage: str                           # parse | merge | prepare | build | validate | cache
    shard_index: Optional[int] = None
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    slot: Optional[str] = None
    status: str
    attempt: int = 1
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_s: Optional[float] = None
    peak_ram_gb: Optional[float] = None
    note: Optional[Any] = None


class DocumentOut(BaseModel):
    id: str
    filename: str
    display_name: Optional[str] = None
    name: str                            # display_name hoặc filename
    status: str                          # queued|parsing|merging|preparing|building|validating|done|failed|cancelled
    progress: float                      # 0-100
    num_pages: int
    size_bytes: int
    tier: str = ""
    error: Optional[ErrorInfo] = None
    cache_hit: bool = False
    docx_available: bool = False
    docx_size: int = 0
    created_at: float
    updated_at: float
    finished_at: Optional[float] = None
    elapsed_s: Optional[float] = None
    job_id: Optional[str] = None
    shards: List[ShardOut] = []


class DocumentDetail(DocumentOut):
    stages: List[StageRunOut] = []


class DocumentListOut(BaseModel):
    items: List[DocumentOut]
    total: int


class UploadItem(BaseModel):
    document_id: str
    job_id: str
    filename: str
    status: str
    cache_hit: bool = False


class UploadRejected(BaseModel):
    filename: str
    code: str
    message: str


class UploadResult(BaseModel):
    items: List[UploadItem]
    rejected: List[UploadRejected] = []


class RenameIn(BaseModel):
    display_name: str = Field(max_length=255)


class JobOut(BaseModel):
    id: str
    document_id: str
    status: str
    progress: float
    attempt: int
    error: Optional[ErrorInfo] = None
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    stages: List[StageRunOut] = []
