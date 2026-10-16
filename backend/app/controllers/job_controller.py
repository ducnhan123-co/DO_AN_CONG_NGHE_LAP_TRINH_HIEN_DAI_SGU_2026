"""Controller: chi tiết job và luồng SSE theo dõi tiến độ."""
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.models import document_model as dm
from backend.app.models.database import SessionLocal, TERMINAL, get_db
from backend.app.views.schemas import JobOut, errors

router = APIRouter(prefix="/jobs", tags=["jobs"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{job_id}", response_model=JobOut, summary="Chi tiết job và thời gian từng bước", responses=errors(404))
def get_job(job_id: str, db: DbSession):
    return dm.job_out(db, job_id)


@router.get("/{job_id}/events", summary="SSE tiến độ: mỗi khi trạng thái hoặc tiến độ đổi gửi sự kiện `progress`; kết thúc bằng `end`",
            responses={200: {"content": {"text/event-stream": {}}, "description": "event: progress | end"}, **errors(404)})
def events(job_id: str, db: DbSession):
    dm.job_out(db, job_id)                                    # 404 trước khi bắt đầu stream

    def gen():
        last = None
        while True:
            with SessionLocal() as s:
                out = dm.job_out(s, job_id)
            sig = (out.status, out.progress, len(out.stages), tuple(x.status for x in out.stages))
            if sig != last:
                last = sig
                yield f"event: progress\ndata: {json.dumps(out.model_dump(), ensure_ascii=False)}\n\n"
            if out.status in TERMINAL:
                yield "event: end\ndata: {}\n\n"
                return
            yield ": keep-alive\n\n"
            time.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream")
