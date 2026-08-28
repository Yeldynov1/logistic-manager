"""Злиття готових фонових статусів у локальну таблицю Streamlit."""
from __future__ import annotations

import pandas as pd

from core.order_identity import order_ttn_match_keys


STATUS_SYNC_FIELDS = ("Статус", "Дата")


def _text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none"} else text


def merge_status_fields(
    local_df: pd.DataFrame,
    remote_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Оновити лише ``Статус``/``Дата`` за однозначною ТТН.

    Інші локальні поля не замінюються. Дубльовані або неоднозначні ТТН
    пропускаються, щоб автоматична синхронізація не торкнулася чужого рядка.
    """
    if local_df is None:
        local_df = pd.DataFrame()
    result = local_df.copy()
    if (
        result.empty
        or remote_df is None
        or remote_df.empty
        or "ТТН" not in result.columns
        or "ТТН" not in remote_df.columns
    ):
        return result, 0

    for field in STATUS_SYNC_FIELDS:
        if field not in result.columns:
            result[field] = ""

    remote_keys: dict[str, set[int]] = {}
    for remote_position, value in enumerate(remote_df["ТТН"].tolist()):
        for key in order_ttn_match_keys(value):
            remote_keys.setdefault(key, set()).add(remote_position)

    changed_rows = 0
    for local_position, value in enumerate(result["ТТН"].tolist()):
        matches: set[int] = set()
        for key in order_ttn_match_keys(value):
            matches.update(remote_keys.get(key, set()))
        if len(matches) != 1:
            continue
        remote_row = remote_df.iloc[next(iter(matches))]
        row_changed = False
        for field in STATUS_SYNC_FIELDS:
            if field not in remote_df.columns:
                continue
            remote_value = _text(remote_row.get(field, ""))
            column_position = result.columns.get_loc(field)
            current_value = result.iat[local_position, column_position]
            if not remote_value or remote_value == _text(current_value):
                continue
            result.iat[local_position, column_position] = remote_value
            row_changed = True
        if row_changed:
            changed_rows += 1
    return result, changed_rows


def drop_completed_receipt_rows(
    local_df: pd.DataFrame,
    completed_ttns,
) -> tuple[pd.DataFrame, int]:
    """Прибрати з відкритої сесії ТТН, чию TurboSMS уже зафіксовано в аудиті."""
    if local_df is None:
        return pd.DataFrame(), 0
    result = local_df.copy()
    if result.empty or "ТТН" not in result.columns:
        return result, 0
    completed_keys = {
        key
        for ttn in completed_ttns or ()
        for key in order_ttn_match_keys(ttn)
    }
    if not completed_keys:
        return result, 0
    keep = [
        not bool(order_ttn_match_keys(value) & completed_keys)
        for value in result["ТТН"].tolist()
    ]
    removed = len(result) - sum(keep)
    return result.loc[keep].reset_index(drop=True), removed
