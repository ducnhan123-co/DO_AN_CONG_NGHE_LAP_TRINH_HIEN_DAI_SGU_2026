"""Test end-to-end. Dùng mineru-kit GIẢ LẬP (tests/fake_mineru_kit.py) nhưng mọi thứ còn lại là thật:
SQLite, hàng đợi, Pandoc, code rag_toan (build_docx, columns, chunking...), hệ thống file data/.

Chạy:  cd backend && pytest -q tests
"""
import io
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

CID = {"X-Client-Id": "ctest1"}
CID2 = {"X-Client-Id": "ctest2"}


def make_pdf(path: Path, pages: int, tag: str = "A") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=A4)
    for i in range(1, pages + 1):
        c.setFont("Helvetica", 14)
        c.drawString(72, 780, f"Toan cao cap {tag} - trang {i}")
        c.setFont("Helvetica", 11)
        for k in range(12):
            c.drawString(72, 740 - 18 * k, f"Dong {k}: f(x) = x^{i} + {k}, dao ham f'(x) = {i}x^{i - 1}")
        c.showPage()
    c.save()
    return path.read_bytes()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("bk")
    data = root / "data"
    os.environ.update({
        "DATA_DIR": str(data),
        "MINERU_CMD": f"{sys.executable} {HERE / 'fake_mineru_kit.py'}",
        "MINERU_STAGGER": "0.3", "SEC_PER_PAGE": "0.3", "FAKE_SLEEP": "1",
        "MAIN_SLOTS": "1", "MINERU_WORKERS": "2", "RAG_INDEX": "0", "SERVE_FRONTEND": "0",
    })
    from app.core.config import load_settings
    from app.main import create_app
    app = create_app(load_settings())
    with TestClient(app) as client:
        yield {"client": client, "data": data, "root": root, "app": app}


def wait(client, doc_id, want, timeout=120, headers=CID):
    t0, seen = time.time(), []
    while time.time() - t0 < timeout:
        d = client.get(f"/api/documents/{doc_id}", headers=headers).json()
        if not seen or seen[-1][0] != d["status"]:
            seen.append((d["status"], d["progress"]))
        if d["status"] in want:
            return d, seen
        time.sleep(0.3)
    raise AssertionError(f"quá hạn, trạng thái cuối: {seen}")


def upload(client, name, content, headers=CID):
    return client.post("/api/documents", files=[("files", (name, io.BytesIO(content), "application/pdf"))],
                       headers=headers)


# ----------------------------------------------------------------------------------------------
def test_health(env):
    h = env["client"].get("/api/health").json()
    assert h["engine_found"] and h["pandoc"] and h["mineru_found"], h


