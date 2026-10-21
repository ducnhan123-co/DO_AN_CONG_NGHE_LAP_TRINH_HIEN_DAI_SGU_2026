"""Cầu nối tới thư mục rag_toan (lõi). Backend KHÔNG sửa rag_toan: chỉ import các hàm của nó.

rag_toan dùng gói `src` (src/build_docx.py, src/parallel_mineru.py ...) nên cần thêm thư mục rag_toan vào
sys.path. Import trễ (lần dùng đầu tiên) để server vẫn khởi động được và báo lỗi rõ ràng nếu thiếu thư viện.
"""
from __future__ import annotations

import importlib
import logging
import shlex
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from ..core.config import Settings
from ..core.errors import PipelineError

log = logging.getLogger("engine")


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
    # Bắt buộc: thiếu là không dựng được Word.
    _REQUIRED = ("build_docx", "column_split", "columns", "config", "frame_layout", "parallel_mineru", "run_mineru")
    # Tùy chọn: module bổ sung của src (thiếu file -> tính năng đó tự tắt, pipeline vẫn chạy).
    _OPTIONAL = ("scan_clean", "math_repair", "image_size", "audit",            # cải thiện Word
                 "structured", "chunking", "validate", "postprocess",           # dữ liệu RAG (bản src cũ)
                 "llama_rag")                                                   # index RAG (bản src cũ)
    _RAG_SET = ("structured", "chunking", "validate", "postprocess")

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
            ns = SimpleNamespace()
            for name in self._REQUIRED:
                try:
                    setattr(ns, name, importlib.import_module(f"src.{name}"))
                except ImportError as ex:
                    raise PipelineError(
                        "ENGINE_IMPORT_FAILED",
                        f"Không nạp được src.{name} của rag_toan: {ex}. Cài đủ thư viện trong requirements.txt.") from ex
            for name in self._OPTIONAL:
                setattr(ns, name, self._import_optional(name))
            ns.cfg = ns.config                                   # tên cũ backend vẫn dùng
            ns.parallel = ns.parallel_mineru
            ns.rag_ok = all(getattr(ns, n) is not None for n in self._RAG_SET)
            log.info("rag_toan/src: module tùy chọn có mặt = %s | dữ liệu RAG: %s",
                     [n for n in self._OPTIONAL if getattr(ns, n) is not None], "có" if ns.rag_ok else "không (src mới đã bỏ)")
            self._ns = ns
            return ns

    @staticmethod
    def _import_optional(name: str):
        """None nếu file không có trong src; nếu file có mà lỗi import (thiếu thư viện...) thì cảnh báo rõ rồi tắt."""
        try:
            return importlib.import_module(f"src.{name}")
        except ModuleNotFoundError as ex:
            if ex.name == f"src.{name}":                         # chính module đó không tồn tại
                return None
            log.warning("src.%s có mặt nhưng thiếu thư viện '%s' -> tắt tính năng này", name, ex.name)
            return None
        except Exception as ex:                                  # noqa: BLE001
            log.warning("src.%s lỗi khi nạp (%s: %s) -> tắt tính năng này", name, type(ex).__name__, ex)
            return None
