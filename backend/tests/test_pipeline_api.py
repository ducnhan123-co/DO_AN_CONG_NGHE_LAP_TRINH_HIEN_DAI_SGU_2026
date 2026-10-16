"""End-to-end coverage for the sequential PDF-to-DOCX API."""
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings

ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def running_api(**overrides):
    from backend.app.main import app
    settings = get_settings()
    old_values = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        setattr(settings, key, value)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def upload(client, files, client_id="t0000001", force=False):
    multipart = [("files", (name, data, "application/pdf")) for name, data in files]
    url = "/api/documents" + ("?force=true" if force else "")
    return client.post(url, files=multipart, headers={"X-Client-Id": client_id})


def read(path):
    return Path(path).read_bytes()


def wait_for(client, document_id, states=("done", "failed", "cancelled"), timeout=120):
    deadline = time.monotonic() + timeout
    result = {}
    while time.monotonic() < deadline:
        result = client.get(f"/api/documents/{document_id}").json()
        if result["status"] in states:
            return result
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for {states}: {result.get('status')} {result.get('error')}")


def test_single_pdf_end_to_end(pdf_factory):
    from docx import Document as WordDocument

    with running_api() as client:
        response = upload(client, [("e2e46.pdf", read(pdf_factory("e2e46.pdf", 46)))])
        assert response.status_code == 202, response.text
        item = response.json()["items"][0]
        assert item["status"] == "queued" and not item["cache_hit"]
        document = wait_for(client, item["document_id"])
        assert document["status"] == "done", document.get("error")
        assert document["progress"] == 100 and document["docx_available"] and document["num_pages"] == 46
        assert [stage["stage"] for stage in document["stages"]] == ["parse", "prepare", "build", "validate"]
        assert len(document["shards"]) == 2
        assert all(part["status"] == "done" and part["progress"] == 100 for part in document["shards"])

        downloaded = client.get(f"/api/documents/{document['id']}/docx")
        assert downloaded.status_code == 200 and "wordprocessingml" in downloaded.headers["content-type"]
        assert "e2e46.docx" in downloaded.headers["content-disposition"]
        output = get_settings().doc_dir(document["id"])
        assert (output / "output.docx").read_bytes() == downloaded.content
        settings = get_settings()
        input_mirror = settings.input_mirror_path(document["id"], "e2e46.pdf")
        docx_mirror = settings.docx_mirror_path(document["id"], "e2e46.pdf")
        work_md_mirror = settings.work_md_mirror_path(document["id"], "e2e46.pdf")
        run_dir = settings.run_dir(document["id"], "e2e46.pdf")
        assert input_mirror.read_bytes() == (output / "input.pdf").read_bytes()
        assert docx_mirror.read_bytes() == downloaded.content
        assert work_md_mirror.read_bytes() == (output / "work.md").read_bytes()
        assert (run_dir / "mineru" / "document.md").exists()
        assert (run_dir / "chunks.json").exists()
        manifest = json.loads((run_dir / "backend_run.json").read_text(encoding="utf-8"))
        assert manifest["document_id"] == document["id"] and manifest["status"] == "done"
        word = WordDocument(str(output / "output.docx"))
        text = "\n".join(paragraph.text for paragraph in word.paragraphs)
        assert "Trang 1 dong" in text and "Trang 46 dong" in text
        assert (output / "input.pdf").exists()
        assert (output / "mineru" / "document.md").exists()
        assert (output / "work.md").exists()
        assert (output / "structured_data.json").exists()
        assert (output / "chunks.json").exists()
        assert (output / "validation.json").exists()
        assert (output / "logs" / "mineru.log").exists()
        assert (output / "logs" / "post.log").exists()
        assert (Path(get_settings().data_dir) / "app.db").exists()
        assert client.get(f"/api/documents/{document['id']}/pdf").headers["content-type"] == "application/pdf"
        job = client.get(f"/api/jobs/{document['job_id']}").json()
        assert job["status"] == "done" and job["attempt"] == 1


def test_single_document_uses_parallel_rag_toan_mineru(pdf_factory, monkeypatch, tmp_path):
    event_log = tmp_path / "parallel-mineru.log"
    monkeypatch.setenv("FAKE_MINERU_LOG_FILE", str(event_log))
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.2")
    with running_api(mineru_workers=2, mineru_min_pages_per_worker=5, mineru_stagger_s=0) as client:
        item = upload(client, [("parallel10.pdf", read(pdf_factory("parallel10.pdf", 10)))])\
            .json()["items"][0]
        document = wait_for(client, item["document_id"])
        assert document["status"] == "done", document.get("error")
        events = event_log.read_text(encoding="utf-8").splitlines()
        active = maximum = 0
        for line in events:
            active += 1 if line.startswith("start ") else -1
            maximum = max(maximum, active)
        assert maximum == 2
        info = (get_settings().mineru_dir(document["id"]) / "parallel_info.json").read_text(encoding="utf-8")
        assert '"workers": 2' in info


