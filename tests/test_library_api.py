"""Library API (SQLite): tài liệu, phiên chat, công thức, lịch sử DOCX. Không đụng BE."""
import json

import pytest
from fastapi.testclient import TestClient

A = {"X-Client-Id": "client-aaaaaaaa"}
B = {"X-Client-Id": "client-bbbbbbbb"}

CONTENT_LIST = [
    {"type": "text", "text": "Chương 1 Đạo hàm", "text_level": 1, "page_idx": 0},
    {"type": "text", "text": "Đạo hàm của hàm số tại một điểm được định nghĩa như sau.", "page_idx": 0},
    {"type": "equation", "text": "$$ f'(x)=\\lim_{h\\to 0}\\frac{f(x+h)-f(x)}{h} $$", "page_idx": 0},
    {"type": "text", "text": "Ví dụ với hàm bậc hai.", "page_idx": 1},
    {"type": "equation", "text": "\\int_0^1 x^2 dx = \\frac{1}{3}", "page_idx": 1},
    {"type": "page_number", "text": "2", "page_idx": 1},
]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import library_api.db as db
    import library_api.sources as sources
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "library.db")
    monkeypatch.setattr(db, "LIBRARY_DIR", tmp_path / "lib")
    monkeypatch.setattr(sources, "DATA_DIR", tmp_path / "docs")
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(sources, "delete_pdf", lambda doc_id: "unsupported")
    import library_api.main as main
    return TestClient(main.app), tmp_path / "docs"


def reg(client, doc_id="doc1", headers=A, **kw):
    body = {"name": "bai-giang.pdf", "num_pages": 10, "parser": "pypdf", **kw}
    return client.put(f"/api/lib/docs/{doc_id}", json=body, headers=headers)


def test_client_id_required_and_validated(env):
    client, _ = env
    assert client.get("/api/lib/docs").status_code == 400
    assert client.get("/api/lib/docs", headers={"X-Client-Id": "a b!"}).status_code == 400
    assert client.get("/api/lib/docs", headers=A).json() == []


def test_documents_crud_and_isolation(env):
    client, _ = env
    assert reg(client).status_code == 200
    assert [d["doc_id"] for d in client.get("/api/lib/docs", headers=A).json()] == ["doc1"]
    assert client.get("/api/lib/docs", headers=B).json() == []          # tách theo client
    assert client.patch("/api/lib/docs/doc1", json={"display_name": "Toán A3"}, headers=B).status_code == 404
    assert client.patch("/api/lib/docs/doc1", json={"display_name": "Toán A3"}, headers=A).status_code == 200
    d = client.get("/api/lib/docs", headers=A).json()[0]
    assert d["display_name"] == "Toán A3" and d["name"] == "bai-giang.pdf"
    assert client.put("/api/lib/docs/../etc", json={"name": "x"}, headers=A).status_code in (404, 405, 422)


def test_sessions_messages_roundtrip_and_cascade(env):
    client, _ = env
    reg(client)
    sid = client.post("/api/lib/docs/doc1/sessions", json={"title": "Phiên 1"}, headers=A).json()["id"]
    r = client.post(f"/api/lib/sessions/{sid}/messages", headers=A, json={"messages": [
        {"role": "user", "content": "Đạo hàm là gì?"},
        {"role": "assistant", "content": "Là giới hạn [3]", "citations": [3], "model": "qwen3:8b", "elapsed_s": 1.5}]})
    assert r.status_code == 200
    msgs = client.get(f"/api/lib/sessions/{sid}/messages", headers=A).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[1]["citations"] == [3]
    assert client.get(f"/api/lib/sessions/{sid}/messages", headers=B).status_code == 404
    listed = client.get("/api/lib/docs/doc1/sessions", headers=A).json()
    assert listed[0]["message_count"] == 2
    assert client.delete(f"/api/lib/sessions/{sid}", headers=A).status_code == 200
    assert client.get("/api/lib/docs/doc1/sessions", headers=A).json() == []
    assert client.get(f"/api/lib/sessions/{sid}/messages", headers=A).status_code == 404


def test_message_validation(env):
    client, _ = env
    reg(client)
    sid = client.post("/api/lib/docs/doc1/sessions", json={}, headers=A).json()["id"]
    bad = client.post(f"/api/lib/sessions/{sid}/messages", headers=A,
                      json={"messages": [{"role": "system", "content": "x"}]})
    assert bad.status_code == 422
    huge = client.post(f"/api/lib/sessions/{sid}/messages", headers=A,
                       json={"messages": [{"role": "user", "content": "x" * 20001}]})
    assert huge.status_code == 422


