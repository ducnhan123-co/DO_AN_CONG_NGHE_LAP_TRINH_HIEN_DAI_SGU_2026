import importlib
import os
import tempfile

from fastapi.testclient import TestClient

os.environ["PDF2DOCX_STORAGE"] = tempfile.mkdtemp()
main = importlib.import_module("backend.app.main")
client = TestClient(main.app)


def test_rejects_non_pdf():
    r = client.post("/api/jobs", files={"file": ("a.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400


def test_rejects_bad_tier():
    r = client.post("/api/jobs", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")}, data={"tier": "x"})
    assert r.status_code == 400


def test_unknown_or_traversal_id_is_404():
    assert client.get("/api/jobs/000000000000").status_code == 404
    assert client.get("/api/jobs/..%2f..%2fetc").status_code == 404


def test_frontend_served():
    assert "PDF toán" in client.get("/").text
