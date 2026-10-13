"""Правила відмови від чеків для нових замовлень."""
from __future__ import annotations

import pandas as pd

import utils


def mark_created_orders_no_receipt(df: pd.DataFrame, update_order) -> tuple[int, list[str]]:
    """Точково позначити поточні рядки зі статусом «Створено» без чека."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return 0, []
    required = {"ТТН", "Статус", "Статус СМС"}
    if not required.issubset(df.columns):
        return 0, []

    updated = 0
    errors: list[str] = []
    for idx, row in df.iterrows():
        status = str(row.get("Статус", "") or "").strip().casefold()
        sms_status = str(row.get("Статус СМС", "") or "").strip()
        if status != "створено" or utils.sms_status_is_done(sms_status):
            continue
        ttn = str(row.get("ТТН", "") or "").strip()
        if not ttn:
            errors.append("Рядок зі статусом «Створено» не має ТТН.")
            continue
        saved, error = update_order(
            ttn,
            {"Статус СМС": utils.SMS_STATUS_NOT_REQUIRED},
            silent=True,
        )
        if not saved:
            errors.append(error or f"Не вдалося оновити ТТН {ttn}.")
            continue
        df.at[idx, "Статус СМС"] = utils.SMS_STATUS_NOT_REQUIRED
        updated += 1
    return updated, errors
