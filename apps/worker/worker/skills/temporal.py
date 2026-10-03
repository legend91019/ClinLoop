from __future__ import annotations

from datetime import UTC, datetime, timedelta


def parse_time_window(
    text: str, *, now: datetime | None = None
) -> tuple[datetime, datetime] | None:
    base = now or datetime.now(UTC)
    if "今天" in text:
        start = base.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if "今晚" in text:
        start = base.replace(hour=18, minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=6)
    if "明日" in text or "明天" in text:
        start = (base + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    return None
