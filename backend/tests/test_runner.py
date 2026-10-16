import os
import threading
import time

import pytest

from backend.app.engine.mineru_runner import MinerUCancelled, MinerUError, kit_command, run_kit

CMD = os.environ["MINERU_CMD"]


def _run(pdf, out, tmp_path, timeout=60, cancel=None, fmt="zip", **kw):
    return run_kit(pdf, out, cmd=CMD, tier="standard", ocr_mode="auto", timeout_s=timeout, fmt=fmt,
                   log_path=tmp_path / "logs" / "k.log", cancel=cancel or threading.Event(), **kw)


def test_run_ok(pdf_factory, tmp_path):
    pdf = pdf_factory("r3.pdf", 3)
    res = _run(pdf, tmp_path / "out", tmp_path)
    assert (tmp_path / "out" / "markdown.md").exists()
    assert len(list((tmp_path / "out" / "images").iterdir())) == 3
    assert not (tmp_path / "out" / "_kit").exists()                           # thư mục tạm đã dọn
    assert res.returncode == 0 and res.duration_s > 0
    assert "parse" in (tmp_path / "logs" / "k.log").read_text(encoding="utf-8")


def test_nonzero_exit_with_zip_is_success(pdf_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_EXIT", "3")                                # mineru-kit thật hay thoát mã lỗi do telemetry
    res = _run(pdf_factory("r2.pdf", 2), tmp_path / "out", tmp_path)
    assert res.returncode == 3 and (tmp_path / "out" / "markdown.md").exists()


def test_failure_without_zip(pdf_factory, tmp_path, monkeypatch):
    ff = tmp_path / "fail.txt"
    ff.write_text("1")
    monkeypatch.setenv("FAKE_MINERU_FAIL_FILE", str(ff))
    with pytest.raises(MinerUError) as e:
        _run(pdf_factory("r1.pdf", 2), tmp_path / "out", tmp_path)
    assert e.value.code == "MINERU_FAILED" and "lỗi giả lập" in e.value.message
    _run(pdf_factory("r1.pdf", 2), tmp_path / "out", tmp_path)                 # lần sau thành công


def test_timeout(pdf_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "5")
    t0 = time.time()
    with pytest.raises(MinerUError) as e:
        _run(pdf_factory("r4.pdf", 4), tmp_path / "out", tmp_path, timeout=1.5)
    assert e.value.code == "MINERU_TIMEOUT" and time.time() - t0 < 10


def test_cancel_kills_process(pdf_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "5")
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    t0 = time.time()
    with pytest.raises(MinerUCancelled):
        _run(pdf_factory("r5.pdf", 4), tmp_path / "out", tmp_path, cancel=cancel)
    assert time.time() - t0 < 10


def test_samples_ram_and_calls_on_start(pdf_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_DELAY_PER_PAGE", "0.6")
    seen, pids = [], []
    res = _run(pdf_factory("r6.pdf", 4), tmp_path / "out", tmp_path, on_sample=seen.append, on_start=lambda p: pids.append(p.pid))
    assert pids and seen and res.peak_ram_gb > 0


def test_missing_command(pdf_factory, tmp_path):
    with pytest.raises(MinerUError) as e:
        run_kit(pdf_factory("r7.pdf", 1), tmp_path / "o", cmd="khong-co-lenh-nay-12345", tier="standard", ocr_mode="auto",
                timeout_s=5, log_path=tmp_path / "l.log", cancel=threading.Event())
    assert e.value.code == "MINERU_NOT_FOUND"


def test_unsafe_zip_rejected(tmp_path):
    import zipfile
    from backend.app.engine.mineru_runner import _safe_extract
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../evil.txt", "x")
    with pytest.raises(MinerUError):
        _safe_extract(z, tmp_path / "dest")


def test_kit_command_split():
    assert kit_command('"/usr/bin/python3" "/tmp/a b/fake.py"')[0] == "/usr/bin/python3"
    assert kit_command('"/usr/bin/python3" "/tmp/a b/fake.py"')[1] == "/tmp/a b/fake.py"


# ---------------------------------------------------------------- chế độ markdown (cách rag_toan đang gọi mineru-kit)
def test_markdown_mode_single_md_with_base64_images(pdf_factory, tmp_path):
    res = _run(pdf_factory("md3.pdf", 3), tmp_path / "out", tmp_path, fmt="markdown")
    mds = list((tmp_path / "out").rglob("*.md"))
    assert [p.name for p in mds] == ["md3.md"]                                # đúng <tên pdf>.md như parallel_mineru.py mong đợi
    assert mds[0].read_text(encoding="utf-8").count("data:image/jpeg;base64,") == 3
    assert not (tmp_path / "out" / "images").exists() and not (tmp_path / "out" / "_kit").exists()
    log = (tmp_path / "logs" / "k.log").read_text(encoding="utf-8")
    assert "-f zip" not in log and "--tier standard" in log and "parse" in log and res.returncode == 0


def test_markdown_mode_nonzero_exit_with_md_is_success(pdf_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MINERU_EXIT", "3")
    res = _run(pdf_factory("md2.pdf", 2), tmp_path / "out", tmp_path, fmt="markdown")
    assert res.returncode == 3 and list((tmp_path / "out").rglob("*.md"))


def test_markdown_mode_failure_without_md(pdf_factory, tmp_path, monkeypatch):
    ff = tmp_path / "fail.txt"
    ff.write_text("1")
    monkeypatch.setenv("FAKE_MINERU_FAIL_FILE", str(ff))
    with pytest.raises(MinerUError) as e:
        _run(pdf_factory("md1.pdf", 2), tmp_path / "out", tmp_path, fmt="markdown")
    assert e.value.code == "MINERU_FAILED" and "lỗi giả lập" in e.value.message
