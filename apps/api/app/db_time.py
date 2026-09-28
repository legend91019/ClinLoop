"""Datetime helpers for the persistence boundary.

SQLite has no native timezone-aware datetime type: values written as
``datetime(..., tzinfo=utc)`` come back naive. PostgreSQL 16 with
``TIMESTAMPTZ`` preserves the offset.

The contracts deliberately reject naive datetimes so an ambiguous
clinical timeline can never be persisted. That means the *repository*
must normalise on the way out: any naive value read from the database is
interpreted as UTC (which is how ClinLoop always writes it).
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["as_utc", "as_utc_optional"]


def as_utc(value: datetime | None) -> datetime:
    """Return ``value`` as a timezone-aware UTC datetime.

    Naive values are assumed to be UTC — the only convention this system
    ever writes.
    """
    if value is None:
        raise ValueError("as_utc() requires a datetime, got None; use as_utc_optional()")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def as_utc_optional(value: datetime | None) -> datetime | None:
    """Like :func:`as_utc` but tolerates ``None``."""
    return None if value is None else as_utc(value)
