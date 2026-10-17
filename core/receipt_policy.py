"""Правила відмови від чеків для нових замовлень."""
from __future__ import annotations

import pandas as pd

import utils


def _row_created_day(row):
    """Дата створення рядка: внутрішня Supabase-дата або видима «Дата»."""
    for key in ("_created_at_raw", "Дата"):
        raw = row.get(key, "") if hasattr(row, "get") else ""
        if raw is None or not str(raw).strip():
            continue
        text = str(raw).strip()
        iso_order = len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-"
        parsed = pd.to_datetime(
            text,
            dayfirst=not iso_order,
            errors="coerce",
        )
        if not pd.isna(parsed):
            if getattr(parsed, "tzinfo", None) is not None:
                parsed = parsed.tz_convert("Europe/Kyiv")
            return parsed.date()
    return None


def mark_np_orders_no_receipt_from_cutoff(
    df: pd.DataFrame,
    update_order,
) -> tuple[int, list[str]]:
    """Позначити НП від 13.10.2026, якщо чек ще не був виданий."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return 0, []
    required = {"ТТН", "Служба", "Дата", "Статус СМС"}
    if not required.issubset(df.columns):
        return 0, []

    updated = 0
    errors: list[str] = []
    for idx, row in df.iterrows():
        if not utils.row_is_np(row):
            continue
        sms_status = str(row.get("Статус СМС", "") or "").strip()
        if utils.sms_status_is_done(sms_status):
            continue
        created_day = _row_created_day(row)
        if (
            created_day is None
            or created_day < utils.RECEIPT_DISABLED_FOR_NEW_ORDERS_FROM
        ):
            continue
        ttn = str(row.get("ТТН", "") or "").strip()
        if not ttn:
            errors.append("Рядок НП від 13.10 або пізніше не має ТТН.")
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
