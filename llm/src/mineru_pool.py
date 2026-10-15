"""MinerU nhanh: giữ model NÓNG trong N server `mineru-api`, mỗi server parse một dải trang.

Đã đo trên Apple M5 (MPS), 12 trang toán:
  CLI 1 tiến trình (nạp model mỗi file) 74s | 2 CLI song song 60s | 1 server nóng 52s
  2 request đồng thời vào CÙNG 1 server không nhanh hơn (GPU tuần tự) -> mỗi worker 1 server riêng.
Server khởi động lười ở lần parse đầu (nạp model ~26s) rồi dùng lại cho mọi file sau, tự tắt khi thoát.
Mọi lỗi -> ném exception để run_mineru() rơi về CLI cũ.
"""
import atexit
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import requests

_lock = threading.Lock()
_servers: List[Tuple[subprocess.Popen, str]] = []  # (process, url)


def split_ranges(total: int, n: int) -> List[Tuple[int, int]]:
    """Chia `total` trang thành tối đa n dải liên tiếp [start, end] (0-based, gồm cả end)."""
    n = max(1, min(n, total))
    base, extra = divmod(total, n)
    out, s = [], 0
    for k in range(n):
        size = base + (1 if k < extra else 0)
        out.append((s, s + size - 1))
        s += size
    return out


def merge_parts(parts: List[dict], starts: List[int]) -> Tuple[str, List[dict], Dict[str, bytes]]:
    """Ghép kết quả các dải: md nối theo thứ tự, page_idx cộng offset (server trả số trang tương đối),
    ảnh gộp lại (tên ảnh là hash nội dung nên không trùng)."""
    md, items, imgs = [], [], {}
    for part, start in zip(parts, starts):
        md.append(part["md"].strip())
        for it in part["content_list"]:
            if isinstance(it.get("page_idx"), int):
                it["page_idx"] += start
            items.append(it)
        imgs.update(part["images"])
    return "\n\n".join(m for m in md if m) + "\n", items, imgs


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_PIDFILE = Path(__file__).resolve().parents[2] / "runtime" / "mineru_pool.pids"


def _kill_stale() -> None:
    """Backend bị kill cứng (atexit không chạy) thì server cũ còn mồ côi: dọn theo pidfile, chỉ kill đúng tiến trình mineru-api."""
    try:
        pids = [int(x) for x in _PIDFILE.read_text().split()]
    except (OSError, ValueError):
        return
    for pid in pids:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
        if "mineru-api" in cmd:
            os.kill(pid, 15)
    _PIDFILE.unlink(missing_ok=True)


def _save_pids() -> None:
    _PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    _PIDFILE.write_text(" ".join(str(p.pid) for p, _ in _servers))


def _stop_all() -> None:
    for proc, _ in _servers:
        if proc.poll() is None:
            proc.terminate()


atexit.register(_stop_all)


def _start_server(device: str, timeout: float = 180.0) -> Tuple[subprocess.Popen, str]:
    exe = Path(sys.executable).parent / "mineru-api"
    cmd = [str(exe) if exe.exists() else "mineru-api"]
    port = _free_port()
    proc = subprocess.Popen(cmd + ["--host", "127.0.0.1", "--port", str(port)],
                            env={**os.environ, "MINERU_DEVICE_MODE": device},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError("mineru-api thoát ngay khi khởi động")
        try:
            if requests.get(url + "/openapi.json", timeout=2).ok:
                return proc, url
        except requests.RequestException:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("mineru-api không lên kịp trong %.0fs" % timeout)


def get_servers(n: int, device: str) -> List[str]:
    """Trả về n URL server còn sống (tạo thêm nếu thiếu, bỏ server đã chết)."""
    with _lock:
        if not _servers:
            _kill_stale()
        _servers[:] = [(p, u) for p, u in _servers if p.poll() is None]
        while len(_servers) < n:
            _servers.append(_start_server(device))
            _save_pids()
        return [u for _, u in _servers[:n]]


def _parse_range(url: str, pdf: Path, start: int, end: int, lang: str, method: str,
                 formula: bool, table: bool) -> dict:
    with open(pdf, "rb") as f:
        r = requests.post(url + "/file_parse", timeout=3600,
                          files={"files": (pdf.name, f, "application/pdf")},
                          data={"backend": "pipeline", "lang_list": lang, "parse_method": method,
                                "formula_enable": str(formula).lower(), "table_enable": str(table).lower(),
                                "start_page_id": start, "end_page_id": end,
                                "return_md": "true", "return_content_list": "true",
                                "return_images": "true", "response_format_zip": "true"})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    md = next(n for n in names if n.endswith(".md"))
    cl = next(n for n in names if n.endswith("_content_list.json"))
    images = {Path(n).name: z.read(n) for n in names if "/images/" in n and not n.endswith("/")}
    return {"md": z.read(md).decode("utf-8"), "content_list": json.loads(z.read(cl)), "images": images}


def run_pool(pdf_path: Path, out_dir: Path, *, workers: int = 2, device: str = "mps",
             lang: str = "latin", method: str = "auto", formula: bool = True, table: bool = True,
             min_pages_per_worker: int = 8) -> None:
    """Parse PDF qua pool server nóng và ghi {stem}.md, {stem}_content_list.json, images/ vào out_dir."""
    from pypdf import PdfReader
    total = len(PdfReader(str(pdf_path)).pages)
    n = max(1, min(workers, total // max(1, min_pages_per_worker)))
    ranges = split_ranges(total, n)
    urls = get_servers(len(ranges), device)
    print(f"[MinerU-pool] {pdf_path.name}: {total} trang -> {len(ranges)} server nóng {ranges}")
    with ThreadPoolExecutor(max_workers=len(ranges)) as ex:
        futs = [ex.submit(_parse_range, u, pdf_path, s, e, lang, method, formula, table)
                for u, (s, e) in zip(urls, ranges)]
        parts = [f.result() for f in futs]
    md, items, imgs = merge_parts(parts, [s for s, _ in ranges])
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(exist_ok=True)
    for name, data in imgs.items():
        (out_dir / "images" / name).write_bytes(data)
    stem = pdf_path.stem
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    (out_dir / f"{stem}_content_list.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def prewarm(n: int, device: str, lang: str = "latin") -> None:
    """Khởi động n server và cho mỗi server parse 1 trang mẫu (chữ + OCR) để model nạp sẵn: upload đầu tiên khỏi chờ ~25-30s.
    Gọi ở thread nền lúc khởi động backend; mọi lỗi để caller nuốt."""
    import tempfile
    import fitz
    d = fitz.open()
    pg = d.new_page(width=300, height=200)
    pg.insert_text((20, 60), "Warm up: x^2 + y^2 = z^2", fontsize=14)
    tmp = Path(tempfile.gettempdir()) / "mineru_warm.pdf"
    d.save(str(tmp))
    urls = get_servers(n, device)
    with ThreadPoolExecutor(max_workers=n) as ex:
        list(ex.map(lambda u: [_parse_range(u, tmp, 0, 0, lang, m, True, True) for m in ("txt", "ocr")], urls))
