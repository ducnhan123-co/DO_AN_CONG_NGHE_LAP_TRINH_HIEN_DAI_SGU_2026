"""Controller: upload, liệt kê, xem thông tin, thử lại tài liệu."""
from typing import Annotated

from pathlib import Path

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError

from backend.app.models import document_model
from backend.app.models.database import get_db
from backend.app.views.schemas import (DocumentCreated, DocumentListItem,
                                       DocumentListOut, DocumentOut,
                                       MessageListOut, MessageOut,
                                       SplitRequest, SplitResponse, SplitResultItem, errors)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/documents", tags=["documents"], response_model=DocumentCreated, status_code=202,
             summary="Upload PDF và bắt đầu xử lý", responses=errors(400, 413, 415, 422, 429))
def upload_document(response: Response, db: DbSession,
                    file: UploadFile = File(..., description="File PDF toán")):
    doc, job = document_model.create_document(db, file)
    job_url = f"/jobs/{job.id}"
    response.headers["Location"] = job_url
    return DocumentCreated(document_id=doc.id, job_id=job.id, filename=doc.filename,
                           status=doc.status, job_url=job_url)


@router.get("/documents", tags=["documents"], response_model=DocumentListOut,
            summary="Liệt kê tài liệu (mới nhất trước)")
def list_documents(db: DbSession, limit: int = 20, offset: int = 0):
    rows, total = document_model.list_documents(db, limit, offset)
    items = [DocumentListItem(id=r.id, filename=r.filename, status=r.status,
                              message_count=document_model._message_count(db, r.id),
                              created_at=r.created_at) for r in rows]
    return DocumentListOut(items=items, total=total)


@router.get("/documents/{document_id}", tags=["documents"], response_model=DocumentOut,
            summary="Xem thông tin và trạng thái tài liệu", responses=errors(404))
def get_document(document_id: str, db: DbSession):
    return document_model.document_out(db, document_id)


@router.post("/documents/{document_id}/retry", tags=["documents"], response_model=DocumentCreated,
             status_code=202,
             summary="Thử lại xử lý tài liệu đã failed (dùng lại PDF đã lưu, không cần upload lại)",
             responses=errors(404, 409, 429))
def retry_document(document_id: str, response: Response, db: DbSession):
    doc, job = document_model.retry_document(db, document_id)
    job_url = f"/jobs/{job.id}"
    response.headers["Location"] = job_url
    return DocumentCreated(document_id=doc.id, job_id=job.id, filename=doc.filename,
                           status=doc.status, job_url=job_url)


@router.post("/documents/{document_id}/split", tags=["documents"], response_model=SplitResponse,
             status_code=202, summary="Cắt PDF thành nhiều tài liệu con theo khoảng trang",
             responses=errors(404, 409, 422, 429))
def split_document(document_id: str, body: SplitRequest, db: DbSession):
    ranges = [{"from": r.from_page, "to": r.to_page, "name": r.name} for r in body.ranges]
    results = document_model.split_document(db, document_id, ranges)
    parts = [SplitResultItem(document_id=d.id, job_id=j.id, filename=d.filename, status=d.status)
            for d, j in results]
    return SplitResponse(parent_document_id=document_id, parts=parts)


@router.delete("/documents/{document_id}", tags=["documents"], status_code=204,
               summary="Xóa tài liệu và toàn bộ dữ liệu liên quan", responses=errors(404))
def delete_document(document_id: str, db: DbSession):
    document_model.delete_document(db, document_id)

# Backwards-compatible with the useful inspectable artifacts from backend v3.
# The whitelist prevents path traversal and avoids serving arbitrary uploaded files.
ARTIFACTS = {
    "chunks.json": "chunks.json",
    "validation.json": "validation.json",
    "structured_data.json": "structured_data.json",
    "work.md": "work_for_docx.md",
}


def _artifact_paths(document_id: str, db: Session) -> dict[str, Path]:
    doc = document_model.get_document(db, document_id)
    directory = get_settings().doc_dir(doc.id)
    return {name: directory / relpath for name, relpath in ARTIFACTS.items()}


@router.get("/documents/{document_id}/artifacts", tags=["documents"],
            summary="Danh sách artifacts: chunks / validation / structured / DOCX Markdown")
def list_document_artifacts(document_id: str, db: DbSession):
    paths = _artifact_paths(document_id, db)
    return {"items": [{"name": name, "size": path.stat().st_size}
                      for name, path in paths.items() if path.is_file()]}


@router.get("/documents/{document_id}/artifacts/{name}", tags=["documents"],
            response_class=FileResponse, summary="Tải artifacts (whitelist)")
def read_document_artifact(document_id: str, name: str, db: DbSession):
    paths = _artifact_paths(document_id, db)
    path = paths.get(name)
    if path is None:
        raise AppError(404, "ARTIFACT_NOT_FOUND", "Artifact không được hỗ trợ.")
    if not path.is_file():
        raise AppError(404, "ARTIFACT_NOT_READY", "Artifact chưa được tạo.")
    return FileResponse(path,
                        media_type="application/json" if name.endswith(".json") else "text/markdown",
                        filename=name)
