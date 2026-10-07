from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.db_models import EventPublicationRow
from apps.api.app.dependencies import get_event_publisher
from apps.api.app.main import app
from apps.worker.worker.service import publish_pending_events
from tests.api.test_events import event_payload


def test_redis_outage_keeps_event_pending_for_worker_recovery(client, api_engine) -> None:
    class FailingPublisher:
        def publish(self, event):
            raise OSError("synthetic Redis outage")

    app.dependency_overrides[get_event_publisher] = lambda: FailingPublisher()
    try:
        response = client.post("/api/v1/events", json=event_payload(event_id="EVT-OUTBOX-RECOVERY"))
    finally:
        app.dependency_overrides.pop(get_event_publisher, None)

    assert response.status_code == 202
    with Session(api_engine) as session:
        pending = session.get(EventPublicationRow, "EVT-OUTBOX-RECOVERY")
        assert pending is not None and pending.published_at is None

        class RecordingBus:
            def __init__(self):
                self.events = []

            def publish(self, event):
                self.events.append(event.event_id)

        bus = RecordingBus()
        assert publish_pending_events(session, bus) == 1
        session.commit()
        assert bus.events == ["EVT-OUTBOX-RECOVERY"]
        assert session.get(EventPublicationRow, "EVT-OUTBOX-RECOVERY").published_at


def test_api_only_noop_keeps_event_available_for_later_worker(client, api_engine) -> None:
    response = client.post("/api/v1/events", json=event_payload(event_id="EVT-OUTBOX-NOOP"))

    assert response.status_code == 202
    with Session(api_engine) as session:
        publication = session.get(EventPublicationRow, "EVT-OUTBOX-NOOP")
        assert publication is not None and publication.published_at is None
