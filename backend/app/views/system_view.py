"""View cho /api/health và /api/system/stats (trường đặt đúng theo checkHealth()/refreshStats() trong index.html)."""
from __future__ import annotations

from typing import Dict


def render_health(engine, settings) -> Dict:
    return {
        "ok": True,
        "engine_found": engine.found,
        "pandoc": engine.pandoc_found,
        "mineru_found": engine.mineru_found,
        "mineru_cmd": engine.mineru_argv0,
        "tesseract": engine.tesseract_found,
        "tier": settings.mineru_tier,
        "workers_per_doc": settings.mineru_workers,
        "rag_index": settings.rag_index,
    }


def render_stats(stats: Dict) -> Dict:
    return {
        "running": stats["running"],
        "main_slots": stats["main_slots"],
        "aux_mode": stats["aux_mode"],
        "mineru_processes": stats["mineru_processes"],
        "queued_tasks": stats["queued_tasks"],
        "last_decision": stats["last_decision"],
    }