def test_ingest_formulas_idempotent_and_context(env):
    client, docs = env
    reg(client)
    out = docs / "doc1_mineru" / "auto"
    out.mkdir(parents=True)
    (out / "x_content_list.json").write_text(json.dumps(CONTENT_LIST), encoding="utf-8")
    assert client.post("/api/lib/docs/doc1/ingest", headers=A).json()["formulas"] == 2
    assert client.post("/api/lib/docs/doc1/ingest", headers=A).json()["formulas"] == 2   # ghi đè, không nhân đôi

    sid = client.post("/api/lib/docs/doc1/sessions", json={}, headers=A).json()["id"]
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"tin {i}"} for i in range(4)]
    client.post(f"/api/lib/sessions/{sid}/messages", headers=A, json={"messages": msgs})
    client.post(f"/api/lib/sessions/{sid}/messages", headers=A,
                json={"messages": [{"role": "user", "content": "tin 4"}, {"role": "assistant", "content": "tin 5"}]})

    ctx = client.get("/api/lib/docs/doc1/context", headers=A,
                     params={"q": "định nghĩa đạo hàm là gì?", "session_id": sid}).json()
    assert [m["content"] for m in ctx["recent"]] == ["tin 1", "tin 2", "tin 3", "tin 4", "tin 5"]
    assert len(ctx["formulas"]) >= 1
    top = ctx["formulas"][0]
    assert "lim" in top["latex"] and top["page"] == 1 and top["section"] == "Chương 1 Đạo hàm"
    assert "Đạo hàm" in top["ctx_before"] and top["ctx_after"].startswith("Ví dụ")

    # token đặc biệt / rỗng không làm FTS5 lỗi
    for q in ['"', "a OR (b", "\\frac{1}{2}", "", "*"]:
        assert client.get("/api/lib/docs/doc1/context", headers=A, params={"q": q}).status_code == 200
    # client khác không thấy
    assert client.get("/api/lib/docs/doc1/context", headers=B, params={"q": "đạo hàm"}).status_code == 404


def test_ingest_without_content_list_returns_zero(env):
    client, _ = env
    reg(client)
    r = client.post("/api/lib/docs/doc1/ingest", headers=A)
    assert r.status_code == 200 and r.json()["formulas"] == 0


def test_docx_snapshot_dedup_versions_and_download(env):
    client, docs = env
    reg(client)
    assert client.post("/api/lib/docs/doc1/docx/snapshot", json={"source": "fast"}, headers=A).status_code == 404
    (docs / "doc1.docx").write_bytes(b"PK-fast-version")
    first = client.post("/api/lib/docs/doc1/docx/snapshot", json={"source": "fast"}, headers=A).json()
    again = client.post("/api/lib/docs/doc1/docx/snapshot", json={"source": "fast"}, headers=A).json()
    assert first["version"] == 1 and first["created"] is True
    assert again["version"] == 1 and again["created"] is False          # bấm lại -> lấy bản cũ
    (docs / "doc1.docx").write_bytes(b"PK-mineru-version-longer")
    new = client.post("/api/lib/docs/doc1/docx/snapshot", json={"source": "mineru"}, headers=A).json()
    assert new["version"] == 2 and new["created"] is True

    versions = client.get("/api/lib/docs/doc1/docx", headers=A).json()
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["source"] == "mineru"
    old = client.get(f"/api/lib/docx/{versions[1]['id']}/download", headers=A)
    assert old.status_code == 200 and old.content == b"PK-fast-version"   # bản cũ vẫn tải được dù file BE đã đổi
    assert client.get(f"/api/lib/docx/{versions[1]['id']}/download", headers=B).status_code == 404
    kinds = [a["kind"] for a in client.get("/api/lib/docs/doc1/activity", headers=A).json()]
    assert kinds.count("docx") == 2


def test_delete_document_cascades_and_blocks_reregister(env, monkeypatch):
    client, docs = env
    import library_api.sources as sources
    monkeypatch.setattr(sources, "delete_pdf", lambda doc_id: "deleted")
    reg(client)
    sid = client.post("/api/lib/docs/doc1/sessions", json={}, headers=A).json()["id"]
    client.post(f"/api/lib/sessions/{sid}/messages", headers=A, json={"messages": [{"role": "user", "content": "hi"}]})
    (docs / "doc1.docx").write_bytes(b"PK1")
    client.post("/api/lib/docs/doc1/docx/snapshot", json={"source": "fast"}, headers=A)
    assert client.delete("/api/lib/docs/doc1", headers=B).status_code == 404
    r = client.delete("/api/lib/docs/doc1", headers=A)
    assert r.status_code == 200 and r.json()["pdf"] == "deleted"
    assert client.get("/api/lib/docs", headers=A).json() == []
    assert client.get(f"/api/lib/sessions/{sid}/messages", headers=A).status_code == 404
    assert client.get("/api/lib/docs/doc1/docx", headers=A).status_code == 404
    assert reg(client).status_code == 410
    import library_api.db as db
    assert not list((db.LIBRARY_DIR).rglob("*.docx"))                      # bản chụp đã dọn
