import pytest

from backend.app.core.config import get_settings
from backend.app.models import pipeline_model
from backend.app.models.database import Message, SessionLocal


def _upload(client, data: bytes, name="bai_giang.pdf", ctype="application/pdf"):
    return client.post("/documents", files={"file": (name, data, ctype)})


def _chat(client, doc_id, **body):
    return client.post(f"/documents/{doc_id}/chat", json={"question": "Đạo hàm là gì?", **body})


@pytest.fixture
def fake_search(monkeypatch):
    def _fake(doc_id, question, top_k):
        return [{"chunk_id": 3, "heading": "Định nghĩa 1.2", "score": 0.81,
                 "text": "Đạo hàm của hàm số f tại x0 là giới hạn của tỉ số..."}]
    monkeypatch.setattr(pipeline_model, "search", _fake)


# health, documents
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_upload_pdf_returns_202_with_ids(client, pdf_bytes):
    r = _upload(client, pdf_bytes)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["document_id"] and body["job_id"]
    assert r.headers["location"] == f"/jobs/{body['job_id']}"


def test_get_document(client, pdf_bytes):
    doc_id = _upload(client, pdf_bytes).json()["document_id"]
    r = client.get(f"/documents/{doc_id}")
    assert r.status_code == 200
    assert r.json()["filename"] == "bai_giang.pdf"
    assert r.json()["docx_available"] is False


def test_get_document_not_found(client):
    r = client.get("/documents/khong-ton-tai")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_upload_rejects_non_pdf_extension(client):
    r = _upload(client, b"hello", name="a.txt", ctype="text/plain")
    assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_upload_rejects_fake_pdf(client):
    assert _upload(client, b"khong phai pdf").status_code == 415


def test_upload_rejects_empty_file(client):
    r = _upload(client, b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_FILE"


def test_upload_missing_file_is_422(client):
    r = client.post("/documents")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_upload_too_large(client, pdf_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = _upload(client, pdf_bytes)
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


# jobs
def test_job_after_upload(client, pdf_bytes):
    up = _upload(client, pdf_bytes).json()
    r = client.get(f"/jobs/{up['job_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == up["document_id"]
    assert (body["status"], body["stage"], body["progress"]) == ("queued", "queued", 0)


def test_job_not_found(client):
    r = client.get("/jobs/khong-co")
    assert r.status_code == 404 and r.json()["error"]["code"] == "JOB_NOT_FOUND"


# chat
def test_chat_returns_answer_citations_and_thinking(client, make_doc, fake_search):
    doc_id = make_doc("ready")
    r = _chat(client, doc_id)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert body["citations"][0]["heading"] == "Định nghĩa 1.2"
    assert body["citations"][0]["index"] == 1
    steps = [t["step"] for t in body["thinking"]]
    assert steps[:2] == ["analyze", "retrieve"] and "generate" in steps
    with SessionLocal() as db:
        assert db.query(Message).filter_by(document_id=doc_id).count() == 2


def test_chat_stream_sse_events(client, make_doc, fake_search):
    r = _chat(client, make_doc("ready"), stream=True)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    for name in ("thinking", "token", "citations", "done"):
        assert f"event: {name}" in r.text
    assert r.text.index("event: thinking") < r.text.index("event: done")


def test_chat_document_not_ready(client, make_doc):
    r = _chat(client, make_doc("indexing"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_NOT_READY"


def test_chat_document_failed(client, make_doc):
    r = _chat(client, make_doc("failed"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_FAILED"


def test_chat_document_not_found(client):
    assert _chat(client, "khong-co").status_code == 404


def test_chat_empty_question_is_422(client, make_doc):
    r = client.post(f"/documents/{make_doc('ready')}/chat", json={"question": "   "})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# export
def test_export_docx_ok(client, make_doc):
    doc_id = make_doc("ready", docx=True, filename="bai_giang.pdf")
    r = client.get(f"/documents/{doc_id}/export/docx")
    assert r.status_code == 200
    assert "wordprocessingml.document" in r.headers["content-type"]
    assert "bai_giang.docx" in r.headers["content-disposition"]
    assert r.content.startswith(b"PK")


def test_export_not_ready(client, make_doc):
    r = client.get(f"/documents/{make_doc('mineru_parsing')}/export/docx")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_NOT_READY"


def test_export_failed(client, make_doc):
    r = client.get(f"/documents/{make_doc('failed')}/export/docx")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DOCUMENT_FAILED"


def test_export_not_found(client):
    assert client.get("/documents/khong-co/export/docx").status_code == 404