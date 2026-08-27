"""Безпечне зіставлення ТТН з рядками Orders."""
from __future__ import annotations

import re


def order_ttn_match_keys(value) -> frozenset[str]:
    """Варіанти ключа для порівняння ТТН зі збереженим значенням Google Sheets."""
    s = str(value or "").strip().lstrip("'").strip().upper()
    if not s or s in {"NAN", "NONE"}:
        return frozenset()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    compact = re.sub(r"\s+", "", s)
    no_dashes = compact.replace("-", "")
    keys = {compact, no_dashes}
    if no_dashes.isdigit():
        if len(no_dashes) == 12:
            keys.add("0" + no_dashes)
        elif len(no_dashes) == 13 and no_dashes.startswith("0"):
            keys.add(no_dashes[1:])
    return frozenset(k for k in keys if k)


def resolve_order_ttn_rows(
    column_values: list,
    requested_ttns: list,
    *,
    header_rows: int = 1,
) -> tuple[dict[str, int], str]:
    """
    Повернути ``{вхідна_ттн: 1-based_рядок}``.

    Операція скасовується повністю, якщо хоча б одної ТТН немає або вона дублюється.
    """
    entries: list[tuple[str, frozenset[str]]] = []
    for raw in requested_ttns or []:
        label = str(raw or "").strip()
        keys = order_ttn_match_keys(label)
        if not keys:
            return {}, "Порожня або некоректна ТТН."
        if any(keys & existing_keys for _, existing_keys in entries):
            continue
        entries.append((label, keys))
    if not entries:
        return {}, ""

    sheet_rows: list[tuple[int, frozenset[str]]] = []
    for row_number, value in enumerate(column_values or [], start=1):
        if row_number <= max(0, int(header_rows)):
            continue
        keys = order_ttn_match_keys(value)
        if keys:
            sheet_rows.append((row_number, keys))

    resolved: dict[str, int] = {}
    used_rows: set[int] = set()
    for label, requested_keys in entries:
        matches = [
            row_number
            for row_number, row_keys in sheet_rows
            if requested_keys & row_keys
        ]
        if not matches:
            return {}, f"ТТН {label} не знайдено в Orders."
        if len(matches) > 1:
            return {}, f"ТТН {label} дублюється в Orders; операцію скасовано."
        row_number = matches[0]
        if row_number in used_rows:
            return {}, f"Кілька ТТН вказують на один рядок {row_number}; операцію скасовано."
        used_rows.add(row_number)
        resolved[label] = row_number
    return resolved, ""
