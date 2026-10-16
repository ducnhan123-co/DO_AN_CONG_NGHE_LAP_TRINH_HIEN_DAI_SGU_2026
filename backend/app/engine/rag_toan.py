"""Backend adapter for the sibling rag_toan modules; rag_toan source files stay untouched."""
import importlib
import json
import subprocess
import sys
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.engine.mineru_runner import MinerUCancelled, MinerUError, run_kit

_lock = threading.Lock()
_module = None
_modules = {}
_pandoc_timeout_s = 900


class EngineNotFound(RuntimeError):
    pass


def find_project_dir() -> Optional[Path]:
    s = get_settings()
    required = (
        "main.py",
        "src/build_docx.py",
        "src/parallel_mineru.py",
        "src/run_mineru.py",
        "src/structured.py",
        "src/chunking.py",
        "src/validate.py",
    )

    def is_pipeline_project(path: Path) -> bool:
        return all((path / relative).is_file() for relative in required)

    if s.rag_toan_dir:
        p = Path(s.rag_toan_dir)
        p = p if p.is_absolute() else ROOT_DIR / p
        return p.resolve() if is_pipeline_project(p) else None
    expected = ROOT_DIR / "rag_toan"
    if is_pipeline_project(expected):
        return expected.resolve()
    for directory in sorted(ROOT_DIR.iterdir()):
        if (directory.is_dir() and directory.name not in ("backend", "frontend")
                and not directory.name.startswith(".") and is_pipeline_project(directory)):
            return directory.resolve()
    return None


def engine_info() -> dict:
    d = find_project_dir()
    return {"found": d is not None, "dir": str(d) if d else None}