def test_parse_progress_updates_while_mineru_parts_run(pdf_factory, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "1.1")
    with running_api(mineru_workers=2, mineru_min_pages_per_worker=5, mineru_stagger_s=0) as client:
        document_id = upload(client, [("progress10.pdf", read(pdf_factory("progress10.pdf", 10)))])\
            .json()["items"][0]["document_id"]
        deadline = time.monotonic() + 10
        initial = None
        while time.monotonic() < deadline:
            initial = client.get(f"/api/documents/{document_id}").json()
            if initial["status"] == "parsing":
                break
            time.sleep(0.05)
        assert initial and initial["status"] == "parsing"
        time.sleep(1.3)
        current = client.get(f"/api/documents/{document_id}").json()
        assert current["progress"] > initial["progress"]
        assert any(part["status"] == "running" and part["elapsed_s"] > 0 for part in current["shards"])
        manifest_path = get_settings().run_dir(document_id, "progress10.pdf") / "backend_run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "parsing" and manifest["progress"] > initial["progress"]
        assert wait_for(client, document_id)["status"] == "done"
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "done"


def test_jobs_are_processed_sequentially(pdf_factory, monkeypatch, tmp_path):
    event_log = tmp_path / "mineru.log"
    monkeypatch.setenv("FAKE_MINERU_LOG_FILE", str(event_log))
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.03")
    pdfs = [(f"serial-{index}.pdf", read(pdf_factory(f"serial-{index}.pdf", 5, f"Doc{index}")))
            for index in range(3)]
    with running_api() as client:
        items = upload(client, pdfs, client_id="serial001").json()["items"]
        documents = [wait_for(client, item["document_id"]) for item in items]
        assert all(document["status"] == "done" for document in documents)
        assert documents[0]["finished_at"] < documents[1]["finished_at"] < documents[2]["finished_at"]
        lines = event_log.read_text(encoding="utf-8").splitlines()
        active = maximum = 0
        for line in lines:
            if not line.strip():
                continue
            event = line.split()[0]
            active += 1 if event == "start" else -1
            maximum = max(maximum, active)
        assert maximum == 1
        assert client.get("/api/system/stats").json()["main_slots"] == 1


def test_sha256_cache_and_force(pdf_factory):
    pdf = read(pdf_factory("cache30.pdf", 30))
    with running_api() as client:
        original = wait_for(client, upload(client, [("first.pdf", pdf)]).json()["items"][0]["document_id"])
        cached_item = upload(client, [("cached.pdf", pdf)]).json()["items"][0]
        assert cached_item["cache_hit"] and cached_item["status"] == "done"
        cached = client.get(f"/api/documents/{cached_item['document_id']}").json()
        assert cached["cache_hit"] and cached["docx_available"] and cached["progress"] == 100
        assert [stage["stage"] for stage in cached["stages"]] == ["cache"]
        assert client.get(f"/api/documents/{cached_item['document_id']}/docx").content == \
            client.get(f"/api/documents/{original['id']}/docx").content
        forced = upload(client, [("forced.pdf", pdf)], force=True).json()["items"][0]
        assert not forced["cache_hit"]
        assert wait_for(client, forced["document_id"])["status"] == "done"


