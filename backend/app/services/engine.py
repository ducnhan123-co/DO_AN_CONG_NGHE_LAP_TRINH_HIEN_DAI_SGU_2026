"""Cầu nối tới thư mục rag_toan (lõi). Backend KHÔNG sửa rag_toan: chỉ import các hàm của nó.

rag_toan dùng gói `src` (src/build_docx.py, src/parallel_mineru.py ...) nên cần thêm thư mục rag_toan vào
sys.path. Import trễ (lần dùng đầu tiên) để server vẫn khởi động được và báo lỗi rõ ràng nếu thiếu thư viện.
"""
from __future__ import annotations

import shlex
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from ..core.config import Settings
from ..core.errors import PipelineError


class Engine:
    def __init__(self, settings: Settings):
        self.s = settings
        self._ns: Optional[SimpleNamespace] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ kiểm tra môi trường
    @property
    def found(self) -> bool:
        return (self.s.engine_dir / "src" / "build_docx.py").is_file()

    @property
    def mineru_argv0(self) -> str:
        parts = shlex.split(self.s.mineru_cmd, posix=False) or [self.s.mineru_cmd]
        return parts[0].strip('"')

    @property
    def mineru_found(self) -> bool:
        return shutil.which(self.mineru_argv0) is not None

    @property
    def pandoc_found(self) -> bool:
        return shutil.which("pandoc") is not None

    @property
    def tesseract_found(self) -> bool:
        return shutil.which("tesseract") is not None

    def mineru_command(self, part_pdf: Path, out_dir: Path) -> list:
        """Giống hệt lệnh của rag_toan: mineru-kit parse <pdf> -o <out> --tier <tier> (+ tham số thêm nếu có)."""
        base = shlex.split(self.s.mineru_cmd, posix=False) or [self.s.mineru_cmd]
        base = [b.strip('"') for b in base]
        cmd = base + ["parse", str(part_pdf), "-o", str(out_dir), "--tier", self.s.mineru_tier]
        if self.s.mineru_extra_args.strip():
            cmd += shlex.split(self.s.mineru_extra_args, posix=False)
        return cmd

    # ------------------------------------------------------------------ import trễ
    def load(self) -> SimpleNamespace:
        if self._ns is not None:
            return self._ns
        with self._lock:
            if self._ns is not None:
                return self._ns
            if not self.found:
                raise PipelineError(
                    "ENGINE_NOT_FOUND",
                    f"Không thấy thư mục rag_toan tại {self.s.engine_dir} (cần có src/build_docx.py). "
                    f"Đặt biến RAG_ENGINE_DIR nếu để ở chỗ khác.")
            p = str(self.s.engine_dir)
            if p not in sys.path:
                sys.path.insert(0, p)
            try:
                from src import (build_docx, chunking, column_split, columns, config as rag_cfg,  # noqa: E501
                                 frame_layout, parallel_mineru, postprocess, run_mineru, structured, validate)
            except ImportError as ex:
                raise PipelineError(
                    "ENGINE_IMPORT_FAILED",
                    f"Không nạp được code rag_toan: {ex}. Cài đủ thư viện trong requirements.txt.") from ex
            self._ns = SimpleNamespace(
                build_docx=build_docx, chunking=chunking, column_split=column_split, columns=columns,
                cfg=rag_cfg, frame_layout=frame_layout, parallel=parallel_mineru, postprocess=postprocess,
                run_mineru=run_mineru, structured=structured, validate=validate)
            return self._ns
