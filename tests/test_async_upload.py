"""Upload phải trả về ngay (PDF mở được liền); đọc chữ/embedding chạy nền."""
import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    import importlib
    import backend.app.main as main
    main = importlib.reload(main)
    events = []

    def fake_index(doc_id, name, path):  # thay phần nặng (OCR + embedding)
        events.append("indexed")
        main.store._index(doc_id, name, path, ["Nội dung trang một đủ dài để thành chunk. " * 3], False, "pypdf")

    monkeypatch.setattr(main.store, "index_upload", fake_index)
    monkeypatch.setattr(main.store, "build_docx_fast", lambda doc_id: None)
    monkeypatch.setattr(main.store, "upgrade_mineru", lambda doc_id: None)
    import llm.matchpdf as mp
    monkeypatch.setattr(mp, "_embed", lambda texts: [[1.0] for _ in texts])
    return main, events, TestClient(main.app)


def _pdf() -> bytes:
    w, buf = PdfWriter(), io.BytesIO()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    return buf.getvalue()


def test_upload_returns_before_indexing(api):
    main, events, client = api
    r = client.post("/api/upload", files={"f": ("a.pdf", _pdf(), "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "indexing"      # phản hồi dựng TRƯỚC khi index chạy
    assert body["num_pages"] == 1
    assert "num_chunks" not in body


def test_ready_after_background_and_chat_blocked_while_pending(api):
    main, events, client = api
    doc_id = client.post("/api/upload", files={"f": ("a.pdf", _pdf(), "application/pdf")}).json()["doc_id"]
    # TestClient chạy background trước khi trả về -> đã xong
    assert events == ["indexed"]
    info = client.get(f"/api/doc/{doc_id}").json()
    assert info["status"] == "ready" and info["num_chunks"] >= 1

    # tài liệu đang xử lý: PDF gốc xem được ngay, chat bị chặn rõ ràng
    main.store.pending["aaaaaaaaaa"] = {"name": "b.pdf", "file": main.DATA_DIR / f"{doc_id}.pdf",
                                        "num_pages": 1, "status": "indexing"}
    assert client.get("/api/doc/aaaaaaaaaa").json()["status"] == "indexing"
    assert client.get("/api/file/aaaaaaaaaa").status_code == 200
    r = client.post("/api/chat_stream", json={"doc_id": "aaaaaaaaaa", "question": "hi"})
    assert r.status_code == 425
