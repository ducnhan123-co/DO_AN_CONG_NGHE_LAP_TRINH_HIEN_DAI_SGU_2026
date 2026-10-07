"""Controller: theo dõi tiến độ xử lý (job)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.models import document_model
from backend.app.models.database import get_db
from backend.app.views.schemas import JobOut, errors

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/jobs/{job_id}", tags=["jobs"], response_model=JobOut,
            summary="Theo dõi tiến độ xử lý", responses=errors(404))
def get_job(job_id: str, db: DbSession):
    return document_model.job_out(db, job_id)