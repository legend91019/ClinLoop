"""FastAPI dependencies and the replaceable event publisher port.

Two ideas live here:

1. ``get_session`` — the request-scoped database session. Routes depend on
   this and never construct an engine themselves.
2. ``EventPublisher`` — the seam between ingest and the worker. The
   foundation ships a no-op/Redis implementation; task 5 swaps in the real
   ``RedisStreamEventBus`` without touching the routes.

Routes never return SQLAlchemy objects — see :mod:`packages.contracts.api`
for the DTOs they return instead.
"""

from __future__ import annotations

from typing import Annotated, Protocol, runtime_checkable

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.app.db import get_session
from apps.api.app.settings import get_settings
from apps.worker.worker.bus import RedisStreamEventBus
from packages.contracts import ActorRef, ClinicalEvent

__all__ = [
    "SessionDep",
    "EventPublisher",
    "NoopEventPublisher",
    "InMemoryEventPublisher",
    "get_event_publisher",
    "EventPublisherDep",
    "get_actor",
    "ActorDep",
    "or_404",
]


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

SessionDep = Annotated[Session, Depends(get_session)]


# ---------------------------------------------------------------------------
# Event publisher port
# ---------------------------------------------------------------------------


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes an ingested event onto the workflow event bus.

    The foundation deliberately keeps this abstract: the worker (task 5)
    binds the Redis Streams implementation. Nothing about the HTTP
    contract changes when it does.
    """

    def publish(self, event: ClinicalEvent) -> str:
        """Publish ``event`` and return its ``event_id``."""
        ...


class NoopEventPublisher:
    """Accepts events and discards them.

    Used when no worker is running (local API-only development, the
    foundation test suite). Ingest is still durable in PostgreSQL — this
    only controls whether a worker is woken.
    """

    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, event: ClinicalEvent) -> str:
        self.published.append(event.event_id)
        return event.event_id


class InMemoryEventPublisher:
    """Ordered in-process queue. The contract for :class:`EventPublisher`."""

    def __init__(self) -> None:
        self.events: list[ClinicalEvent] = []

    def publish(self, event: ClinicalEvent) -> str:
        self.events.append(event)
        return event.event_id

    def drain(self) -> list[ClinicalEvent]:
        drained, self.events = self.events, []
        return drained


class RedisEventPublisher:
    """API publisher backed by the same Redis Stream as the Worker."""

    def __init__(self, bus: RedisStreamEventBus) -> None:
        self.bus = bus

    def publish(self, event: ClinicalEvent) -> str:
        return self.bus.publish(event)


def get_event_publisher() -> EventPublisher:
    """FastAPI dependency returning the active publisher.

    Overridable via ``app.dependency_overrides`` in tests, or by
    ``create_app(event_publisher=...)``.
    """
    settings = get_settings()
    if settings.event_bus.strip().lower() != "redis":
        return _DEFAULT_PUBLISHER
    import redis

    client = redis.Redis.from_url(settings.redis_url)
    return RedisEventPublisher(RedisStreamEventBus(client))


_DEFAULT_PUBLISHER: EventPublisher = NoopEventPublisher()

EventPublisherDep = Annotated[EventPublisher, Depends(get_event_publisher)]


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------


def get_actor(
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
) -> ActorRef:
    """Resolve the acting user from request headers.

    Synthetic default keeps local development and tests frictionless; a
    real deployment supplies the identity at the gateway.
    """
    return ActorRef(
        actor_id=x_actor_id or "DR-001",
        role=x_actor_role or "PHYSICIAN",
        display_name=None,
    )


ActorDep = Annotated[ActorRef, Depends(get_actor)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def or_404(value, *, detail: str):  # type: ignore[no-untyped-def]
    """Return ``value`` or raise a structured 404."""
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return value
