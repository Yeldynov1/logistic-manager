"""Безпечне доповнення порожніх номерів накладних із журналу Укрпошти."""
from __future__ import annotations

import re

import pandas as pd

import utils
from core.order_identity import order_ttn_match_keys


_BLOCKED_DESCRIPTION_PARTS = (
    "імпорт із трекінгу",
    "импорт из трекинга",
    "повний доступ обмежено",
    "немає даних",
    "не знайдено",
)
_INVOICE_PATTERN = re.compile(r"[0-9A-Za-zА-Яа-яІіЇїЄє._/#№-]+")


def up_invoice_candidate(value, shipment_ttn="") -> str:
    """Повернути лише схожий на номер накладної короткий опис УП."""
    invoice = utils.normalize_invoice_number(value)
    if not invoice or len(invoice) > 80 or not any(ch.isdigit() for ch in invoice):
        return ""
    lowered = invoice.casefold()
    if any(part in lowered for part in _BLOCKED_DESCRIPTION_PARTS):
        return ""
    if not _INVOICE_PATTERN.fullmatch(invoice):
        return ""
    if shipment_ttn and (
        order_ttn_match_keys(invoice) & order_ttn_match_keys(shipment_ttn)
    ):
        return ""
    return invoice


def plan_missing_up_invoice_updates(
    orders_df: pd.DataFrame,
    up_shipments_df: pd.DataFrame,
) -> list[tuple[str, str]]:
    """Пари (ТТН, номер) лише для порожніх Orders і однозначного ШКІ журналу."""
    if (
        orders_df is None
        or orders_df.empty
        or up_shipments_df is None
        or up_shipments_df.empty
        or "ТТН" not in orders_df.columns
        or "Номер накладної" not in orders_df.columns
        or "ШКІ" not in up_shipments_df.columns
        or "Дод. інфо" not in up_shipments_df.columns
    ):
        return []

    journal_candidates: dict[str, set[str]] = {}
    for _, row in up_shipments_df.iterrows():
        candidate = up_invoice_candidate(
            row.get("Дод. інфо", ""),
            row.get("ШКІ", ""),
        )
        if not candidate:
            continue
        for key in order_ttn_match_keys(row.get("ШКІ", "")):
            journal_candidates.setdefault(key, set()).add(candidate)

    blank_orders: list[tuple[str, frozenset[str]]] = []
    for _, row in orders_df.iterrows():
        if utils.normalize_invoice_number(row.get("Номер накладної", "")):
            continue
        raw_ttn = str(row.get("ТТН", "") or "").strip()
        keys = order_ttn_match_keys(raw_ttn)
        if not keys:
            continue
        blank_orders.append((raw_ttn, keys))

    key_counts: dict[str, int] = {}
    for _, keys in blank_orders:
        for key in keys:
            key_counts[key] = key_counts.get(key, 0) + 1

    planned: list[tuple[str, str]] = []
    for raw_ttn, keys in blank_orders:
        # Дубль ТТН у Orders не можна оновлювати: невідомо, який рядок правильний.
        if any(key_counts.get(key, 0) > 1 for key in keys):
            continue
        candidates: set[str] = set()
        for key in keys:
            candidates.update(journal_candidates.get(key, set()))
        if len(candidates) == 1:
            planned.append((raw_ttn, next(iter(candidates))))
    return planned


def merge_missing_invoice_fields(
    local_df: pd.DataFrame,
    remote_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Підтягнути з актуального Orders лише порожні локальні номери накладних."""
    if local_df is None:
        local_df = pd.DataFrame()
    result = local_df.copy()
    if (
        result.empty
        or remote_df is None
        or remote_df.empty
        or "ТТН" not in result.columns
        or "ТТН" not in remote_df.columns
        or "Номер накладної" not in remote_df.columns
    ):
        return result, 0
    if "Номер накладної" not in result.columns:
        result["Номер накладної"] = ""

    remote_keys: dict[str, set[int]] = {}
    for position, value in enumerate(remote_df["ТТН"].tolist()):
        for key in order_ttn_match_keys(value):
            remote_keys.setdefault(key, set()).add(position)

    changed = 0
    invoice_col = result.columns.get_loc("Номер накладної")
    for position, value in enumerate(result["ТТН"].tolist()):
        if utils.normalize_invoice_number(result.iat[position, invoice_col]):
            continue
        matches: set[int] = set()
        for key in order_ttn_match_keys(value):
            matches.update(remote_keys.get(key, set()))
        if len(matches) != 1:
            continue
        invoice = up_invoice_candidate(
            remote_df.iloc[next(iter(matches))].get("Номер накладної", "")
        )
        if invoice:
            result.iat[position, invoice_col] = invoice
            changed += 1
    return result, changed
