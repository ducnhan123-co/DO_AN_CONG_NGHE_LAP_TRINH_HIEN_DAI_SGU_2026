import shutil
from pathlib import Path

import pytest

from llm.src.mineru_pool import merge_parts, split_ranges
from llm.src.run_mineru import fix_vi_ocr

PDF = Path(__file__).resolve().parents[1] / "llm" / "input" / "1.pdf"


def test_split_ranges_cover_all_pages_without_gaps():
    for total in (1, 2, 7, 100, 203):
        for n in (1, 2, 3, 5):
            r = split_ranges(total, n)
            assert r[0][0] == 0 and r[-1][1] == total - 1
            assert all(b[0] == a[1] + 1 for a, b in zip(r, r[1:]))
            assert len(r) == min(n, total)


def test_merge_parts_offsets_page_idx_and_keeps_order():
    a = {"md": "A1\n", "content_list": [{"page_idx": 0, "type": "text"}, {"page_idx": 2, "type": "text"}], "images": {"x.jpg": b"1"}}
    b = {"md": "B1", "content_list": [{"page_idx": 0, "type": "text"}], "images": {"y.jpg": b"2"}}
    md, items, imgs = merge_parts([a, b], [0, 50])
    assert md == "A1\n\nB1\n" and [i["page_idx"] for i in items] == [0, 2, 50] and set(imgs) == {"x.jpg", "y.jpg"}


def test_fix_vi_ocr_only_outside_math():
    assert fix_vi_ocr("Bất đăng thức Cổ si: Dấu xây ra, Đặng: $đăng thức$") == \
        "Bất đẳng thức Cô si: Dấu xảy ra, Dạng: $đăng thức$"


@pytest.mark.skipif(not (shutil.which("mineru-api") and PDF.exists()), reason="cần mineru-api + llm/input/1.pdf")
def test_pool_end_to_end_two_workers(tmp_path):
    """Chạy thật: cắt 16 trang, 2 server -> md + content_list có page_idx 0..15 đủ cả hai nửa, ảnh ghi ra đĩa."""
    from pypdf import PdfReader, PdfWriter
    from llm.src.mineru_pool import run_pool
    w = PdfWriter()
    for pg in PdfReader(str(PDF)).pages[10:26]:
        w.add_page(pg)
    sample = tmp_path / "s.pdf"
    w.write(open(sample, "wb"))
    out = tmp_path / "out"
    run_pool(sample, out, workers=2, device="mps", method="txt")
    import json
    items = json.loads((out / "s_content_list.json").read_text(encoding="utf-8"))
    pages = {i["page_idx"] for i in items if isinstance(i.get("page_idx"), int)}
    assert max(pages) <= 15 and any(p >= 8 for p in pages) and any(p < 8 for p in pages)
    assert (out / "s.md").stat().st_size > 1000 and any((out / "images").iterdir())
    assert sum(1 for i in items if i["type"] == "equation") > 0


def test_run_mineru_falls_back_to_cli_when_pool_fails(tmp_path, monkeypatch):
    import subprocess
    import llm.src.mineru_pool as pool
    import llm.src.run_mineru as rm
    monkeypatch.setattr(rm.shutil, "which", lambda _: None)  # không có mineru-kit
    monkeypatch.setattr(pool, "run_pool", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("server chết")))
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = Path(cmd[cmd.index("-o") + 1]) / "x" / "auto"
        out.mkdir(parents=True)
        (out / "x.md").write_text("Bất đăng thức $a$", encoding="utf-8")
        (out / "x_content_list.json").write_text('[{"type":"text","text":"xây ra","page_idx":0}]', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rm.subprocess, "run", fake_run)
    rm.run_mineru(tmp_path / "x.pdf", tmp_path / "out", workers=2)
    assert calls and calls[0][0] == "mineru"
    assert "Bất đẳng thức $a$" in (tmp_path / "out/x/auto/x.md").read_text(encoding="utf-8")
    assert '"xảy ra"' in (tmp_path / "out/x/auto/x_content_list.json").read_text(encoding="utf-8")
