"""Cấu hình đọc từ backend/.env (xem .env.example) + các đường dẫn dữ liệu dùng chung.

Mọi dữ liệu (app.db, PDF, kết quả MinerU, DOCX, log) nằm dưới backend/data — không còn ghi ra rag_toan.
"""
from functools import lru_cache
from pathlib import Path
import re
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]      # .../backend
ROOT_DIR = BACKEND_DIR.parent                          # thư mục chứa backend/ và frontend/

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "PDF to DOCX API"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    cors_origins: List[str] = ["*"]
    data_dir: Path = BACKEND_DIR / "data"
    database_url: str = ""                  # rỗng -> sqlite:///<data_dir>/app.db
    frontend_dir: Path = ROOT_DIR / "frontend"

    # --- upload ---
    max_upload_mb: int = 100
    max_files_per_request: int = 20
    max_active_jobs: int = 50               # vượt quá thì từ chối upload (429)

    # --- MinerU (mineru-kit) ---
    rag_toan_dir: str = ""                  # rỗng = tự tìm dự án rag_toan đầy đủ cạnh backend/
    mineru_cmd: str = "mineru-kit"          # có thể là "python /đường/dẫn/fake.py" khi test
    mineru_format: str = "markdown"         # markdown: `parse -o` ra 1 file .md, ảnh nhúng base64 (cách rag_toan đang dùng)
                                            # zip: `parse -f zip` ra markdown.md + images/ (kiểu cũ)
    mineru_tier: str = "advanced"           # rag_toan/src/config.py dùng "advanced"; số đo thời gian trước đây là "standard"
    mineru_ocr_mode: str = "auto"           # auto | txt | ocr (đo thực tế: txt và auto không khác biệt đáng kể)
    mineru_workers: int = 2                  # số tiến trình MinerU chạy đồng thời trong một tài liệu
    mineru_min_pages_per_worker: int = 5     # file ngắn tự giảm số tiến trình như rag_toan/main.py
    mineru_stagger_s: float = 20.0           # giãn thời điểm khởi chạy để tránh nạp model cùng lúc
    mineru_timeout_min_s: int = 900
    mineru_timeout_per_page_s: int = 90
    # --- Pandoc / DOCX ---
    pandoc_timeout_s: int = 900
    est_seconds_per_page: float = 0.0       # chỉ để ước lượng thanh tiến độ khi chưa có số đo; 0 = tự chọn theo tier

    @model_validator(mode="after")
    def _defaults(self):
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"
        return self

    # --- đường dẫn theo tài liệu ---
    def doc_dir(self, doc_id: str) -> Path:
        return self.data_dir / "documents" / doc_id

    def pdf_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "input.pdf"

    def docx_path(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "output.docx"

    def mineru_dir(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "mineru"

    def work_md(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "work.md"

    def logs_dir(self, doc_id: str) -> Path:
        return self.doc_dir(doc_id) / "logs"

    def input_dir(self) -> Path:
        return self.data_dir / "input"

    def docx_output_dir(self) -> Path:
        return self.data_dir / "docx_output"

    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @staticmethod
    def _safe_stem(name: str) -> str:
        stem = Path(name).stem
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
        return (stem or "document")[:180]

    def input_mirror_path(self, doc_id: str, filename: str) -> Path:
        return self.input_dir() / f"{doc_id}_{self._safe_stem(filename)}.pdf"

    def docx_mirror_path(self, doc_id: str, display_name: str) -> Path:
        return self.docx_output_dir() / f"{doc_id}_{self._safe_stem(display_name)}.docx"

    def work_md_mirror_path(self, doc_id: str, display_name: str) -> Path:
        return self.docx_output_dir() / f"{doc_id}_{self._safe_stem(display_name)}_for_docx.md"

    def run_dir(self, doc_id: str, filename: str) -> Path:
        return self.runs_dir() / f"{self._safe_stem(filename)}_{doc_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
