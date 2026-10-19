"""Container: gom các đối tượng dùng chung (tạo 1 lần khi khởi động) + dependency cho controller."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, Request

from ..models.database import Database
from ..models.document_repository import DocumentRepository
from ..services.engine import Engine
from ..services.mineru_runner import MineruRunner
from ..services.pipeline import Pipeline
from ..services.rag_service import RagService
from ..services.scheduler import Scheduler
from ..services.storage import Storage
from ..services.upload_service import UploadService
from .config import Settings
from .errors import AppError

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class Container:
    settings: Settings
    db: Database
    repo: DocumentRepository
    storage: Storage
    engine: Engine
    runner: MineruRunner
    pipeline: Pipeline
    scheduler: Scheduler
    uploads: UploadService
    rag: RagService


def build_container(settings: Settings) -> Container:
    settings.ensure_dirs()
    db = Database(settings.db_path)
    db.init()
    repo = DocumentRepository(db)
    storage = Storage(settings)
    engine = Engine(settings)
    runner = MineruRunner(settings, engine)
    pipeline = Pipeline(settings, repo, storage, engine, runner)
    scheduler = Scheduler(settings, repo, storage, pipeline, runner)
    uploads = UploadService(settings, repo, storage, scheduler)
    rag = RagService(settings, storage, engine)
    return Container(settings, db, repo, storage, engine, runner, pipeline, scheduler, uploads, rag)


# ---- dependency của FastAPI ---------------------------------------------------------
def get_container(request: Request) -> Container:
    return request.app.state.container


def get_client_id(x_client_id: Optional[str] = Header(default=None)) -> str:
    """Mỗi trình duyệt gửi X-Client-Id (frontend/app.js tự sinh) -> thư viện tài liệu riêng của trình duyệt đó."""
    if x_client_id is None or x_client_id == "":
        return "anonymous"
    if not CLIENT_ID_RE.match(x_client_id):
        raise AppError(400, "BAD_CLIENT_ID", "X-Client-Id không hợp lệ.")
    return x_client_id