class _TimeoutSubprocess:
    """Thay cho `subprocess` bên trong build_docx: mọi subprocess.run (Pandoc) đều có timeout."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, *args, **kwargs):
        kwargs.setdefault("timeout", _pandoc_timeout_s)
        return subprocess.run(*args, **kwargs)


def _load():
    global _module
    with _lock:
        if _module is not None:
            return _module
        d = find_project_dir()
        if d is None:
            raise EngineNotFound(
                "Không tìm thấy dự án rag_toan (cần main.py và các module xử lý trong src/). "
                "Đặt thư mục đó NGANG HÀNG với backend/ "
                "và frontend/, hoặc đặt RAG_TOAN_DIR trong backend/.env.")
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
        existing = sys.modules.get("src")
        if existing is not None and not str(getattr(existing, "__file__", "") or "").startswith(str(d)):
            raise EngineNotFound(f"Đã có một package 'src' khác trong sys.path ({getattr(existing, '__file__', '?')}), "
                                 f"không nạp được {d / 'src'}.")
        mod = importlib.import_module("src.build_docx")
        mod.subprocess = _TimeoutSubprocess()
        _module = mod
        return _module


def _load_module(name: str):
    _load()
    with _lock:
        if name not in _modules:
            _modules[name] = importlib.import_module(f"src.{name}")
        return _modules[name]


def prepare_work_md(markdown_text: str, md_path: Path, work_md: Path):
    return _load().prepare_work_md(markdown_text, md_path, work_md)


def fix_legacy_tex_bf(markdown_text: str) -> str:
    return _load().fix_legacy_tex_bf(markdown_text)


def find_content_list(mineru_dir: Path) -> Optional[Path]:
    return _load_module("run_mineru").find_content_list(mineru_dir)


def md_to_docx(work_md: Path, docx_path: Path, resource_dir: Path, timeout_s: int = 900):
    """Dựng DOCX bằng md_to_docx của rag_toan. Quá timeout_s thì dừng Pandoc và báo RuntimeError."""
    global _pandoc_timeout_s
    mod = _load()
    _pandoc_timeout_s = timeout_s
    try:
        return mod.md_to_docx(work_md, docx_path, resource_dir)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Pandoc quá {timeout_s}s, đã dừng.") from exc


def run_mineru_parallel(
    pdf_path: Path,
    out_dir: Path,
    *,
    cmd: str,
    tier: str,
    ocr_mode: str,
    timeout_s: float,
    log_path: Path,
    cancel: threading.Event,
    workers: int = 2,
    min_pages_per_worker: int = 5,
    stagger_s: float = 20.0,
    fmt: str = "markdown",
    on_progress: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    """Run the rag_toan page-splitting/merge flow with backend-managed child processes."""
    parallel = _load_module("parallel_mineru")
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    parts_root = out_dir.parent / "mineru_parts"
    shutil.rmtree(parts_root, ignore_errors=True)

    total_pages = len(parallel.PdfReader(str(pdf_path)).pages)
    if total_pages < 1:
        raise MinerUError("MINERU_BAD_INPUT", "PDF không có trang để xử lý.")
    part_count = max(1, min(max(1, workers), total_pages // max(1, min_pages_per_worker)))
    ranges = parallel.split_page_ranges(total_pages, part_count)
    part_pdfs = parallel.split_pdf(pdf_path, ranges, parts_root / "pdf")
    part_outs = [parts_root / "out" / part_pdf.stem for part_pdf in part_pdfs]
    results: Dict[int, Any] = {}
    failures: Dict[int, Exception] = {}
    progress_lock = threading.Lock()
    part_progress: List[Dict[str, Any]] = [
        {
            "index": index + 1,
            "page_from": start + 1,
            "page_to": end,
            "status": "planned",
            "progress": 0.0,
            "elapsed_s": 0.0,
            "peak_ram_gb": 0.0,
        }
        for index, (start, end) in enumerate(ranges)
    ]
    started = time.perf_counter()

    def report(index: int, **updates: Any) -> None:
        if on_progress is None:
            return
        with progress_lock:
            part_progress[index].update(updates)
            snapshot = [dict(part) for part in part_progress]
        on_progress(snapshot)

    def run_part(index: int, *, stagger: bool = True) -> Any:
        try:
            delay = max(0.0, stagger_s) * index if stagger else 0.0
            if cancel.wait(delay):
                raise MinerUCancelled()
            part_out = part_outs[index]
            part_out.mkdir(parents=True, exist_ok=True)
            page_count = ranges[index][1] - ranges[index][0]
            expected_s = 15 + page_count * (15.0 if tier == "advanced" else 6.5 if tier == "standard" else 10.0)
            part_started = [None]
            peak_ram = [0.0]

            def on_start(_proc) -> None:
                part_started[0] = time.perf_counter()
                report(index, status="running", progress=0.0, elapsed_s=0.0)

            def on_sample(rss: float) -> None:
                elapsed = time.perf_counter() - (part_started[0] or time.perf_counter())
                peak_ram[0] = max(peak_ram[0], rss)
                fraction = min(0.95, elapsed / expected_s)
                report(index, status="running", progress=round(fraction * 100, 1),
                       elapsed_s=round(elapsed, 1), peak_ram_gb=peak_ram[0])

            result = run_kit(
                part_pdfs[index],
                part_out,
                cmd=cmd,
                tier=tier,
                ocr_mode=ocr_mode,
                timeout_s=timeout_s,
                log_path=log_path.with_name(f"{log_path.stem}-part-{index + 1}{log_path.suffix}"),
                cancel=cancel,
                fmt=fmt,
                on_start=on_start,
                on_sample=on_sample,
            )
            report(index, status="done", progress=100.0, elapsed_s=round(result.duration_s, 1),
                   peak_ram_gb=result.peak_ram_gb)
            return result
        except MinerUCancelled:
            report(index, status="cancelled")
            raise
        except Exception as exc:
            report(index, status="failed", error=str(exc)[:500])
            raise

    try:
        if on_progress is not None:
            on_progress([dict(part) for part in part_progress])
        with ThreadPoolExecutor(max_workers=len(ranges), thread_name_prefix="mineru-part") as pool:
            futures = {pool.submit(run_part, index): index for index in range(len(ranges))}
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except MinerUCancelled:
                    if cancel.is_set():
                        raise
                    failures[index] = MinerUError("MINERU_CANCELLED", "Một phần MinerU đã bị hủy.")
                except Exception as exc:
                    failures[index] = exc

        if cancel.is_set():
            raise MinerUCancelled()

        for index in sorted(failures) if len(ranges) > 1 else ():
            if cancel.is_set():
                raise MinerUCancelled()
            shutil.rmtree(part_outs[index], ignore_errors=True)
            try:
                results[index] = run_part(index, stagger=False)
                del failures[index]
            except MinerUCancelled:
                raise
            except Exception as exc:
                failures[index] = exc

        if failures:
            details = "\n".join(f"Phần {index + 1}: {error}" for index, error in sorted(failures.items()))
            first_error = failures[min(failures)]
            if isinstance(first_error, MinerUError):
                raise MinerUError(first_error.code, f"{first_error.message}\n{details}") from first_error
            raise MinerUError("MINERU_FAILED", details) from first_error

        md_path, content_list_path = parallel.merge_parts(part_outs, ranges, out_dir, pdf_path.stem)
        (out_dir / "parallel_info.json").write_text(
            json.dumps({
                "total_pages": total_pages,
                "workers": len(ranges),
                "ranges_1based": [[start + 1, end] for start, end in ranges],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "duration_s": time.perf_counter() - started,
            "peak_ram_gb": sum(result.peak_ram_gb for result in results.values()),
            "returncodes": [results[index].returncode for index in sorted(results)],
            "workers": len(ranges),
            "ranges_1based": [[start + 1, end] for start, end in ranges],
            "parts": [dict(part) for part in part_progress],
            "markdown": str(md_path),
            "content_list": str(content_list_path) if content_list_path else None,
        }
    finally:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as combined:
            for index in range(len(ranges)):
                part_log = log_path.with_name(f"{log_path.stem}-part-{index + 1}{log_path.suffix}")
                if part_log.exists():
                    combined.write(f"===== MinerU part {index + 1} =====\n")
                    combined.write(part_log.read_text(encoding="utf-8", errors="replace"))
                    combined.write("\n")


def build_structured_assets(
    content_list_path: Optional[Path],
    markdown_path: Path,
    markdown_text: str,
    source: str,
    doc_id: str,
    output_dir: Path,
) -> Dict[str, Any]:
    structured = _load_module("structured")
    chunking = _load_module("chunking")
    validation = _load_module("validate")
    config = _load_module("config")

    raw = structured.load_raw(content_list_path, markdown_path, md_text=markdown_text)
    blocks = structured.normalize_blocks(raw, source=source, doc_id=doc_id)
    structured_path = structured.save_structured(blocks, output_dir / "structured_data.json")
    chunks = chunking.build_chunks(blocks, config.MAX_CHARS, config.OVERLAP)
    chunks_path = output_dir / "chunks.json"
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    report = validation.validate_chunks(chunks, expected_source=source, expected_doc_id=doc_id)
    validation_path = output_dir / "validation.json"
    validation_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "blocks": len(blocks),
        "chunks": len(chunks),
        "chunk_validation_ok": report["ok"],
        "chunk_validation_problems": report["problems"][:20],
        "structured_path": str(structured_path),
        "chunks_path": str(chunks_path),
        "validation_path": str(validation_path),
    }
