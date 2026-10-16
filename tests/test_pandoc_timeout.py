"""Pandoc treo -> báo lỗi rõ ràng thay vì kẹt thread DOCX mãi."""
import subprocess

import pytest

from llm.src import build_docx


def test_pandoc_timeout_becomes_runtime_error(monkeypatch):
    def boom(*a, **k):
        assert k["timeout"] == build_docx.PANDOC_TIMEOUT_S
        raise subprocess.TimeoutExpired(a[0], k["timeout"])
    monkeypatch.setattr(build_docx.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="Pandoc quá"):
        build_docx._run_pandoc(["pandoc", "x"])
