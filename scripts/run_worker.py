"""Run the Redis-backed ClinLoop Worker against synthetic events."""

from __future__ import annotations

import argparse
import time

import redis

from apps.api.app.db import build_engine, session_scope
from apps.api.app.settings import get_settings
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.bus import RedisStreamEventBus
from apps.worker.worker.providers import build_model_provider
from apps.worker.worker.service import process_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--count", type=int, default=10, help="maximum events per poll")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.event_bus.lower() != "redis":
        parser.error("EVENT_BUS=redis is required for the Worker")
    if args.count < 1:
        parser.error("--count must be positive")

    bus = RedisStreamEventBus(redis.Redis.from_url(settings.redis_url))
    engine = build_engine()
    agent = WorkflowAgent(provider=build_model_provider(settings))
    try:
        while True:
            messages = bus.consume_messages(count=args.count)
            if not messages:
                if args.once:
                    return 0
                time.sleep(1)
                continue
            for message in messages:
                with session_scope(engine) as session:
                    process_event(session, agent, message.event)
                bus.ack(message)
            if args.once:
                return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
