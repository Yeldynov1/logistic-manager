"""Чисті правила інтервалу автооновлення без залежності від Streamlit."""
from __future__ import annotations


AUTO_CYCLE_INTERVAL_SECONDS = 5 * 60


def auto_cycle_is_due(last_run, now) -> bool:
    """Чи настав час нового циклу; некоректний або майбутній час не блокує запуск."""
    try:
        last_value = float(last_run or 0)
        now_value = float(now)
    except (TypeError, ValueError):
        return True
    if last_value <= 0 or now_value < last_value:
        return True
    return now_value - last_value >= AUTO_CYCLE_INTERVAL_SECONDS
