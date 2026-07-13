from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def now_taipei_iso() -> str:
    return now_taipei().replace(tzinfo=None).isoformat(timespec="seconds")


def to_taipei(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(TAIPEI_TZ)
    if parsed.date() < datetime(2026, 7, 13).date():
        return parsed.replace(tzinfo=ZoneInfo("UTC")).astimezone(TAIPEI_TZ)
    return parsed
