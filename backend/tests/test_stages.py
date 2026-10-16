import os
import subprocess

import pytest

from backend.app.models import job_model
from backend.app.models import pipeline
from backend.app.models.database import Job, StageRun


def test_count_md_formulas():
    md = "a $x$ b $$\ny\n$$ c $5 và $10 d $z_1$"
    assert pipeline._count_md_formulas(md) >= 3


def test_build_and_validate_docx_real_pandoc(tmp_path):
    md = tmp_path / "work.md"
    md.write_text("# Chương 1\n\nCho $x^2+1$.\n\n$$\n\\frac{a}{b}=c\n$$\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    out = tmp_path / "o.docx"
    info = pipeline._build_docx(md, tmp_path, out, 120, tmp_path / "post.log")
    assert out.exists() and info["docx_bytes"] > 1000
    assert not (tmp_path / "o.building.docx").exists()                       # file tạm đã được thay bằng file thật
    v = pipeline._validate_docx(out, md.read_text(encoding="utf-8"))
    assert v["equations_docx"] >= 2 and v["tables"] == 1 and "warning" not in v
    assert (tmp_path / "post.log").exists()                                  # print của rag_toan được gom vào log


def test_validate_warns_when_formulas_missing(tmp_path):
    md = tmp_path / "w.md"
    md.write_text("Chỉ chữ.\n", encoding="utf-8")
    out = tmp_path / "o.docx"
    pipeline._build_docx(md, tmp_path, out, 120, tmp_path / "l.log")
    v = pipeline._validate_docx(out, "$a$ $b$ $c$ $d$")                        # markdown báo 4 công thức nhưng DOCX không có
    assert "warning" in v


def test_validate_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"khong phai docx")
    with pytest.raises(Exception):
        pipeline._validate_docx(bad, "")


def test_pandoc_missing(tmp_path, monkeypatch):
    md = tmp_path / "w.md"
    md.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(pipeline.PandocMissing):
        pipeline._build_docx(md, tmp_path, tmp_path / "o.docx", 30, tmp_path / "l.log")


def test_pandoc_timeout_stops(tmp_path, monkeypatch):
    md = tmp_path / "w.md"
    md.write_text("x", encoding="utf-8")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("pandoc", 1)
    monkeypatch.setattr("subprocess.run", boom)                                # cầu nối rag_toan: subprocess của build_docx -> timeout
    with pytest.raises(RuntimeError, match="Pandoc quá"):
        pipeline._build_docx(md, tmp_path, tmp_path / "o.docx", 1, tmp_path / "l.log")
    assert not (tmp_path / "o.building.docx").exists()


def _job(status, progress=0):
    return Job(id="j", document_id="d", status=status, progress=progress)


def test_estimate_progress_parsing_uses_pages_and_measured_speed():
    from backend.app.core.config import get_settings
    s = get_settings()
    runs = [StageRun(stage="parse", shard_index=1, page_from=1, page_to=23, status="done", duration_s=100.0, started_at=0.0),
            StageRun(stage="parse", shard_index=2, page_from=24, page_to=46, status="running", started_at=1000.0)]
    p0 = job_model.estimate_progress(_job("parsing"), runs, s, t=1000.0)       # phần 2 vừa bắt đầu
    p1 = job_model.estimate_progress(_job("parsing"), runs, s, t=1050.0)       # chạy được 50s
    p2 = job_model.estimate_progress(_job("parsing"), runs, s, t=9999.0)       # chạy rất lâu: trần 92% của phần đó
    assert 5 + 37 < p0 < p1 < p2 < 5 + 75
    assert job_model.estimate_progress(_job("done"), [], s) == 100.0
    assert job_model.estimate_progress(_job("building", 90), [], s) == 90.0
    assert job_model.estimate_progress(_job("failed", 37), [], s) == 37.0
