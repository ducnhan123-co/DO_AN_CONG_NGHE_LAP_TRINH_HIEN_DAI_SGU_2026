"""Synchronize per-document artifacts to the legacy rag_toan data directories."""
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from backend.app.core.config import Settings
from backend.app.models import job_model
from backend.app.models.database import Document, Job, StageRun

_SYNC_LOCK = threading.RLock()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".syncing")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_run_artifacts(source: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".syncing")
    backup = target.with_name(target.name + ".previous")
    if temporary.exists():
        shutil.rmtree(temporary)
    if backup.exists():
        shutil.rmtree(backup)
    try:
        shutil.copytree(source, temporary, ignore=shutil.ignore_patterns(
            "input.pdf", "output.docx", "output.building.docx"))
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except Exception:
            if backup.exists():
                os.replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _write_manifest(path: Path, document: Document, job: Optional[Job], settings: Settings,
                    runs: list[StageRun]) -> None:
    name = document.display_name or document.filename
    progress = job_model.estimate_progress(
        job, runs, settings, tier=document.tier) if job is not None else 0.0
    manifest = {
        "document_id": document.id,
        "filename": document.filename,
        "display_name": document.display_name,
        "sha256": document.sha256,
        "num_pages": document.num_pages,
        "tier": document.tier,
        "status": document.status,
        "progress": progress,
        "job_id": job.id if job else None,
        "attempt": job.attempt if job else None,
        "stages": [
            {
                "stage": run.stage,
                "status": run.status,
                "shard_index": run.shard_index,
                "page_from": run.page_from,
                "page_to": run.page_to,
                "note": job_model.note_json(run),
            }
            for run in runs
        ],
        "input": str(settings.input_mirror_path(document.id, document.filename)),
        "docx": str(settings.docx_mirror_path(document.id, name)),
        "run_dir": str(settings.run_dir(document.id, document.filename)),
        "updated_at": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".syncing")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sync_document(settings: Settings, document: Document, job: Optional[Job] = None,
                  runs: Optional[list[StageRun]] = None, *, artifacts: bool = False,
                  outputs: bool = False) -> None:
    """Copy stable artifacts and status to data/input, data/docx_output, and data/runs."""
    with _SYNC_LOCK:
        _sync_document(settings, document, job, runs, artifacts=artifacts, outputs=outputs)


def _sync_document(settings: Settings, document: Document, job: Optional[Job] = None,
                   runs: Optional[list[StageRun]] = None, *, artifacts: bool = False,
                   outputs: bool = False) -> None:
    runs = runs if runs is not None else (list(job.stage_runs) if job else [])
    run_dir = settings.run_dir(document.id, document.filename)
    manifest_path = run_dir / "backend_run.json"
    if run_dir.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("document_id") != document.id:
            raise OSError(f"Run directory belongs to a different document: {run_dir}")
    elif run_dir.exists() and any(run_dir.iterdir()):
        raise OSError(f"Refusing to overwrite unowned run directory: {run_dir}")

    input_path = settings.pdf_path(document.id)
    input_mirror = settings.input_mirror_path(document.id, document.filename)
    if input_path.exists() and (
        not input_mirror.exists() or input_path.stat().st_size != input_mirror.stat().st_size
    ):
        _atomic_copy(input_path, input_mirror)

    name = document.display_name or document.filename
    docx_path = settings.docx_path(document.id)
    docx_mirror = settings.docx_mirror_path(document.id, name)
    work_md = settings.work_md(document.id)
    work_md_mirror = settings.work_md_mirror_path(document.id, name)
    if outputs:
        if docx_path.exists():
            _atomic_copy(docx_path, docx_mirror)
        if work_md.exists():
            _atomic_copy(work_md, work_md_mirror)
    if artifacts:
        _copy_run_artifacts(settings.doc_dir(document.id), run_dir)
    _write_manifest(run_dir / "backend_run.json", document, job, settings, runs)

    if outputs:
        for path in settings.docx_output_dir().glob(f"{document.id}_*"):
            if path not in (docx_mirror, work_md_mirror) and path.is_file():
                path.unlink()


def remove_document_mirrors(settings: Settings, document: Document) -> None:
    with _SYNC_LOCK:
        _remove_document_mirrors(settings, document)


def _remove_document_mirrors(settings: Settings, document: Document) -> None:
    run_dir = settings.run_dir(document.id, document.filename)
    if run_dir.exists():
        manifest_path = run_dir / "backend_run.json"
        if not manifest_path.is_file():
            raise OSError(f"Refusing to remove unowned run directory: {run_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("document_id") != document.id:
            raise OSError(f"Run directory belongs to a different document: {run_dir}")

    settings.input_mirror_path(document.id, document.filename).unlink(missing_ok=True)
    for pattern in (f"{document.id}_*.docx", f"{document.id}_*_for_docx.md"):
        for path in settings.docx_output_dir().glob(pattern):
            path.unlink()

    if run_dir.exists():
        shutil.rmtree(run_dir)


def sync_all_documents(settings: Settings, documents: list[tuple[Document, Optional[Job]]]) -> None:
    for document, job in documents:
        sync_document(settings, document, job, artifacts=True, outputs=True)
