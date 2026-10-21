"""Chạy `mineru-kit parse` cho từng dải trang, song song nhiều tiến trình (như parallel_mineru.py của rag_toan).

Giữ nguyên bố cục của rag_toan để kết quả ghép dùng lại được merge_parts():
    <run_dir>/mineru_parts/pdf/part_k_pS-E.pdf   PDF của từng phần
    <run_dir>/mineru_parts/out/part_k_pS-E/      kết quả MinerU của từng phần (+ file .done khi xong)

Khác bản gốc (vì backend cần điều khiển từ giao diện):
  * dùng Popen thay vì subprocess.run  -> HỦY được ngay (kill cả cây tiến trình)
  * cập nhật tiến độ/RAM từng phần      -> giao diện hiện "Phần 1/2 · trang 1–40 · ~35%"
  * semaphore toàn cục                  -> nhiều tài liệu cùng chạy vẫn không vượt trần tiến trình MinerU
Tiến độ là ƯỚC LƯỢNG theo thời gian (mineru-kit không báo %): số trang x giây/trang, giây/trang tự học
từ các lần chạy trước (trung bình trượt lưu trong bảng meta).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Tuple

try:
    import psutil
except ImportError:          # psutil tùy chọn: thiếu thì không đo RAM, hủy bằng terminate()
    psutil = None

from ..core.config import Settings
from ..core.errors import Cancelled, PipelineError
from ..core.log_router import log_line
from .engine import Engine


class MineruRunner:
    def __init__(self, settings: Settings, engine: Engine):
        self.s = settings
        self.engine = engine
        self._sem = threading.BoundedSemaphore(settings.procs_cap)
        self._procs: Dict[str, set] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ trạng thái toàn cục
    def running_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._procs.values())

    def kill(self, doc_id: str) -> None:
        with self._lock:
            procs = list(self._procs.get(doc_id, ()))
        for p in procs:
            self._kill_tree(p)

    def _register(self, doc_id: str, proc) -> None:
        with self._lock:
            self._procs.setdefault(doc_id, set()).add(proc)

    def _unregister(self, doc_id: str, proc) -> None:
        with self._lock:
            self._procs.get(doc_id, set()).discard(proc)

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            if psutil is not None:
                parent = psutil.Process(proc.pid)
                for ch in parent.children(recursive=True):
                    try:
                        ch.kill()
                    except psutil.Error:
                        pass
                parent.kill()
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _rss_gb(proc: subprocess.Popen) -> float:
        if psutil is None:
            return 0.0
        try:
            p = psutil.Process(proc.pid)
            total = p.memory_info().rss + sum(c.memory_info().rss for c in p.children(recursive=True))
            return total / (1 << 30)
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ chia phần
    def plan_ranges(self, total_pages: int) -> List[Tuple[int, int]]:
        """Giống run_mineru_parallel: PDF ngắn thì giảm số tiến trình (min_pages_per_worker trang/tiến trình)."""
        P = self.engine.load().parallel
        n = max(1, min(self.s.mineru_workers, total_pages // max(1, self.s.min_pages_per_worker)))
        return P.split_page_ranges(total_pages, n)

    # ------------------------------------------------------------------ chạy
    def run(self, doc_id: str, mineru_pdf: Path, run_dir: Path, ranges: List[Tuple[int, int]],
            shards: List[dict], on_update: Callable[[], None], cancel: threading.Event,
            sec_per_page: float, record_spp: Callable[[float], None]) -> List[Path]:
        """Chạy mọi phần, trả về danh sách thư mục output của từng phần (theo thứ tự trang)."""
        if not self.engine.mineru_found:
            raise PipelineError(
                "MINERU_NOT_FOUND",
                f"Không tìm thấy lệnh “{self.engine.mineru_argv0}”. Cài MinerU (pip install mineru) hoặc đặt MINERU_CMD.")
        P = self.engine.load().parallel
        parts_root = run_dir / "mineru_parts"
        part_pdfs = P.split_pdf(mineru_pdf, ranges, parts_root / "pdf")
        part_outs = [parts_root / "out" / p.stem for p in part_pdfs]
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        def one(k: int, force_rerun: bool, delay: float) -> None:
            self._run_shard(doc_id, k, part_pdfs[k], part_outs[k], logs_dir / f"mineru_part_{k + 1}.log",
                            shards[k], on_update, cancel, delay, sec_per_page, record_spp, force_rerun)

        failed: List[int] = []
        with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
            futs = {k: pool.submit(one, k, False, k * self.s.mineru_stagger) for k in range(len(ranges))}
            for k, fut in futs.items():
                try:
                    fut.result()
                except Cancelled:
                    cancel.set()
                except PipelineError as ex:
                    if ex.code == "MINERU_NOT_FOUND":
                        cancel.set()
                        raise
                    failed.append(k)
                    log_line(f"[LỖI] phần {k + 1}: {ex.message}")
        if cancel.is_set():
            raise Cancelled()

        if failed:                              # như rag_toan: chạy lại TUẦN TỰ các phần lỗi trước khi báo lỗi
            log_line(f"{len(failed)} phần lỗi khi chạy song song -> chạy lại tuần tự")
            still: List[int] = []
            for k in sorted(failed):
                try:
                    one(k, True, 0.0)
                except PipelineError as ex:
                    still.append(k)
                    log_line(f"[LỖI] phần {k + 1} (chạy lại): {ex.message}")
            if still:
                raise PipelineError("MINERU_FAILED", "MinerU lỗi ở " + "; ".join(
                    f"phần {k + 1} ({shards[k].get('error', '')})" for k in still))
        return part_outs

    def _sleep(self, seconds: float, cancel: threading.Event) -> None:
        if seconds > 0 and cancel.wait(seconds):
            raise Cancelled()

    def _run_shard(self, doc_id, k, part_pdf: Path, part_out: Path, log_path: Path, shard: dict,
                   on_update, cancel: threading.Event, delay: float, spp: float, record_spp,
                   force_rerun: bool) -> None:
        P = self.engine.load().parallel
        part_out.mkdir(parents=True, exist_ok=True)
        done = part_out / P.DONE_MARK
        if not force_rerun and P._part_finished(part_out):
            done.write_text("ok", encoding="utf-8")
            shard.update(status="done", progress=100.0, error=None)
            on_update()
            log_line(f"[Phần {k + 1}] đã xong từ lần chạy trước, bỏ qua")
            return

        shard.update(status="pending", progress=0.0, error=None)
        on_update()
        self._sleep(delay, cancel)
        while not self._sem.acquire(timeout=0.5):       # chờ slot tiến trình toàn máy
            if cancel.is_set():
                raise Cancelled()
        proc = None
        try:
            if cancel.is_set():
                raise Cancelled()
            # Phần chưa xong thì dọn sạch rồi chạy lại từ đầu (tránh lẫn file dở dang)
            shutil.rmtree(part_out, ignore_errors=True)
            part_out.mkdir(parents=True, exist_ok=True)
            cmd = self.engine.mineru_command(part_pdf, part_out)
            log_line(f"[Phần {k + 1}] bắt đầu: {' '.join(cmd)}")
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            t0 = time.time()
            expected = max(15.0, (shard["page_to"] - shard["page_from"] + 1) * spp)
            shard.update(status="running", progress=1.0, elapsed_s=0.0, peak_ram_gb=0.0)
            on_update()
            with open(log_path, "wb") as logf:
                logf.write(("$ " + " ".join(cmd) + "\n\n").encode("utf-8"))
                logf.flush()
                try:
                    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                            env=env)
                except FileNotFoundError as ex:
                    raise PipelineError("MINERU_NOT_FOUND", f"Không chạy được “{cmd[0]}”: {ex}") from ex
                self._register(doc_id, proc)
                peak, last_push = 0.0, 0.0
                while True:
                    rc = proc.poll()
                    if cancel.is_set():
                        self._kill_tree(proc)
                        proc.wait()
                        raise Cancelled()
                    el = time.time() - t0
                    peak = max(peak, self._rss_gb(proc))
                    shard.update(elapsed_s=round(el, 1), peak_ram_gb=round(peak, 2),
                                 progress=round(min(95.0, max(1.0, 100.0 * el / expected)), 1))
                    if time.time() - last_push >= 1.0:
                        on_update()
                        last_push = time.time()
                    if rc is not None:
                        break
                    cancel.wait(0.5)
            elapsed = time.time() - t0
            self._write_part_log(part_out, cmd, log_path)
            if rc != 0:
                tail = self._tail(log_path)
                shard.update(status="failed", error=f"exit {rc}: {tail}"[:300])
                on_update()
                raise PipelineError("MINERU_FAILED", f"Phần {k + 1} lỗi (exit {rc}): {tail}")
            if P._find_md(part_out) is None:
                shard.update(status="failed", error="MinerU chạy xong nhưng không tạo file .md")
                on_update()
                raise PipelineError("MINERU_FAILED", f"Phần {k + 1}: không thấy file .md trong {part_out}")
            done.write_text("ok", encoding="utf-8")
            shard.update(status="done", progress=100.0, elapsed_s=round(elapsed, 1), error=None)
            on_update()
            pages = shard["page_to"] - shard["page_from"] + 1
            if elapsed > 5 and pages > 0:
                record_spp(elapsed / pages)
            log_line(f"[Phần {k + 1}] xong sau {elapsed:.0f}s")
        except Cancelled:
            shard.update(status="pending", progress=0.0)
            on_update()
            raise
        finally:
            if proc is not None:
                self._unregister(doc_id, proc)
            self._sem.release()

    @staticmethod
    def _write_part_log(part_out: Path, cmd: list, log_path: Path) -> None:
        """Ghi <part_out>/mineru_log.txt đúng định dạng của parallel_mineru._run_one_part.
        File này được src dùng: audit.dropped_pages() đọc dòng `page_idx=N ... dropped=M`,
        parallel_mineru._part_finished() đọc dòng `Parsed N input(s)` để biết phần đã xong."""
        try:
            body = log_path.read_text(encoding="utf-8", errors="replace")
            body = body.split("\n\n", 1)[1] if body.startswith("$ ") and "\n\n" in body else body
            (part_out / "mineru_log.txt").write_text(
                f"$ {' '.join(cmd)}\n\n--- STDOUT ---\n{body}\n\n--- STDERR ---\n(đã gộp vào STDOUT)\n",
                encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _tail(log_path: Path, lines: int = 4) -> str:
        try:
            txt = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            return " | ".join(l.strip() for l in txt[-lines:] if l.strip())
        except OSError:
            return ""
