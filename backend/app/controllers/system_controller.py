"""Controller: /api/health và /api/system/stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core.container import Container, get_container
from ..views.system_view import render_health, render_stats

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(c: Container = Depends(get_container)):
    return render_health(c.engine, c.settings)


@router.get("/system/stats")
def system_stats(c: Container = Depends(get_container)):
    return render_stats(c.scheduler.stats())
