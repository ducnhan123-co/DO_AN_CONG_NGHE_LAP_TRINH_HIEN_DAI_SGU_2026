"""Run EXACT Kiệt CLI PDF->Math Repair->DOCX code in an isolated child process.

Uses the existing FastAPI /api/upload and job model, NOT a separate Kiet API.
The output DOCX is copied byte-for-byte after ZIP validation. No E5/Qwen is involved.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import ROOT_DIR, get_settings
from backend.app.models.database import Document, DocumentStatus, Job

logger = logging.getLogger(__name__)


def _paragraph_chunks(markdown: str, document_id: str, filename: str) -> list[dict]:
    """Fallback lookup. Advanced MinerU Markdown has no reliable page mapping.

    Keep math/display blocks intact; do not fabricate page citations.
    The Word file remains the unmodified output of Kiệt's CLI.
    """
    paragraphs = [p.strip() for p in markdown.split("\n\n") if p.strip()]
    blocks, buf, idx = [], [], 0
    def flush():
        nonlocal idx, buf
        if not buf:
            return
        blocks.append({
            "chunk_id": idx, "doc_id": document_id, "source": filename,
            "text": "\n\n".join(buf), "section": "Nội dung",
            "page": None, "pages": [], "content_types": ["text"],
        })
        idx += 1
        buf = []
    for p in paragraphs:
        if buf and sum(len(s) for s in buf) + len(p) > 1800:
            flush()
        buf.append(p)
    flush()
    return blocks


def _import_kiet_results(doc: Document, workspace: Path, target: Path) -> tuple[int, int]:
    """Copy only validated artifacts; never modify Kiệt's generated Word content."""
    word = workspace / "docx_output" / "input.docx"
    if not word.is_file() or not word.stat().st_size:
        raise RuntimeError("Kiệt CLI completed without a DOCX file")
    with zipfile.ZipFile(word) as archive:
        if archive.testzip() or "word/document.xml" not in archive.namelist():
            raise RuntimeError("Kiệt CLI DOCX is corrupt or missing word/document.xml")

    runs = [p for p in (workspace / "runs").glob("input_*") if p.is_dir()]
    if len(runs) != 1:
        raise RuntimeError(f"Expected one Kiệt run directory, got {len(runs)}")
    run = runs[0]
    if not (run / "audit.json").is_file():
        raise RuntimeError("Missing Kiệt audit.json; refusing incomplete DOCX")
    if not (run / "repair_report.json").is_file():
        raise RuntimeError("Missing Kiệt repair_report.json; check --no-repair flags")

    for original, name in ((run / "audit.json", "audit.json"),
                           (run / "repair_report.json", "repair_report.json"),
                           (run / "scan_clean.json", "scan_clean.json"),
                           (workspace / "docx_output" / "input_for_docx.md",
                            "work_for_docx.md")):
        if original.is_file():
            shutil.copy2(original, target / name)

    # Kiệt's Advanced tier may output only Markdown; do not invent page numbers.
    mineru_mds = [p for p in (run / "mineru").rglob("*.md") if p.is_file()]
    md = max(mineru_mds, key=lambda p: p.stat().st_size) if mineru_mds else None
    chunks = _paragraph_chunks(md.read_text(encoding="utf-8", errors="replace"),
                               doc.id, doc.filename) if md else []
    (target / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    (target / "validation.json").write_text(json.dumps({
        "ok": True, "source": "kiet_cli", "docx_zip_valid": True,
        "page_mapping": "unknown", "num_chunks": len(chunks),
        "note": "Markdown fallback contains no provable page citations."
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    staged = target / ".output.kiet.staging.docx"
    try:
        shutil.copy2(word, staged)
        staged.replace(target / "output.docx")
    finally:
        staged.unlink(missing_ok=True)
    return 1, len(chunks)


def run_kiet_job(document_id: str, job_id: str) -> None:
    from backend.app.models import pipeline_model as state
    from backend.app.models.database import JobStatus, SessionLocal
    settings = get_settings()
    with SessionLocal() as db:
        doc = db.get(Document, document_id)
        job = db.get(Job, job_id)
        if doc is None or job is None:
            logger.error("Missing Kiệt job or document %s / %s", document_id, job_id)
            return
        try:
            target = settings.doc_dir(doc.id)
            workspace = target / "kiet_work"
            workspace.mkdir(parents=True, exist_ok=True)
            state._running(db, doc, job, DocumentStatus.mineru_parsing, 10)
            env = os.environ.copy()
            env["KIET_WORK_ROOT"] = str(workspace)
            env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent),
                                            env.get("PATH", "")))
            tier = settings.kiet_tier
            if tier not in {"flash", "basic", "standard", "advanced"}:
                raise ValueError("Invalid KIET_TIER")

            cmd = [sys.executable, str(ROOT_DIR / "kiet_cli.py"),
                   "--pdf", str(settings.pdf_path(doc.id)),
                   "--workers", "1", "--tier", tier]
            log_file = target / "kiet_cli.log"
            with log_file.open("w", encoding="utf-8") as stream:
                stream.write("Command: kiet_cli.py --pdf [per-document input] "
                             f"--workers 1 --tier {tier}\n")
                stream.flush()
                result = subprocess.run(
                    cmd, cwd=str(ROOT_DIR), env=env, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=settings.kiet_timeout_s,
                    check=False)
            if result.returncode:
                raise RuntimeError(f"Kiệt CLI exited {result.returncode}; see kiet_cli.log")

            state._running(db, doc, job, DocumentStatus.building_docx, 90)
            n_sections, n_chunks = _import_kiet_results(doc, workspace, target)
            state._succeeded(db, doc, job, n_sections, n_chunks)
            logger.info("Kiet CLI ready doc=%s, chunks=%d", doc.id, n_chunks)
        except subprocess.TimeoutExpired:
            db.rollback()
            state._failed(db, doc, job, "KIET_TIMEOUT",
                          f"Kiệt CLI exceeded {settings.kiet_timeout_s}s")
        except Exception as exc:
            logger.exception("Kiet CLI failed doc=%s", document_id)
            db.rollback()
            state._failed(db, doc, job, "KIET_CLI_FAILED", str(exc)[:500])
