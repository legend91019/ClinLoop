"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from apps.api.app.dependencies import SessionDep
from apps.api.app.settings import get_settings
from packages.contracts import HealthResponse

__all__ = ["router"]

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
def healthz() -> HealthResponse:
    """Return ``{"status": "ok"}`` when the process is serving."""
    settings = get_settings()
    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/readyz", summary="Readiness probe")
def readyz(session: SessionDep) -> dict[str, str]:
    """Return ``ok`` only when the database answers a trivial query."""
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
