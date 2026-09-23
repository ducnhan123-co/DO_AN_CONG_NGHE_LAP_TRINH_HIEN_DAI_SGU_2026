"""Controller: tải file DOCX đã xử lý."""
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.core.config import DOCX_MIME
from backend.app.models import document_model
from backend.app.models.database import get_db
from backend.app.views.schemas import errors

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/documents/{document_id}/export/docx", tags=["export"],
            summary="Tải file DOCX", response_class=FileResponse,
            responses={200: {"content": {DOCX_MIME: {}}, "description": "File DOCX"},
                       **errors(404, 409)})
def export_docx(document_id: str, db: DbSession):
    path, filename = document_model.get_docx(db, document_id)
    return FileResponse(path, media_type=DOCX_MIME, filename=filename)