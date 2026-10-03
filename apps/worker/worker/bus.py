"""Event bus implementations used by the workflow worker."""
from __future__ import annotations

import json
from collections import deque
from typing import Any

from packages.contracts import ClinicalEvent


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: deque[ClinicalEvent] = deque()
        self._seen: set[str] = set()

    def publish(self, event: ClinicalEvent) -> str:
        if event.event_id not in self._seen:
            self._events.append(event)
            self._seen.add(event.event_id)
        return event.event_id

    def consume(self, consumer_group: str = "clinloop-workers", count: int = 10) -> list[ClinicalEvent]:
        del consumer_group
        result: list[ClinicalEvent] = []
        for _ in range(max(0, count)):
            if not self._events:
                break
            result.append(self._events.popleft())
        return result


class RedisStreamEventBus:
    """Redis Streams adapter; construction is lazy so local tests need no Redis."""
    def __init__(self, redis_client: Any, *, stream: str = "clinloop.events") -> None:
        self.redis = redis_client
        self.stream = stream

    def publish(self, event: ClinicalEvent) -> str:
        self.redis.xadd(self.stream, {"event": event.model_dump_json()}, id="*")
        return event.event_id

    def consume(self, consumer_group: str = "clinloop-workers", count: int = 10) -> list[ClinicalEvent]:
        try:
            self.redis.xgroup_create(self.stream, consumer_group, id="0", mkstream=True)
        except Exception:
            pass
        rows = self.redis.xreadgroup(consumer_group, "clinloop-worker", {self.stream: ">"}, count=count, block=1)
        events: list[ClinicalEvent] = []
        for _stream, messages in rows:
            for message_id, fields in messages:
                raw = fields.get(b"event", fields.get("event"))
                event = ClinicalEvent.model_validate_json(raw.decode() if isinstance(raw, bytes) else raw)
                events.append(event)
                self.redis.xack(self.stream, consumer_group, message_id)
        return events


EventBus = InMemoryEventBus | RedisStreamEventBus
