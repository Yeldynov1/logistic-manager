"""Безпечний пакетний запис лише статусу й дати в Orders за ТТН."""
from __future__ import annotations

from dataclasses import dataclass
import time

import gspread

from core.order_identity import order_ttn_match_keys, resolve_order_ttn_rows


CANARY_STATUS_COLUMNS = frozenset({"Статус", "Дата"})
_TRANSIENT_GOOGLE_CODES = frozenset({429, 500, 502, 503, 504})


def _google_error_status_code(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    for value in (
        getattr(response, "status_code", None),
        getattr(exc, "status_code", None),
        getattr(exc, "code", None),
    ):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _is_transient_google_error(exc: Exception) -> bool:
    if _google_error_status_code(exc) in _TRANSIENT_GOOGLE_CODES:
        return True
    name = type(exc).__name__.casefold()
    message = str(exc or "").casefold()
    return (
        "timeout" in name
        or "connectionerror" in name
        or "timed out" in message
        or "temporarily unavailable" in message
        or "connection reset" in message
    )


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

    def apply_prepared(
        self,
        prepared: PreparedStatusBatch,
        *,
        attempts: int = 3,
        sleep_fn=time.sleep,
    ) -> tuple[int, str]:
        if not prepared.batch:
            return 0, ""
        total_attempts = max(1, int(attempts))
        for attempt in range(1, total_attempts + 1):
            try:
                self.worksheet.batch_update(
                    list(prepared.batch),
                    value_input_option="USER_ENTERED",
                )
                return prepared.row_count, ""
            except Exception as exc:
                if attempt >= total_attempts or not _is_transient_google_error(exc):
                    return 0, f"Помилка пакетного оновлення Orders: {exc}"
                sleep_fn(attempt)
        return 0, "Помилка пакетного оновлення Orders."
