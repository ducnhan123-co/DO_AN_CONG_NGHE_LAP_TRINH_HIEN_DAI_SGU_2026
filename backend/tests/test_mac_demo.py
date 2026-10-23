"""Regression for no-model keyword search and same-origin Mac tunnel."""
import json

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.models.lexical_search import search_chunks


def test_bm25_vietnamese_formula_and_page(tmp_path):
    path = tmp_path / "chunks.json"
    chunks = [
        {"chunk_id": 0, "doc_id": "abc", "page": 1, "pages": [1],
         "section": "Giới thiệu", "source": "de.pdf",
         "text": "Trái đất quay quanh mặt trời."},
        {"chunk_id": 1, "doc_id": "abc", "page": 3, "pages": [3],
         "section": "Tích phân", "source": "de.pdf",
         "formula_latex": [r"\int_0^1 x dx"],
         "text": r"Công thức tích phân: $$\int_0^1 x dx$$"},
    ]
    path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    hits = search_chunks(path, "tích phân công thức", 2)
    assert hits[0]["page"] == 3
    assert r"\int_0^1" in hits[0]["text"]
    assert hits[0]["pages"] == [3]
    assert hits[0]["score"] > 0
    assert search_chunks(path, "zzzzunmatched", 5) == []


def test_mac_static_uses_runtime_origin(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "demo_auth_user", "")
    monkeypatch.setattr(settings, "demo_auth_password", "")
    with TestClient(create_app()) as c:
        assert c.get("/").status_code == 200
        assert c.get("/reader.html").status_code == 200
        assert c.get("/lib.js").status_code == 200
        config = c.get("/config.js")
        assert config.status_code == 200
        assert "MATCHPDF_FORCE_ORIGIN = true" in config.text
        assert "location.origin" in config.text
        assert "no-store" in config.headers["cache-control"]
        assert c.get("/api/health").json()["search_backend"] == "keyword_bm25"


def test_mac_basic_auth_protects_every_route(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "demo_auth_user", "demo")
    monkeypatch.setattr(settings, "demo_auth_password", "StrongTestOnly1")
    with TestClient(create_app()) as c:
        for route in ("/", "/config.js", "/docs", "/api/health"):
            assert c.get(route).status_code == 401
            assert c.get(route, auth=("demo", "invalid")).status_code == 401
            assert c.get(route, auth=("demo", "StrongTestOnly1")).status_code == 200


def test_chat_extracts_cited_text_without_llm(client, make_doc):
    doc_id = make_doc(status="ready")
    chunks = [{"chunk_id": 0, "doc_id": doc_id, "source": "math.pdf",
               "section": "Đạo hàm", "page": 2, "pages": [2],
               "text": r"Đạo hàm của $x^2$ là $2x$. Công thức cơ bản."}]
    path = get_settings().doc_dir(doc_id) / "chunks.json"
    path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    res = client.post(f"/api/documents/{doc_id}/chat", json={
        "question": "đạo hàm", "top_k": 3,
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["citations"][0]["page"] == 2
    assert "$2x$" in data["answer"]
