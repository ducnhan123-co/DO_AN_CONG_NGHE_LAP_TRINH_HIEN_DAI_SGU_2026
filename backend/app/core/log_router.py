"""Chuyển print() của code rag_toan vào đúng file log của từng tài liệu.

Code rag_toan (build_docx, columns...) chỉ dùng print(). Nhiều tài liệu chạy song song trong nhiều
thread, nên thay sys.stdout bằng một proxy phân luồng theo thread: thread nào đang xử lý tài liệu nào
thì print() của nó đi vào data/documents/<id>/logs/pipeline.log (và vẫn in ra console như thường).
"""
from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_local = threading.local()


class _Router:
    def __init__(self, original):
        self._orig = original

    def write(self, s):
        f = getattr(_local, "file", None)
        if f is not None and s:
            try:
                f.write(s)
                f.flush()
            except Exception:
                pass
        try:
            return self._orig.write(s)
        except UnicodeEncodeError:          # console Windows cp1252...
            enc = getattr(self._orig, "encoding", None) or "ascii"
            return self._orig.write(s.encode(enc, "replace").decode(enc))

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._orig, name)


def install() -> None:
    """Cài proxy; gọi lại an toàn (nếu ai đó thay sys.stdout sau đó, cài lại)."""
    if not isinstance(sys.stdout, _Router):
        sys.stdout = _Router(sys.stdout)


@contextmanager
def capture_to(log_path: Path):
    """Trong khối with: print() của thread hiện tại được ghi thêm vào log_path."""
    install()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, "a", encoding="utf-8")
    prev = getattr(_local, "file", None)
    _local.file = f
    try:
        yield f
    finally:
        _local.file = prev
        f.close()


def log_line(msg: str) -> None:
    """Ghi 1 dòng có mốc thời gian (vào log tài liệu nếu thread đang capture)."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
