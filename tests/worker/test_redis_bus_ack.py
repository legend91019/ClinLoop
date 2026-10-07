from __future__ import annotations

from datetime import UTC, datetime

from apps.worker.worker.bus import RedisStreamEventBus
from packages.contracts import ActorRef, ClinicalEvent, EventType


class FakeRedis:
    def __init__(self, event: ClinicalEvent) -> None:
        self.event = event
        self.acks: list[tuple[str, str | bytes]] = []

    def xgroup_create(self, *args, **kwargs) -> None:
        del args, kwargs

    def xreadgroup(self, *args, **kwargs):
        del args, kwargs
        return [(b"clinloop.events", [(b"1-0", {b"event": self.event.model_dump_json()})])]

    def xack(self, stream: str, group: str, message_id: str | bytes) -> None:
        self.acks.append((f"{stream}:{group}", message_id))


def event() -> ClinicalEvent:
    now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    return ClinicalEvent(
        event_id="EVT-REDIS-1",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.NOTE_CREATED,
        event_time=now,
        source_time=now,
        payload_ref="NOTE-REDIS-1",
        actor=ActorRef(actor_id="DR-TEST", role="PHYSICIAN"),
        payload={"text": "复查血培养"},
    )


def test_worker_ack_is_explicit_after_processing() -> None:
    redis_client = FakeRedis(event())
    bus = RedisStreamEventBus(redis_client)

    messages = bus.consume_messages(count=1)

    assert len(messages) == 1
    assert redis_client.acks == []
    bus.ack(messages[0])
    assert redis_client.acks == [("clinloop.events:clinloop-workers", b"1-0")]


def test_pending_message_can_be_reclaimed_after_worker_restart() -> None:
    class PendingRedis(FakeRedis):
        def xautoclaim(self, stream, group, consumer, min_idle_time, start_id, count):
            assert min_idle_time >= 60_000
            return (
                b"0-0",
                [(b"9-0", {b"event": self.event.model_dump_json()})],
                [],
            )

    redis_client = PendingRedis(event())
    bus = RedisStreamEventBus(redis_client)

    messages = bus.recover_pending_messages(count=1)

    assert len(messages) == 1
    assert messages[0].event.event_id == "EVT-REDIS-1"
    assert redis_client.acks == []
