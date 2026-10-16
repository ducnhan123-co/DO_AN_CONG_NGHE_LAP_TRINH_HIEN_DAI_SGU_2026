"""Controller: upload (nhiều file), liệt kê, xem, đổi tên, hủy, thử lại, xóa."""
from typing import Annotated, List

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.models import document_model as dm
from backend.app.models.database import get_db
from backend.app.views.schemas import (DocumentDetail, DocumentListOut, DocumentOut, RenameIn, UploadResult, errors)

router = APIRouter(prefix="/documents", tags=["documents"])
DbSession = Annotated[Session, Depends(get_db)]
ClientId = Annotated[str, Header(alias="X-Client-Id", description="Mã ẩn danh của trình duyệt, để mỗi người chỉ thấy file của mình")]


@router.post("", response_model=UploadResult, status_code=202, summary="Upload 1 hoặc nhiều PDF và bắt đầu chuyển sang DOCX",
             responses=errors(400, 413, 415, 422, 429))
def upload(db: DbSession, files: List[UploadFile] = File(..., description="Một hoặc nhiều file PDF"),
           x_client_id: ClientId = "", force: bool = Query(False, description="true: bỏ qua cache sha256, xử lý lại từ đầu")):
    """Nhận ít nhất 1 file thì trả 202 kèm danh sách `items` và `rejected` (file bị từ chối + lý do).
    Không file nào nhận được thì trả lỗi HTTP của file đầu tiên."""
    limit = get_settings().max_files_per_request
    if len(files) > limit:
        raise AppError(400, "TOO_MANY_FILES", f"Mỗi lần upload tối đa {limit} file (bạn gửi {len(files)}).")
    items, rejected = dm.create_documents(db, files, dm.clean_client_id(x_client_id), force)
    return UploadResult(items=items, rejected=rejected)


@router.get("", response_model=DocumentListOut, summary="Danh sách tài liệu (mới nhất trước)")
def list_documents(db: DbSession, x_client_id: ClientId = "",
                   status: str = Query("", description="active | done | failed | trạng thái cụ thể"),
                   q: str = "", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    rows, total = dm.list_documents(db, dm.clean_client_id(x_client_id), status, q, limit, offset)
    return DocumentListOut(items=[dm.document_out(db, d) for d in rows], total=total)


@router.get("/{document_id}", response_model=DocumentDetail, summary="Chi tiết + thời gian từng bước", responses=errors(404))
def get_document(document_id: str, db: DbSession):
    return dm.document_out(db, dm.get_document(db, document_id), detail=True)


@router.patch("/{document_id}", response_model=DocumentOut, summary="Đổi tên hiển thị", responses=errors(404, 422))
def rename(document_id: str, body: RenameIn, db: DbSession):
    return dm.document_out(db, dm.rename_document(db, document_id, body.display_name))


@router.post("/{document_id}/cancel", response_model=DocumentOut, summary="Hủy xử lý", responses=errors(404, 409))
def cancel(document_id: str, db: DbSession):
    return dm.document_out(db, dm.cancel_document(db, document_id))


@router.post("/{document_id}/retry", response_model=DocumentOut, status_code=202,
             summary="Thử lại tài liệu lỗi/đã hủy (giữ các phần MinerU đã xong)", responses=errors(404, 409, 429))
def retry(document_id: str, db: DbSession):
    doc, _ = dm.retry_document(db, document_id)
    return dm.document_out(db, doc)


@router.delete("/{document_id}", status_code=204, summary="Xóa tài liệu và toàn bộ file", responses=errors(404))
def delete(document_id: str, db: DbSession):
    dm.delete_document(db, document_id)
    return Response(status_code=204)
