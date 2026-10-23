"""Đọc cấu hình từ backend/.env và cung cấp các đường dẫn dữ liệu dùng chung."""
import sys
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]   # .../backend
ROOT_DIR = BACKEND_DIR.parent                        # thư mục gốc dự án

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env",
                                      env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Math PDF Chat API"
    database_url: str = ""
    data_dir: Path = BACKEND_DIR / "data"
    max_upload_mb: int = 50
    top_k: int = 5
    log_level: str = "INFO"
    cors_origins: List[str] = ["*"]
    api_prefix: str = "/api" 

    max_queued_jobs: int = 6        # số job (queued+running) tối đa, vượt thì từ chối upload (429)
    chat_history_turns: int = 3     # số lượt hỏi-đáp gần nhất đưa vào ngữ cảnh chat

    ai_pipeline_enabled: bool = False  # Render Free safe by default; Mac starts this
    kiet_cli_enabled: bool = True        # existing upload/job API drives Kiệt's CLI
    kiet_tier: str = "advanced"          # exact Kiệt default; use standard for smoke tests
    kiet_timeout_s: int = 3600
    mineru_prewarm: bool = False
    serve_frontend: bool = False  # Mac tunnel: serve static UI from API origin
    demo_auth_user: str = ""           # enable Basic Auth for temporary tunnel demos
    demo_auth_password: str = ""       # never commit the password


    @model_validator(mode="after")
    def _defaults(self):
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"
        return self

    def doc_dir(self, doc_id: str) -> Path:
        return self.data_dir / "documents" / doc_id

    def pdf_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "input.pdf"

    def docx_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "output.docx"

    def mineru_dir(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "mineru"

    def rag_dir(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "rag"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def setup_logging(level: str = "INFO") -> None:
    import logging
    logging.basicConfig(level=level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")