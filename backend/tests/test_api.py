import importlib
import json
import os
import tempfile
import time
from io import BytesIO

from fastapi.testclient import TestClient

os.environ["PDF2DOCX_STORAGE"] = tempfile.mkdtemp()
main = importlib.import_module("backend.app.main")
client = TestClient(main.app)


def make_pdf() -> bytes:
    from pypdf import PdfWriter

    buf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    return buf.getvalue()


def make_job(job_id: str = "abc123abc123", **fields):
    from backend.app import jobs

    d = jobs.JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "input.pdf").write_bytes(make_pdf())
    job = {"id": job_id, "name": "Đề 1", "filename": "de.pdf", "num_pages": 1, "size_bytes": 10,
           "status": "done", "created": time.time(), "tier": "advanced", "workers": 2,
           "started": time.time() - 60, "finished": time.time()}
    job.update(fields)
    (d / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return d


def test_frontend_served():
    page = client.get("/").text
    assert "Từ PDF toán sang Word" in page


def test_rejects_non_pdf():
    r = client.post("/api/documents", files=[("files", ("a.pdf", b"hello", "application/pdf"))])
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "UPLOAD_REJECTED"


def test_rejects_bad_tier():
    r = client.post("/api/documents", files=[("files", ("a.pdf", b"%PDF-1.4", "application/pdf"))],
                    data={"tier": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_TIER"


def test_unknown_id_is_404():
    assert client.get("/api/documents/000000000000").status_code == 404
    assert client.get("/api/documents/not-a-valid-id").status_code == 404


def test_health_and_stats():
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["engine_found"] is True
    assert health["tier"] == "advanced"
    stats = client.get("/api/system/stats").json()
    assert isinstance(stats["running"], list)
    assert stats["main_slots"] == 1


def test_list_rename_delete():
    d = make_job()
    items = client.get("/api/documents").json()["items"]
    assert any(i["id"] == "abc123abc123" and i["name"] == "Đề 1" for i in items)

    r = client.patch("/api/documents/abc123abc123", json={"display_name": "  Đề số 2  "})
    assert r.status_code == 200
    assert r.json()["name"] == "Đề số 2"

    assert client.patch("/api/documents/abc123abc123", json={"display_name": "  "}).status_code == 400
    assert client.patch("/api/documents/abc123abc123", json={"display_name": "x" * 201}).status_code == 400

    assert client.get("/api/documents/abc123abc123/docx").status_code == 409
    assert client.get("/api/documents/abc123abc123/pdf").headers["content-type"] == "application/pdf"

    assert client.delete("/api/documents/abc123abc123").status_code == 204
    assert not d.exists()
    assert client.get("/api/documents/abc123abc123").status_code == 404


def test_done_document_renders_audit_note():
    d = make_job(job_id="def456def456")
    (d / "out").mkdir()
    (d / "out" / "de.docx").write_bytes(b"PK\x03\x04")
    (d / "out" / "audit.json").write_text(json.dumps({
        "dropped_pages": [{"page": 3, "dropped": 1}],
        "numbering_gaps": [],
        "docx": {"equations": 12, "raw_latex_paragraphs": 2, "samples": []},
    }), encoding="utf-8")
    doc = client.get("/api/documents/def456def456").json()
    assert doc["status"] == "done"
    assert doc["docx_available"] is True
    assert doc["docx_size"] == 4
    note = doc["stages"][-1]["note"]
    assert note["equations_docx"] == 12
    assert note["raw_latex_paragraphs"] == 2
    assert "bỏ khối" in note["warning"]


def test_retry_requires_failure():
    make_job(job_id="aaa111aaa111", status="done")
    assert client.post("/api/documents/aaa111aaa111/retry").status_code == 409
    assert client.post("/api/documents/aaa111aaa111/cancel").status_code == 409


def test_failed_document_renders_error_and_steps():
    make_job(job_id="bbb222bbb222", status="failed", error_code="MINERU_FAILED",
             error_message="mineru-kit: command not found")
    doc = client.get("/api/documents/bbb222bbb222").json()
    assert doc["status"] == "failed"
    assert doc["error"]["code"] == "MINERU_FAILED"
    assert doc["docx_available"] is False
    assert doc["stages"][0]["status"] in ("failed", "done", "planned")


def test_queued_document_has_zero_progress():
    make_job(job_id="ccc333ccc333", status="queued", started=None, finished=None)
    doc = client.get("/api/documents/ccc333ccc333").json()
    assert doc["status"] == "queued"
    assert doc["progress"] == 0.0
    assert all(s["status"] == "planned" for s in doc["stages"])
