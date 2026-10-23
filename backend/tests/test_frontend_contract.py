"""FE <-> BE smoke contract; no MinerU, GPU, or network required."""
from io import BytesIO

from pypdf import PdfWriter

from backend.app.core.config import get_settings


def _pdf_bytes():
    out = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(out)
    return out.getvalue()


def test_matchpdf_upload_read_library_contract(client):
    response = client.post(
        "/api/upload", files={"f": ("math.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 200, response.text
    uploaded = response.json()
    doc_id = uploaded["doc_id"]
    assert len(doc_id) == 10
    assert uploaded["status"] == "indexing"
    assert uploaded["parser"] == "mineru_running"
    assert uploaded["num_pages"] == 1
    assert uploaded["file_url"] == f"/api/file/{doc_id}"
    assert uploaded["docx"] == "building"

    info = client.get(f"/api/doc/{doc_id}")
    assert info.status_code == 200
    assert info.json()["num_chunks"] == 0
    assert info.json()["status"] == "indexing"

    assert client.get(f"/api/file/{doc_id}").content.startswith(b"%PDF")
    assert client.get(f"/api/docx/{doc_id}").status_code == 425
    assert client.post("/api/chat_stream", json={
        "doc_id": doc_id, "question": "Giải thích công thức", "history": [],
    }).status_code == 425

    headers = {"X-Client-Id": "c_frontend_smoketest_42"}
    saved = client.put(f"/api/doc/{doc_id}", json={
        "name": uploaded["name"],
        "num_pages": uploaded["num_pages"],
        "parser": uploaded["parser"],
    }, headers=headers)
    assert saved.status_code == 200, saved.text
    recents = client.get("/api/doc", headers=headers)
    assert recents.status_code == 200
    assert any(row["doc_id"] == doc_id for row in recents.json())
    assert client.get(f"/api/doc/{doc_id}/file", headers=headers).content.startswith(b"%PDF")
    assert client.get("/api/lib/health").json()["ok"] is True


def test_frontend_docx_ready_contract(client, make_doc):
    doc_id = make_doc(status="ready", docx=True)
    info = client.get(f"/api/doc/{doc_id}")
    assert info.status_code == 200
    data = info.json()
    assert data["status"] == "ready"
    assert data["docx"] == "ready"
    assert data["docx_url"] == f"/api/docx/{doc_id}"
    assert client.get(data["docx_url"]).status_code == 200


def test_rag_failed_but_word_remains_downloadable(client, make_doc):
    from backend.app.models.database import DocumentStatus
    from backend.app.models import pipeline_model

    doc_id = make_doc(status=DocumentStatus.failed.value, docx=True)
    doc_dir = get_settings().doc_dir(doc_id)
    (doc_dir / "chunks.json").write_text("[]", encoding="utf-8")
    resp = client.get(f"/api/doc/{doc_id}")
    assert resp.status_code == 200
    info = resp.json()
    assert info["status"] == "failed"
    assert info["embed"] == "failed"
    assert info["parser"] == "mineru"
    assert info["chunks_available"] is True
    assert info["docx"] == "ready"
    assert info["docx_url"] == f"/api/docx/{doc_id}"
    assert client.get(info["docx_url"]).status_code == 200


def test_docx_is_published_atomically_after_validation(tmp_path, monkeypatch):
    from zipfile import ZipFile
    from llm.src import build_docx
    from backend.app.models.pipeline_model import _build_docx_background

    output = tmp_path / "result.docx"
    flag = tmp_path / "docx_failed.flag"

    def write_valid(_, path, __):
        with ZipFile(path, "w") as z:
            z.writestr("word/document.xml",
                       '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')

    monkeypatch.setattr(build_docx, "md_to_docx", write_valid)
    _build_docx_background("testid", tmp_path / "work.md", output, tmp_path, flag)
    assert output.is_file()
    assert not flag.exists()
    assert not (tmp_path / ".result.building.docx").exists()


def test_invalid_docx_never_published(tmp_path, monkeypatch):
    from llm.src import build_docx
    from backend.app.models.pipeline_model import _build_docx_background

    output = tmp_path / "result.docx"
    flag = tmp_path / "docx_failed.flag"
    monkeypatch.setattr(build_docx, "md_to_docx",
                        lambda _md, target, _imgs: target.write_bytes(b"not a docx"))
    _build_docx_background("testid", tmp_path / "work.md", output, tmp_path, flag)
    assert not output.exists()
    assert flag.exists()
    assert not (tmp_path / ".result.building.docx").exists()


def test_api_only_mode_rejects_heavy_work_without_crashing(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_pipeline_enabled", False)
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ai_pipeline_enabled"] is False
    for endpoint, field in (("/api/upload", "f"), ("/api/documents", "file")):
        response = client.post(
            endpoint, files={field: ("math.pdf", _pdf_bytes(), "application/pdf")})
        assert response.status_code == 503, (endpoint, response.text)
        assert "AI" in response.text or "MinerU" in response.text


def test_api_only_mode_blocks_retry(client, make_doc, monkeypatch):
    from backend.app.models.database import DocumentStatus

    doc_id = make_doc(status=DocumentStatus.failed.value)
    monkeypatch.setattr(get_settings(), "ai_pipeline_enabled", False)
    response = client.post(f"/api/documents/{doc_id}/retry")
    assert response.status_code == 503


def test_v3_style_artifacts_available_for_chunks_and_validation(client, make_doc):
    doc_id = make_doc()
    folder = get_settings().doc_dir(doc_id)
    (folder / "chunks.json").write_text('[{"text":"\\\\frac{a}{b}"}]', encoding="utf-8")
    (folder / "validation.json").write_text('{"ok":true}', encoding="utf-8")
    summary = client.get(f"/api/documents/{doc_id}/artifacts")
    assert summary.status_code == 200
    assert {e["name"] for e in summary.json()["items"]} == {
        "chunks.json", "validation.json"}
    chunks = client.get(f"/api/documents/{doc_id}/artifacts/chunks.json")
    assert chunks.status_code == 200
    assert chunks.json()[0]["text"] == r"\frac{a}{b}"
    assert client.get(f"/api/documents/{doc_id}/artifacts/secrets.env").status_code == 404
