"""Chạy `mineru-kit parse ... -f zip --ocr-mode <mode> --tier <tier>` như một tiến trình con.

Cách gọi này giống lệnh đã chạy ổn và đã đo thời gian trên máy của bạn (log mineru-kit, -f zip). Khác rag_toan/src/run_mineru.py
(gọi không có -f zip): ở đây nhận zip (markdown + ảnh) rồi giải nén vào thư mục của từng phần.

- Thành công = có file .zip (mineru-kit hay thoát mã lỗi do telemetry của onnxruntime dù đã ghi xong).
- Có timeout, hủy được (giết cả cây tiến trình), đo RAM đỉnh (tổng RSS của tiến trình + con).
"""
import os
import shlex
import shutil
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None

GB = 1024 ** 3


class MinerUError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class MinerUCancelled(Exception):
    pass


@dataclass
class KitResult:
    duration_s: float
    peak_ram_gb: float
    returncode: int


def kit_command(cmd_setting: str) -> List[str]:
    parts = shlex.split(cmd_setting, posix=(os.name != "nt"))
    if os.name == "nt":
        parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'" else part
                 for part in parts]
    if len(parts) == 1:
        resolved = shutil.which(parts[0])
        if resolved:
            parts = [resolved]
    return parts


def _tree_rss_gb(pid: int) -> float:
    if psutil is None:
        return 0.0
    try:
        root = psutil.Process(pid)
        total = root.memory_info().rss
        for child in root.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
        return total / GB
    except psutil.Error:
        return 0.0


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if psutil is not None:
            root = psutil.Process(proc.pid)
            for child in root.children(recursive=True):
                try:
                    child.kill()
                except psutil.Error:
                    pass
            root.kill()
        else:
            proc.kill()
    except Exception:                                   # noqa: BLE001
        try:
            proc.kill()
        except Exception:                               # noqa: BLE001
            pass


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if dest != target and dest not in target.parents:
                raise MinerUError("MINERU_BAD_OUTPUT", f"File zip chứa đường dẫn không an toàn: {member.filename}")
        z.extractall(dest)


def _log_tail(log_path: Path, n: int = 600) -> str:
    try:
        return log_path.read_bytes()[-n:].decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def run_kit(pdf: Path, out_dir: Path, *, cmd: str, tier: str, ocr_mode: str, timeout_s: float, log_path: Path,
            cancel: threading.Event, fmt: str = "markdown", env_extra: Optional[Dict[str, str]] = None,
            on_start: Optional[Callable[[subprocess.Popen], None]] = None,
            on_sample: Optional[Callable[[float], None]] = None) -> KitResult:
    """fmt="markdown": `mineru-kit parse <pdf> -o <out_dir> --tier T` -> <out_dir>/<tên>.md, ảnh nhúng base64
    (đúng cách rag_toan/src/run_mineru.py và parallel_mineru.py đang gọi).
    fmt="zip": thêm `-f zip` -> markdown.md + images/ (kiểu cũ), giải nén vào out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_mode = fmt == "zip"
    tmp = out_dir / "_kit"
    target = tmp if zip_mode else out_dir
    if zip_mode:
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv = kit_command(cmd) + ["parse", str(pdf), "-o", str(target), "--tier", tier] + (["-f", "zip"] if zip_mode else []) \
        + ["--ocr-mode", ocr_mode]
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.update(env_extra or {})
    t0 = time.perf_counter()
    peak = 0.0
    with open(log_path, "ab") as log:
        log.write(("$ " + " ".join(argv) + "\n").encode("utf-8", errors="replace"))
        log.flush()
        try:
            proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        except FileNotFoundError as exc:
            raise MinerUError("MINERU_NOT_FOUND", f"Không chạy được '{argv[0]}': cài mineru-kit hoặc đặt MINERU_CMD trong .env.") from exc
        if on_start:
            on_start(proc)
        last_sample = 0.0
        while True:
            if proc.poll() is not None:
                break
            now = time.perf_counter()
            if cancel.is_set():
                _kill_tree(proc)
                proc.wait()
                raise MinerUCancelled()
            if now - t0 > timeout_s:
                _kill_tree(proc)
                proc.wait()
                raise MinerUError("MINERU_TIMEOUT", f"MinerU quá {int(timeout_s)} giây, đã dừng.")
            if now - last_sample >= 1.0:
                last_sample = now
                rss = _tree_rss_gb(proc.pid)
                peak = max(peak, rss)
                if on_sample:
                    on_sample(rss)
            time.sleep(0.2)
    duration = time.perf_counter() - t0
    if zip_mode:
        zips = list(tmp.glob("*.zip"))
        if not zips:
            raise MinerUError("MINERU_FAILED", f"MinerU không tạo ra file zip (mã thoát {proc.returncode}). {_log_tail(log_path)}")
        _safe_extract(zips[0], out_dir)
        shutil.rmtree(tmp, ignore_errors=True)
        if not (out_dir / "markdown.md").exists() and not list(out_dir.rglob("*.md")):
            raise MinerUError("MINERU_BAD_OUTPUT", "Zip của MinerU không có file markdown.")
    else:
        # Thành công = có file .md không rỗng (mineru-kit có thể thoát mã lỗi do telemetry dù đã ghi xong)
        if not any(p.is_file() and p.stat().st_size > 0 for p in out_dir.rglob("*.md")):
            raise MinerUError("MINERU_FAILED", f"MinerU không tạo ra file .md (mã thoát {proc.returncode}). {_log_tail(log_path)}")
    return KitResult(duration, peak, proc.returncode)
