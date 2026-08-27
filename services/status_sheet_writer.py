"""Безпечний пакетний запис лише статусу й дати в Orders за ТТН."""
from __future__ import annotations

from dataclasses import dataclass

import gspread

from core.order_identity import order_ttn_match_keys, resolve_order_ttn_rows


CANARY_STATUS_COLUMNS = frozenset({"Статус", "Дата"})


@dataclass(frozen=True)
class PreparedStatusBatch:
    batch: tuple[dict, ...] = ()
    row_count: int = 0
    ttns: tuple[str, ...] = ()


class OrdersStatusBatchWriter:
    """Спочатку повна перевірка пакета, потім один batch_update."""

    def __init__(self, worksheet):
        self.worksheet = worksheet

    def prepare(self, updates: list[tuple[str, dict]]) -> tuple[PreparedStatusBatch, str]:
        normalized: list[tuple[str, dict]] = []
        seen_keys: list[frozenset[str]] = []
        for raw_ttn, raw_changes in updates or []:
            ttn = str(raw_ttn or "").strip()
            keys = order_ttn_match_keys(ttn)
            if not keys:
                return PreparedStatusBatch(), "Порожня або некоректна ТТН."
            if any(keys & existing for existing in seen_keys):
                return PreparedStatusBatch(), f"ТТН {ttn} повторюється у пакеті."
            seen_keys.append(keys)

            changes = {
                str(column or "").strip(): value
                for column, value in (raw_changes or {}).items()
                if str(column or "").strip()
            }
            forbidden = sorted(set(changes) - CANARY_STATUS_COLUMNS)
            if forbidden:
                return (
                    PreparedStatusBatch(),
                    "Canary забороняє колонки: " + ", ".join(forbidden),
                )
            if changes:
                normalized.append((ttn, changes))

        if not normalized:
            return PreparedStatusBatch(), ""

        headers_raw = [str(value or "").strip() for value in self.worksheet.row_values(1)]
        if headers_raw.count("ТТН") != 1:
            return PreparedStatusBatch(), "У Orders має бути рівно одна колонка «ТТН»."
        needed_columns = {column for _, changes in normalized for column in changes}
        ambiguous = sorted(column for column in needed_columns if headers_raw.count(column) != 1)
        if ambiguous:
            return (
                PreparedStatusBatch(),
                "У Orders відсутні або дублюються колонки: " + ", ".join(ambiguous),
            )

        headers = {value: index for index, value in enumerate(headers_raw, start=1) if value}
        ttn_values = self.worksheet.col_values(headers["ТТН"])
        labels = [ttn for ttn, _ in normalized]
        resolved, error = resolve_order_ttn_rows(ttn_values, labels, header_rows=1)
        if error:
            return PreparedStatusBatch(), error

        batch: list[dict] = []
        for ttn, changes in normalized:
            row_number = resolved[ttn]
            for column, value in changes.items():
                batch.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(row_number, headers[column]),
                        "values": [["" if value is None else str(value)]],
                    }
                )
        return (
            PreparedStatusBatch(
                batch=tuple(batch),
                row_count=len(normalized),
                ttns=tuple(labels),
            ),
            "",
        )

    def apply_prepared(self, prepared: PreparedStatusBatch) -> tuple[int, str]:
        if not prepared.batch:
            return 0, ""
        try:
            self.worksheet.batch_update(
                list(prepared.batch),
                value_input_option="USER_ENTERED",
            )
            return prepared.row_count, ""
        except Exception as exc:
            return 0, f"Помилка пакетного оновлення Orders: {exc}"
