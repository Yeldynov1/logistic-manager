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


def manager_auto_refresh_is_effectively_enabled(ar: dict, *, now: datetime) -> bool:
    """ВКЛ лише поки відкрита вкладка регулярно залишає heartbeat."""
    if not ar.get("enabled"):
        return False

    heartbeat = parse_saved_time(ar.get("last_cycle_at", ""))
    switched_at = parse_saved_time(ar.get("updated_at", ""))
    latest_signal = max(
        (value for value in (heartbeat, switched_at) if value is not None),
        default=None,
    )
    if latest_signal is None:
        return False
    age_seconds = max(0.0, (now - latest_signal).total_seconds())
    return age_seconds <= HEARTBEAT_STALE_SECONDS


def manager_auto_refresh_activity(ar: dict, *, now: datetime) -> str:
    """Людський стан: працює, очікує цикл, неактивний або вимкнений."""
    enabled = ar.get("enabled")
    if enabled is None:
        return "менеджер ще не перемикав"
    if not enabled:
        return "вимкнено"
    heartbeat = parse_saved_time(ar.get("last_cycle_at", ""))
    switched_at = parse_saved_time(ar.get("updated_at", ""))
    if heartbeat is None and switched_at is not None:
        age_seconds = max(0.0, (now - switched_at).total_seconds())
        if age_seconds > HEARTBEAT_STALE_SECONDS:
            return "вимкнено — вкладка менеджера неактивна"
        return "увімкнено, очікується перший цикл"
    if manager_auto_refresh_is_effectively_enabled(ar, now=now):
        return "працює зараз"
    return "вимкнено — вкладка менеджера неактивна"
