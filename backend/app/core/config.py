"""Cấu hình toàn backend. Mọi thứ đổi được bằng biến môi trường hoặc file .env (cạnh run.py).

Giá trị mặc định của pipeline GIỐNG main.py của rag_toan (workers=2, stagger=20s, profile=auto...).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]          # .../backend
PROJECT_ROOT = BACKEND_DIR.parent                          # .../rag_toan


def _load_dotenv(path: Path) -> None:
    """Đọc .env đơn giản (KEY=VALUE), không ghi đè biến môi trường đã có."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    # ---- đường dẫn -------------------------------------------------------
    engine_dir: Path = PROJECT_ROOT / "rag_toan"
    frontend_dir: Path = PROJECT_ROOT / "frontend"
    data_dir: Path = BACKEND_DIR / "data"

    # ---- server ----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list = field(default_factory=lambda: ["*"])
    serve_frontend: bool = True

    # ---- upload ----------------------------------------------------------
    max_upload_mb: int = 100
    max_files_per_request: int = 20
    max_pages: int = 1000

    # ---- lập lịch --------------------------------------------------------
    main_slots: int = 1                 # số TÀI LIỆU chạy cùng lúc
    mineru_workers: int = 2             # số tiến trình MinerU cho 1 tài liệu (như --workers)
    mineru_stagger: float = 20.0        # giây chờ giữa các tiến trình MinerU (như --stagger)
    min_pages_per_worker: int = 5
    max_mineru_procs: int = 0           # trần tổng tiến trình MinerU toàn máy; 0 = main_slots*workers
    sec_per_page: float = 6.0           # ước lượng ban đầu để vẽ thanh tiến độ (tự học sau mỗi lần chạy)

    # ---- MinerU ----------------------------------------------------------
    mineru_cmd: str = "mineru-kit"
    mineru_tier: str = "advanced"
    mineru_extra_args: str = ""         # vd: "--remote --api-key XXXX" để dùng mineru.net thay vì model cục bộ

    # ---- pipeline (như các cờ của main.py) ----------------------------------
    profile: str = "auto"
    no_columns: bool = False
    no_frame: bool = False
    no_split: bool = False
    ocr_lang: str = "eng"
    col_font_pt: float = 8.0

    # ---- RAG -------------------------------------------------------------------
    rag_artifacts: bool = True          # sinh structured_data / chunks / validation (nhẹ)
    rag_index: bool = False             # dựng LlamaIndex E5 (nặng: torch + model ~1GB)

    # ---- đường dẫn dẫn xuất ---------------------------------------------------
    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def input_dir(self) -> Path:
        return self.data_dir / "input"

    @property
    def docx_dir(self) -> Path:
        return self.data_dir / "docx_output"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def procs_cap(self) -> int:
        return self.max_mineru_procs or max(1, self.main_slots * self.mineru_workers)

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.documents_dir, self.input_dir, self.docx_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    _load_dotenv(BACKEND_DIR / ".env")
    s = Settings()
    s.engine_dir = Path(_env("RAG_ENGINE_DIR", str(s.engine_dir))).resolve()
    s.frontend_dir = Path(_env("FRONTEND_DIR", str(s.frontend_dir))).resolve()
    s.data_dir = Path(_env("DATA_DIR", str(s.data_dir))).resolve()
    s.host = _env("HOST", s.host)
    s.port = _int("PORT", s.port)
    origins = _env("CORS_ORIGINS", "*")
    s.cors_origins = ["*"] if origins.strip() == "*" else [o.strip() for o in origins.split(",") if o.strip()]
    s.serve_frontend = _bool("SERVE_FRONTEND", True)
    s.max_upload_mb = _int("MAX_UPLOAD_MB", s.max_upload_mb)
    s.max_files_per_request = _int("MAX_FILES_PER_REQUEST", s.max_files_per_request)
    s.max_pages = _int("MAX_PAGES", s.max_pages)
    s.main_slots = max(1, _int("MAIN_SLOTS", s.main_slots))
    s.mineru_workers = max(1, _int("MINERU_WORKERS", s.mineru_workers))
    s.mineru_stagger = _float("MINERU_STAGGER", s.mineru_stagger)
    s.min_pages_per_worker = max(1, _int("MIN_PAGES_PER_WORKER", s.min_pages_per_worker))
    s.max_mineru_procs = _int("MAX_MINERU_PROCS", s.max_mineru_procs)
    s.sec_per_page = _float("SEC_PER_PAGE", s.sec_per_page)
    s.mineru_cmd = _env("MINERU_CMD", s.mineru_cmd)
    s.mineru_tier = _env("MINERU_TIER", s.mineru_tier)
    s.mineru_extra_args = _env("MINERU_EXTRA_ARGS", s.mineru_extra_args)
    s.profile = _env("PROFILE", s.profile)
    s.no_columns = _bool("NO_COLUMNS", s.no_columns)
    s.no_frame = _bool("NO_FRAME", s.no_frame)
    s.no_split = _bool("NO_SPLIT", s.no_split)
    s.ocr_lang = _env("OCR_LANG", s.ocr_lang)
    s.col_font_pt = _float("COL_FONT_PT", s.col_font_pt)
    s.rag_artifacts = _bool("RAG_ARTIFACTS", s.rag_artifacts)
    s.rag_index = _bool("RAG_INDEX", s.rag_index)
    return s