def test_full_pipeline_and_layout(env):
    client, data = env["client"], env["data"]
    pdf = make_pdf(env["root"] / "a.pdf", 12, "A")
    r = upload(client, "Giai tich 1.pdf", pdf)
    assert r.status_code == 202, r.text
    item = r.json()["items"][0]
    doc_id = item["id"]
    assert len(doc_id) == 10 and item["num_pages"] == 12 and item["name"] == "Giai tich 1"
    assert "column_mode" not in item

    done, seen = wait(client, doc_id, {"done", "failed"})
    assert done["status"] == "done", done
    assert done["progress"] == 100 and done["docx_available"] and done["docx_size"] > 1000
    assert len(done["shards"]) == 2 and all(s["status"] == "done" for s in done["shards"])
    assert [(s["page_from"], s["page_to"]) for s in done["shards"]] == [(1, 6), (7, 12)]
    assert [s["stage"] for s in done["stages"]] == ["parse", "merge", "prepare", "build", "validate"]
    assert all(s["status"] == "done" for s in done["stages"])
    note = done["stages"][-1]["note"]
    assert note["equations_docx"] > 0 and note["formulas_md"] > 0
    print("trạng thái đã đi qua:", seen, "| validate:", note)

    # --- bố cục data/ đúng yêu cầu
    assert (data / "app.db").is_file()
    assert (data / "input" / f"{doc_id}.pdf").is_file()
    assert (data / "docx_output" / f"{doc_id}.docx").is_file()
    run_dir = data / "documents" / doc_id
    for name in ("logs", "mineru", "mineru_parts", "work.md"):
        assert (run_dir / name).exists(), f"thiếu {name}"
    assert not (run_dir / "input.pdf").exists() and not (run_dir / "output.docx").exists()
    assert not (data / "runs").exists()
    assert (run_dir / "logs" / "pipeline.log").stat().st_size > 0
    assert not list((data / "docx_output").glob(".*building*")), "file tạm Word phải được dọn"

    # --- Word hợp lệ và có Equation thật
    r = client.get(f"/api/documents/{doc_id}/docx")
    assert r.status_code == 200 and "wordprocessingml" in r.headers["content-type"]
    from urllib.parse import unquote
    assert "Giai tich 1.docx" in unquote(r.headers["content-disposition"])
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert b"<m:oMath" in z.read("word/document.xml")

    # --- RAG artifacts chỉ được tạo nếu các module tương ứng có trong rag_toan/src
    if done["rag"]["ok"] is True:
        chunks = json.loads((run_dir / "chunks.json").read_text(encoding="utf-8"))
        assert chunks and all(c["doc_id"] == doc_id and c["source"] == "Giai tich 1.pdf" for c in chunks)
        assert json.loads((run_dir / "validation.json").read_text(encoding="utf-8"))["ok"] is True
    else:
        assert done["rag"]["ok"] is None
        assert not (run_dir / "chunks.json").exists()

    # --- PDF gốc xem được
    r = client.get(f"/api/documents/{doc_id}/pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert "inline" in r.headers["content-disposition"]

    arts = client.get(f"/api/documents/{doc_id}/artifacts", headers=CID).json()["items"]
    assert "work.md" in {a["name"] for a in arts}
    assert "BẮT ĐẦU" in client.get(f"/api/documents/{doc_id}/log", headers=CID).text


def test_stats_and_list(env):
    client = env["client"]
    s = client.get("/api/system/stats").json()
    assert set(s) >= {"running", "main_slots", "aux_mode", "mineru_processes", "queued_tasks", "last_decision"}
    items = client.get("/api/documents?limit=200", headers=CID).json()["items"]
    assert len(items) >= 1
    assert client.get("/api/documents", headers=CID2).json()["items"] == []     # thư viện tách theo client


def test_cache_hit_other_client_rename_and_delete(env):
    client, data = env["client"], env["data"]
    pdf = (env["root"] / "a.pdf").read_bytes()
    r = upload(client, "Ban sao.pdf", pdf, headers=CID2)
    item = r.json()["items"][0]
    assert item["status"] == "done" and item["cache_hit"] is True and item["name"] == "Ban sao"
    doc_id = item["id"]

    # đổi tên chỉ ảnh hưởng thư viện của client đó
    r = client.patch(f"/api/documents/{doc_id}", json={"display_name": "  Tên mới  "}, headers=CID2)
    assert r.status_code == 200 and r.json()["name"] == "Tên mới"
    assert client.get(f"/api/documents/{doc_id}", headers=CID).json()["name"] == "Giai tich 1"
    assert client.patch(f"/api/documents/{doc_id}", json={"display_name": "  "}, headers=CID2).status_code == 400

    # client 2 xóa: dữ liệu vẫn còn vì client 1 đang dùng
    assert client.delete(f"/api/documents/{doc_id}", headers=CID2).status_code == 204
    assert (data / "docx_output" / f"{doc_id}.docx").is_file()
    assert client.get(f"/api/documents/{doc_id}", headers=CID2).status_code == 404
    # client 1 xóa: không còn ai dùng -> xóa sạch trong data/
    assert client.delete(f"/api/documents/{doc_id}", headers=CID).status_code == 204
    assert not (data / "docx_output" / f"{doc_id}.docx").exists()
    assert not (data / "input" / f"{doc_id}.pdf").exists()
    assert not (data / "documents" / doc_id).exists()
    assert client.get(f"/api/documents/{doc_id}/docx").status_code == 404


def test_upload_rejections(env):
    client = env["client"]
    r = upload(client, "ghi-chu.txt", b"hello")
    assert r.status_code == 400 and r.json()["error"]["code"] == "UPLOAD_REJECTED"
    r = upload(client, "gia.pdf", b"khong phai pdf " * 50)
    assert r.status_code == 400 and "PDF" in r.json()["error"]["message"]
    r = upload(client, "rong.pdf", b"")
    assert r.status_code == 400
    # lẫn file tốt + file xấu -> 202 kèm rejected
    pdf = make_pdf(env["root"] / "ok.pdf", 3, "OK")
    r = client.post("/api/documents", headers=CID, files=[
        ("files", ("ok.pdf", io.BytesIO(pdf), "application/pdf")), ("files", ("x.txt", io.BytesIO(b"x"), "text/plain"))])
    assert r.status_code == 202
    j = r.json()
    assert len(j["items"]) == 1 and j["rejected"][0]["filename"] == "x.txt"
    wait(env["client"], j["items"][0]["id"], {"done", "failed"})
    assert client.get("/api/documents/../../etc/passwd", headers=CID).status_code in (404, 400)
    assert client.get("/api/documents/khongco", headers=CID).status_code == 404
    assert client.get("/api/documents/khongco/docx").status_code == 404
    assert client.get("/api/documents", headers={"X-Client-Id": "bad id!"}).status_code == 400


def test_failure_then_retry_resumes(env):
    client, data = env["client"], env["data"]
    flag = env["root"] / "fail_once.flag"
    flag.write_text("x")
    os.environ["FAKE_FAIL_ONCE"] = str(flag)
    try:
        pdf = make_pdf(env["root"] / "f.pdf", 12, "F")
        doc_id = upload(client, "loi.pdf", pdf).json()["items"][0]["id"]
        # phần 1 và 2 chạy song song: một phần nhận cờ lỗi -> chạy lại tuần tự -> thành công
        d, seen = wait(client, doc_id, {"done", "failed"})
    finally:
        os.environ.pop("FAKE_FAIL_ONCE", None)
    assert d["status"] == "done", (d["error"], seen)

    # lỗi cứng -> failed + mã lỗi + nút thử lại
    os.environ["FAKE_FAIL"] = "1"
    try:
        pdf2 = make_pdf(env["root"] / "g.pdf", 6, "G")
        did2 = upload(client, "hong.pdf", pdf2).json()["items"][0]["id"]
        d2, _ = wait(client, did2, {"done", "failed"})
    finally:
        os.environ.pop("FAKE_FAIL", None)
    assert d2["status"] == "failed" and d2["error"]["code"] == "MINERU_FAILED", d2
    assert d2["stages"][0]["status"] == "failed"
    assert d2["docx_available"] is False
    assert client.get(f"/api/documents/{did2}/docx").status_code == 409
    assert client.post(f"/api/documents/{doc_id}/retry", headers=CID).status_code == 409   # đang 'done'

    r = client.post(f"/api/documents/{did2}/retry", headers=CID)
    assert r.status_code == 200
    d3, _ = wait(client, did2, {"done", "failed"})
    assert d3["status"] == "done" and d3["error"] is None
    assert (data / "docx_output" / f"{did2}.docx").is_file()


def test_cancel_running(env):
    client, data = env["client"], env["data"]
    os.environ["FAKE_SLEEP"] = "60"
    try:
        pdf = make_pdf(env["root"] / "c.pdf", 12, "C")
        doc_id = upload(client, "huy.pdf", pdf).json()["items"][0]["id"]
        d, _ = wait(client, doc_id, {"parsing"})
        # đợi tới khi MinerU thật sự chạy
        for _ in range(60):
            if client.get("/api/system/stats").json()["mineru_processes"] > 0:
                break
            time.sleep(0.2)
        assert client.get("/api/system/stats").json()["mineru_processes"] >= 1
        t0 = time.time()
        r = client.post(f"/api/documents/{doc_id}/cancel", headers=CID)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled", r.json()
        assert time.time() - t0 < 15, "hủy phải nhanh, không đợi MinerU chạy hết"
        assert client.get("/api/system/stats").json()["mineru_processes"] == 0
        assert client.post(f"/api/documents/{doc_id}/cancel", headers=CID).status_code == 409
    finally:
        os.environ["FAKE_SLEEP"] = "1"
    # chạy lại sau khi hủy
    client.post(f"/api/documents/{doc_id}/retry", headers=CID)
    d, _ = wait(client, doc_id, {"done", "failed"})
    assert d["status"] == "done"


def test_delete_while_running(env):
    client, data = env["client"], env["data"]
    os.environ["FAKE_SLEEP"] = "60"
    try:
        pdf = make_pdf(env["root"] / "d.pdf", 12, "D")
        doc_id = upload(client, "xoa-khi-chay.pdf", pdf).json()["items"][0]["id"]
        wait(client, doc_id, {"parsing"})
        for _ in range(60):
            if client.get("/api/system/stats").json()["mineru_processes"] > 0:
                break
            time.sleep(0.2)
        assert client.delete(f"/api/documents/{doc_id}", headers=CID).status_code == 204
    finally:
        os.environ["FAKE_SLEEP"] = "1"
    assert not (data / "documents" / doc_id).exists()
    assert not (data / "input" / f"{doc_id}.pdf").exists()
    assert client.get("/api/system/stats").json()["mineru_processes"] == 0


def test_requeue_after_restart(env, tmp_path):
    """Server chết giữa chừng (status 'parsing' còn trong DB) -> khởi động lại thì tự chạy tiếp."""
    from app.core.config import load_settings
    from app.main import create_app
    client, data = env["client"], env["data"]
    pdf = make_pdf(env["root"] / "r.pdf", 6, "R")
    doc_id = upload(client, "restart.pdf", pdf).json()["items"][0]["id"]
    wait(client, doc_id, {"done"})
    env["app"].state.container.repo.update(doc_id, status="building", progress=80)   # giả lập chết giữa chừng
    (data / "docx_output" / f"{doc_id}.docx").unlink()
    app2 = create_app(load_settings())
    with TestClient(app2) as c2:
        d, _ = wait(c2, doc_id, {"done", "failed"})
    assert d["status"] == "done" and (data / "docx_output" / f"{doc_id}.docx").is_file()
    # lần này MinerU được bỏ qua (đã có kết quả ghép)
    assert d["stages"][0]["note"] == {"skipped": True}