def test_cancel_running_job(pdf_factory, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.5")
    with running_api() as client:
        document_id = upload(client, [("cancel.pdf", read(pdf_factory("cancel.pdf", 20)))])\
            .json()["items"][0]["document_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/documents/{document_id}").json()
            if current["status"] == "parsing":
                break
            time.sleep(0.05)
        assert current["status"] == "parsing"
        response = client.post(f"/api/documents/{document_id}/cancel")
        assert response.status_code == 200
        cancelled = wait_for(client, document_id, states=("cancelled",))
        assert cancelled["error"]["code"] == "CANCELLED"
        assert client.post(f"/api/documents/{document_id}/cancel").status_code == 409


def test_mineru_timeout_and_missing_command(pdf_factory, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "5")
    with running_api(mineru_timeout_min_s=1, mineru_timeout_per_page_s=0) as client:
        item = upload(client, [("slow.pdf", read(pdf_factory("slow.pdf", 2)))])\
            .json()["items"][0]
        failed = wait_for(client, item["document_id"], timeout=30)
        assert failed["status"] == "failed" and failed["error"]["code"] == "MINERU_TIMEOUT"
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.01")
    with running_api(mineru_cmd="no-such-mineru-command"):
        from backend.app.main import app
        with TestClient(app) as client:
            item = upload(client, [("missing.pdf", read(pdf_factory("missing.pdf", 2)))])\
                .json()["items"][0]
            failed = wait_for(client, item["document_id"])
            assert failed["status"] == "failed" and failed["error"]["code"] == "MINERU_NOT_FOUND"


def test_upload_validation_errors(pdf_factory):
    valid_pdf = read(pdf_factory("good3.pdf", 3))
    with running_api() as client:
        response = client.post("/api/documents", files=[("files", ("a.txt", b"hello", "text/plain"))])
        assert response.status_code == 415 and response.json()["error"]["code"] == "INVALID_FILE_TYPE"
        response = client.post("/api/documents", files=[("files", ("a.pdf", b"%PDF-1.4\ninvalid", "application/pdf"))])
        assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PDF"
        response = client.post("/api/documents", files=[
            ("files", ("good.pdf", valid_pdf, "application/pdf")),
            ("files", ("bad.txt", b"bad", "text/plain")),
        ])
        assert response.status_code == 202
        result = response.json()
        assert len(result["items"]) == 1 and result["rejected"][0]["code"] == "INVALID_FILE_TYPE"


def test_list_rename_and_client_isolation(pdf_factory):
    with running_api() as client:
        a = upload(client, [("alpha.pdf", read(pdf_factory("alpha.pdf", 2, "A")))],
                   client_id="user000A").json()["items"][0]["document_id"]
        b = upload(client, [("beta.pdf", read(pdf_factory("beta.pdf", 2, "B")))],
                   client_id="user000B").json()["items"][0]["document_id"]
        wait_for(client, a)
        wait_for(client, b)
        listing = client.get("/api/documents", headers={"X-Client-Id": "user000A"}).json()
        assert [item["id"] for item in listing["items"]] == [a]
        renamed = client.patch(f"/api/documents/{a}", json={"display_name": "Giải tích 1"}).json()
        assert renamed["name"] == "Giải tích 1"
        settings = get_settings()
        renamed_docx = settings.docx_mirror_path(a, "Giải tích 1")
        original_docx = settings.docx_mirror_path(a, "alpha.pdf")
        assert renamed_docx.exists() and not original_docx.exists()
        run_manifest = json.loads(
            (settings.run_dir(a, "alpha.pdf") / "backend_run.json").read_text(encoding="utf-8"))
        assert run_manifest["display_name"] == "Giải tích 1"
        assert client.get("/api/documents?status=done", headers={"X-Client-Id": "user000A"}).json()["total"] == 1
        deleted = client.delete(f"/api/documents/{a}")
        assert deleted.status_code == 204
        assert not settings.input_mirror_path(a, "alpha.pdf").exists()
        assert not renamed_docx.exists()
        assert not settings.run_dir(a, "alpha.pdf").exists()
        assert not settings.doc_dir(a).exists()


def test_health_stats_and_openapi():
    with running_api() as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok" and health["mineru_found"] is True
        stats = client.get("/api/system/stats").json()
        assert stats["main_slots"] == 1 and stats["running"] == [] and "documents" in stats
        spec = client.get("/openapi.json").json()
        paths = spec["paths"]
        assert "/api/documents" in paths
        assert "/api/documents/{document_id}/docx" in paths
        assert "/api/jobs/{job_id}/events" in paths


def test_cli_runs_pipeline_and_reuses_cache(pdf_factory, tmp_path):
    pdf = pdf_factory("cli30.pdf", 3)
    data = tmp_path / "cli-data"
    env = {**os.environ, "DATA_DIR": str(data)}
    result = subprocess.run([sys.executable, "-m", "backend.app.cli", str(pdf)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-> done" in result.stdout and "DOCX:" in result.stdout
    docx = Path(result.stdout.split("DOCX:")[1].splitlines()[0].strip())
    assert docx.exists() and str(docx).startswith(str(data))
    again = subprocess.run([sys.executable, "-m", "backend.app.cli", str(pdf)], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=90)
    assert again.returncode == 0 and "dùng lại DOCX cũ" in again.stdout


def test_restart_recovers_unfinished_job(pdf_factory, monkeypatch):
    from backend.app.models.pipeline import Pipeline, get_pipeline, set_pipeline

    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.1")
    with running_api() as client:
        document_id = upload(client, [("recover.pdf", read(pdf_factory("recover.pdf", 8)))])\
            .json()["items"][0]["document_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = client.get(f"/api/documents/{document_id}").json()
            if current["status"] == "parsing":
                break
            time.sleep(0.05)
        assert current["status"] == "parsing"
        get_pipeline().stop()
        assert client.get(f"/api/documents/{document_id}").json()["status"] in ("parsing", "queued")
        pipeline = Pipeline(get_settings())
        set_pipeline(pipeline)
        pipeline.start()
        try:
            assert wait_for(client, document_id, timeout=60)["status"] == "done"
        finally:
            pipeline.stop()
            set_pipeline(None)


def test_engine_comes_from_sibling_project_directory():
    from backend.app.engine import rag_toan

    info = rag_toan.engine_info()
    assert info["found"] and Path(info["dir"]).parent == ROOT and Path(info["dir"]).name == "rag_toan"
    module = rag_toan._load()
    assert str(Path(module.__file__).resolve()).startswith(info["dir"])
    assert module.__name__ == "src.build_docx"
