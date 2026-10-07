"""Clinical event ingest and patient timeline endpoints.

Ingest is **idempotent on ``event_id``**:

* new event      -> ``202 Accepted``
* known event_id -> ``409 Conflict`` (the first ingest is never rewritten)
* invalid body   -> ``422 Unprocessable Entity``

The route persists the event, hands it to the :class:`EventPublisher`
port, and returns. It does not run the agent — that is the worker's job
(task 6).
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.db_models import EventPublicationRow
from apps.api.app.db_time import as_utc
from apps.api.app.dependencies import EventPublisherDep, NoopEventPublisher, SessionDep
from apps.api.app.repositories import ClinicalEventRepository
from packages.contracts import (
    ClinicalEvent,
    EventAcceptedResponse,
    TimelineEntry,
    TimelineResponse,
    utcnow,
)

__all__ = ["router", "MAX_TIMELINE_HOURS"]

router = APIRouter(tags=["events"])
logger = logging.getLogger(__name__)

#: Upper bound on the timeline look-back window (30 days).
MAX_TIMELINE_HOURS = 24 * 30


@router.post(
    "/events",
    response_model=EventAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a clinical event",
    responses={
        409: {"description": "An event with this event_id was already ingested"},
        422: {"description": "The event payload violates the contract"},
    },
)
def ingest_event(
    event: ClinicalEvent,
    session: SessionDep,
    publisher: EventPublisherDep,
) -> EventAcceptedResponse:
    """Persist a clinical event and publish it for the workflow worker.

    The event is stored before it is published so a worker crash cannot
    lose it; a re-delivery of the same ``event_id`` is rejected with 409
    rather than silently double-counted.
    """
    repo = ClinicalEventRepository(session)

    if repo.exists(event.event_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"event_id {event.event_id} has already been ingested",
        )

    try:
        repo.add(event)
        session.add(EventPublicationRow(event_id=event.event_id, payload={}))
        session.commit()
    except ValueError as exc:  # duplicate slipped through a race
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not isinstance(publisher, NoopEventPublisher):
        try:
            publisher.publish(event)
            publication = session.get(EventPublicationRow, event.event_id)
            publication.published_at = utcnow()
            publication.attempts += 1
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("event %s remains queued for publication recovery", event.event_id)

    return EventAcceptedResponse(event_id=event.event_id, accepted=True, duplicate=False)


@router.get(
    "/patients/{patient_id}/timeline",
    response_model=TimelineResponse,
    summary="Patient event timeline",
)
def patient_timeline(
    patient_id: str,
    session: SessionDep,
    hours: Annotated[int, Query(ge=1, le=MAX_TIMELINE_HOURS)] = 24,
) -> TimelineResponse:
    """Return the patient's events from the last ``hours``, oldest first.

    An unknown patient is not an error — it is an empty timeline, which
    the console renders as an empty state.
    """
    reference = utcnow()
    events = ClinicalEventRepository(session).timeline(patient_id, hours=hours, now=reference)

    entries = [
        TimelineEntry(
            event_id=event.event_id,
            event_type=event.event_type,
            event_time=as_utc(event.event_time),
            source_time=as_utc(event.source_time),
            actor=event.actor,
            payload_ref=event.payload_ref,
        )
        for event in events
    ]

    from datetime import timedelta

    return TimelineResponse(
        patient_id=patient_id,
        hours=hours,
        window_start=reference - timedelta(hours=hours),
        window_end=reference,
        count=len(entries),
        entries=entries,
    )
