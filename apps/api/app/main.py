"""FastAPI application assembly.

This module is deliberately thin (task 4): it wires routes, lifecycle and
exception handling, and nothing else.

    * persistence       -> :mod:`apps.api.app.repositories`
    * domain policy     -> :mod:`packages.domain`
    * wire contracts    -> :mod:`packages.contracts`

No business rules live here. No route ever returns a SQLAlchemy object.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.app import db as db_module
from apps.api.app.dependencies import (
    EventPublisher,
    NoopEventPublisher,
    get_event_publisher,
)
from apps.api.app.routes import (
    agentarts_tools,
    audit,
    events,
    evidence,
    handoff,
    health,
    loops,
    review,
    trace,
)
from apps.api.app.settings import get_settings

__all__ = ["app", "create_app"]


def create_app(*, event_publisher: EventPublisher | None = None) -> FastAPI:
    """Build the ClinLoop API.

    Args:
        event_publisher: overrides the process-wide publisher. Tests and
            the worker pass their own; the default simply accepts events.
    """
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Verify database connectivity at boot, clean up at shutdown."""
        from sqlalchemy import text

        engine = db_module.build_engine()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - boot must not crash API-only dev
            # The API still serves /healthz so an operator can see the
            # failure; /readyz reports the database as unreachable.
            pass
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Event-driven clinical workflow continuity API. "
            "Synthetic data only — engineered validation, not evidence of "
            "clinical effectiveness. The API proposes; it never diagnoses, "
            "recommends treatment, or writes to a medical record."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "health", "description": "Liveness and readiness."},
            {"name": "events", "description": "Ingest and timeline."},
            {"name": "loops", "description": "Open Loop read models."},
            {"name": "findings", "description": "Workflow gaps and evidence."},
        ],
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Actor-Id", "X-Actor-Role"],
    )

    if event_publisher is not None:
        application.dependency_overrides[get_event_publisher] = lambda: event_publisher

    application.include_router(health.router)
    application.include_router(events.router, prefix=settings.api_prefix)
    application.include_router(loops.router, prefix=settings.api_prefix)
    application.include_router(evidence.router, prefix=settings.api_prefix)
    application.include_router(review.router, prefix=settings.api_prefix)
    application.include_router(audit.router, prefix=settings.api_prefix)
    application.include_router(handoff.router, prefix=settings.api_prefix)
    application.include_router(trace.router, prefix=settings.api_prefix)
    application.include_router(agentarts_tools.router, prefix=settings.api_prefix)

    @application.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        """A contract violation surfaces as 422, not a 500."""
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc), "code": "contract_violation"},
        )

    return application


#: The application imported by ``uvicorn apps.api.app.main:app``.
app = create_app()

# Re-exported so ``create_app(event_publisher=NoopEventPublisher())`` reads
# naturally in tests and scripts.
__all__ += ["NoopEventPublisher"]
