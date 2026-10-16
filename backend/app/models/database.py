"""app.db duy nhất: documents, jobs, stage_runs. Thời gian lưu dạng epoch giây (REAL) cho đơn giản và không lệch múi giờ."""
import secrets
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from backend.app.core.config import get_settings

settings = get_settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(settings.database_url,
                       connect_args={"check_same_thread": False, "timeout": 15} if _is_sqlite else {},
                       pool_pre_ping=True)

if _is_sqlite:
    database_path = engine.url.database
    if database_path and database_path != ":memory:" and not database_path.startswith("file:"):
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Status(str, Enum):
    queued = "queued"
    parsing = "parsing"          # MinerU đang chạy các phần
    merging = "merging"          # ghép các phần (bỏ qua nếu 1 phần)
    preparing = "preparing"      # sửa markdown cho Pandoc
    building = "building"        # Pandoc + hậu xử lý DOCX
    validating = "validating"    # mở thử DOCX, đếm công thức
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


ACTIVE = {Status.queued.value, Status.parsing.value, Status.merging.value, Status.preparing.value,
          Status.building.value, Status.validating.value}
TERMINAL = {Status.done.value, Status.failed.value, Status.cancelled.value}

DOC_ID_LEN = 10


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex


def new_doc_id() -> str:
    return secrets.token_hex(DOC_ID_LEN // 2)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(DOC_ID_LEN), primary_key=True, default=new_doc_id)
    client_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    filename: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    num_pages: Mapped[int] = mapped_column(Integer, default=0)
    tier: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default=Status.queued.value, index=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    docx_size: Mapped[int] = mapped_column(Integer, default=0)
    docx_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now, onupdate=now)
    finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    jobs: Mapped[list["Job"]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                             order_by="Job.created_at")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(String(DOC_ID_LEN), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=Status.queued.value, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)          # 0-100, mức thô đã ghi DB
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    plan_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # [[from,to],...] kế hoạch chia phần
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=now)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    document: Mapped[Document] = relationship(back_populates="jobs")
    stage_runs: Mapped[list["StageRun"]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                                        order_by="StageRun.id")


class StageRun(Base):
    """Một bước của một job: parse (từng phần), merge, prepare, build, validate, cache."""
    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    shard_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    slot: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)           # main | aux
    status: Mapped[str] = mapped_column(String(12), default="planned")              # planned|running|done|failed|cancelled
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    peak_ram_gb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)                # JSON/ghi chú ngắn

    job: Mapped[Job] = relationship(back_populates="stage_runs")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
