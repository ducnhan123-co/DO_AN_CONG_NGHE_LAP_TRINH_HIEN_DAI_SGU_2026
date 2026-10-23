"""Regression: Kiệt original CLI is invoked without an extra API or DOCX changes."""
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

from backend.app.core.config import get_settings
from backend.app.models.kiet_cli_adapter import _import_kiet_results, _paragraph_chunks
from backend.app.models.database import Document, DocumentStatus, Job, SessionLocal


def _fake_output(work: Path):
    docx = work / "docx_output" / "input.docx"
    docx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml",
                         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    run = work / "runs" / "input_abcdefghij"
    (run / "mineru").mkdir(parents=True, exist_ok=True)
    (run / "audit.json").write_text('{"math":35}', encoding="utf-8")
    (run / "repair_report.json").write_text('{"diacritic_fixes":2}', encoding="utf-8")
    (run / "mineru" / "input.md").write_text(
        r"## Công thức" + "\n\n" + r"$$\int_0^1 x dx$$",
        encoding="utf-8")
    (work / "docx_output" / "input_for_docx.md").write_text(
        "DOCX source from Kiệt", encoding="utf-8")
    return docx


def test_kiet_artifact_import_byte_for_byte(tmp_path):
    work = tmp_path / "work"
    original = _fake_output(work)
    target = tmp_path / "target"
    target.mkdir()
    fake_doc = SimpleNamespace(id="abc123", filename="input.pdf")
    sections, chunks = _import_kiet_results(fake_doc, work, target)
    assert (target / "output.docx").read_bytes() == original.read_bytes()
    assert sections == 1
    assert chunks >= 1
    assert json.loads((target / "audit.json").read_text())["math"] == 35
    assert json.loads((target / "repair_report.json").read_text())["diacritic_fixes"] == 2
    lookup = json.loads((target / "chunks.json").read_text())
    assert lookup[0]["page"] is None  # Advanced Markdown has no verified page map
    assert json.loads((target / "validation.json").read_text())["page_mapping"] == "unknown"


def test_kiet_missing_audit_never_publishes_word(tmp_path):
    work = tmp_path / "work"
    _fake_output(work)
    (work / "runs" / "input_abcdefghij" / "audit.json").unlink()
    target = tmp_path / "target"
    target.mkdir()
    doc = SimpleNamespace(id="abc", filename="input.pdf")
    import pytest
    with pytest.raises(RuntimeError, match="audit.json"):
        _import_kiet_results(doc, work, target)
    assert not (target / "output.docx").exists()


def test_kiet_cli_bridge_jobs_use_isolated_workspace(monkeypatch, client):
    from backend.app.models import kiet_cli_adapter as bridge
    from backend.app.models import pipeline_model
    from backend.app.models.database import JobStatus

    settings = get_settings()
    monkeypatch.setattr(settings, "kiet_cli_enabled", True)
    monkeypatch.setattr(settings, "kiet_tier", "standard")
    with SessionLocal() as db:
        doc = Document(filename="kiet-input.pdf", status=DocumentStatus.indexing.value)
        db.add(doc)
        db.flush()
        job = Job(document_id=doc.id, status=JobStatus.queued.value,
                  stage=DocumentStatus.indexing.value)
        db.add(job)
        db.commit()
        did, jid = doc.id, job.id
    target = settings.doc_dir(did)
    target.mkdir(parents=True, exist_ok=True)
    settings.pdf_path(did).write_bytes(b"%PDF-1.4\n%smoke\n")

    commands = []
    def fake_subprocess(cmd, cwd, env, stdout, stderr, timeout, check):
        assert cmd[0] == sys.executable
        assert cmd[1].endswith("kiet_cli.py")
        assert "--workers" in cmd
        assert cmd[cmd.index("--workers") + 1] == "1"
        assert cmd[cmd.index("--tier") + 1] == "standard"
        assert str(target / "kiet_work") == env["KIET_WORK_ROOT"]
        commands.append(cmd)
        _fake_output(Path(env["KIET_WORK_ROOT"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge.subprocess, "run", fake_subprocess)
    pipeline_model.run_pipeline(did, jid)
    with SessionLocal() as db:
        doc = db.get(Document, did)
        job = db.get(Job, jid)
        assert doc.status == DocumentStatus.ready.value
        assert job.status == JobStatus.succeeded.value
        assert doc.num_chunks > 0
        assert settings.docx_path(did).exists()
        assert (target / "audit.json").exists()
    assert len(commands) == 1


def test_cross_origin_basic_preflight_with_render(client, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    cfg = get_settings()
    monkeypatch.setattr(cfg, "demo_auth_user", "demo")
    monkeypatch.setattr(cfg, "demo_auth_password", "temporary_secret")
    with TestClient(create_app()) as c:
        headers = {
            "Origin": "https://sgu-pdf-rag-frontend.onrender.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        preflight = c.options("/api/upload", headers=headers)
        assert preflight.status_code == 200, preflight.text
        assert preflight.headers["access-control-allow-origin"] == "*"
        assert "authorization" in preflight.headers.get("access-control-allow-headers", "").lower()
        denied = c.get("/api/health", headers={"Origin": headers["Origin"]})
        assert denied.status_code == 401
        assert denied.headers["access-control-allow-origin"] == "*"
        authorized = c.get("/api/health", auth=("demo", "temporary_secret"),
                           headers={"Origin": headers["Origin"]})
        assert authorized.status_code == 200
