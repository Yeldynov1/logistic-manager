"""Чисті правила відображення активності авто-пошуку."""
from __future__ import annotations

from datetime import datetime


HEARTBEAT_STALE_SECONDS = 12 * 60


def parse_saved_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def display_saved_time(value: str) -> str:
    parsed = parse_saved_time(value)
    return parsed.strftime("%d.%m.%Y %H:%M") if parsed else "—"


def manager_auto_refresh_activity(ar: dict, *, now: datetime) -> str:
    """Людський стан: працює, очікує цикл, неактивний або вимкнений."""
    enabled = ar.get("enabled")
    if enabled is None:
        return "менеджер ще не перемикав"
    if not enabled:
        return "вимкнено"
    heartbeat = parse_saved_time(ar.get("last_cycle_at", ""))
    if heartbeat is None:
        return "увімкнено, очікується перший цикл"
    age_seconds = max(0.0, (now - heartbeat).total_seconds())
    if age_seconds <= HEARTBEAT_STALE_SECONDS:
        return "працює зараз"
    return "увімкнено, але вкладка менеджера неактивна"
