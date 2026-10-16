"""_elapsed_s: DOCX xong -> mtime file; lỗi -> finished_at; đang chạy -> tới bây giờ."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from backend.app.controllers.compat_controller import _elapsed_s

T0 = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)


def _doc(**job):
    j = NS(created_at=T0, started_at=T0, finished_at=None, **job)
    return NS(jobs=[j], created_at=T0, updated_at=T0 + timedelta(seconds=7))


def test_ready_uses_docx_mtime(tmp_path):
    f = tmp_path / "o.docx"; f.write_bytes(b"x")
    os.utime(f, ((T0 + timedelta(seconds=250)).timestamp(),) * 2)
    assert _elapsed_s(_doc(), "ready", f) == 250


def test_failed_uses_finished_at(tmp_path):
    d = _doc(); d.jobs[0].finished_at = T0 + timedelta(seconds=42)
    assert _elapsed_s(d, "failed", tmp_path / "x") == 42


def test_building_runs_to_now(tmp_path):
    d = _doc(); d.jobs[0].started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    assert 29 <= _elapsed_s(d, "building", tmp_path / "x") <= 32
