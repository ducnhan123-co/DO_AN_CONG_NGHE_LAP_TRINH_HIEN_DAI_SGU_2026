"""Bố cục thư mục data/ (một nơi duy nhất biết đường dẫn):

data/
├── app.db
├── input/<doc_id>.pdf              PDF gốc (đã đổi tên theo id)
├── docx_output/<doc_id>.docx       kết quả Word
└── documents/<doc_id>/             1 thư mục cho mỗi lần chạy (thay cho runs/ của rag_toan)
    ├── logs/                       pipeline.log + log từng phần MinerU
    ├── mineru/                     kết quả MinerU đã ghép (.md, images/)
    ├── mineru_parts/               pdf/ + out/ của từng phần chạy song song
    ├── work.md                     Markdown đã chuẩn hóa đưa vào Pandoc
    ├── audit.json                  (audit.py) trang MinerU bỏ khối, nhảy số, LaTeX thô trong Word
    ├── math_repair.json            (math_repair.py) báo cáo các chỗ đã sửa
    ├── scan_clean.json             (scan_clean.py) các trang scan đã che dải trang bên cạnh
    ├── <id>__clean.pdf             PDF scan đã che (chỉ có khi có trang bị che)
    └── structured_data.json, chunks.json, validation.json, index/   (chỉ khi src có module RAG)
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import time
from pathlib import Path

from ..core.config import Settings

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Chỉ các file này được phép tải qua API artifacts
ARTIFACT_NAMES = ("work.md", "audit.json", "math_repair.json", "scan_clean.json",
                  "structured_data.json", "chunks.json", "validation.json")


class Storage:
    def __init__(self, settings: Settings):
        self.s = settings

    @staticmethod
    def valid_id(doc_id: str) -> bool:
        return bool(ID_RE.match(doc_id or ""))

    def _checked(self, doc_id: str) -> str:
        if not self.valid_id(doc_id):
            raise ValueError(f"doc_id không hợp lệ: {doc_id!r}")
        return doc_id

    def input_pdf(self, doc_id: str) -> Path:
        return self.s.input_dir / f"{self._checked(doc_id)}.pdf"

    def docx_path(self, doc_id: str) -> Path:
        return self.s.docx_dir / f"{self._checked(doc_id)}.docx"

    def docx_building_path(self, doc_id: str) -> Path:
        """File tạm (đuôi .docx để Pandoc nhận đúng định dạng); đổi tên nguyên tử khi xong."""
        return self.s.docx_dir / f".{self._checked(doc_id)}.building.docx"

    def run_dir(self, doc_id: str) -> Path:
        return self.s.documents_dir / self._checked(doc_id)

    def logs_dir(self, doc_id: str) -> Path:
        return self.run_dir(doc_id) / "logs"

    def pipeline_log(self, doc_id: str) -> Path:
        return self.logs_dir(doc_id) / "pipeline.log"

    def artifact(self, doc_id: str, name: str) -> Path | None:
        if name not in ARTIFACT_NAMES:
            return None
        p = self.run_dir(doc_id) / name
        return p if p.is_file() else None

    def make_run_dirs(self, doc_id: str) -> Path:
        d = self.run_dir(doc_id)
        (d / "logs").mkdir(parents=True, exist_ok=True)
        return d

    def docx_size(self, doc_id: str) -> int | None:
        p = self.docx_path(doc_id)
        return p.stat().st_size if p.is_file() else None

    def remove_all(self, doc_id: str) -> None:
        """Xóa toàn bộ dữ liệu của 1 tài liệu (có thử lại: Windows hay khóa file vài giây)."""
        for target in (self.input_pdf(doc_id), self.docx_path(doc_id), self.docx_building_path(doc_id)):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        self._rmtree(self.run_dir(doc_id))

    @staticmethod
    def _rmtree(path: Path, attempts: int = 5) -> None:
        def _onerror(func, p, _exc):
            try:
                os.chmod(p, stat.S_IWRITE)
                func(p)
            except OSError:
                pass

        for i in range(attempts):
            if not path.exists():
                return
            shutil.rmtree(path, onerror=_onerror)
            if not path.exists():
                return
            time.sleep(0.5 * (i + 1))
