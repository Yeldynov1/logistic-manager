"""Безпечний точковий запис лише порожніх номерів накладних у Orders."""
from __future__ import annotations

from dataclasses import dataclass
import time

import gspread

import utils
from core.order_identity import order_ttn_match_keys, resolve_order_ttn_rows
from services.status_sheet_writer import _is_transient_google_error


@dataclass(frozen=True)
class PreparedInvoiceBatch:
    batch: tuple[dict, ...] = ()
    row_count: int = 0
    ttns: tuple[str, ...] = ()


class OrdersMissingInvoiceWriter:
    """Перевірити весь пакет, потім заповнити лише порожні комірки."""

    def __init__(self, worksheet):
        self.worksheet = worksheet

    def prepare(
        self,
        updates: list[tuple[str, str]],
    ) -> tuple[PreparedInvoiceBatch, str]:
        normalized: list[tuple[str, str]] = []
        seen_keys: list[frozenset[str]] = []
        for raw_ttn, raw_invoice in updates or []:
            ttn = str(raw_ttn or "").strip()
            keys = order_ttn_match_keys(ttn)
            invoice = utils.normalize_invoice_number(raw_invoice)
            if not keys or not invoice:
                continue
            if any(keys & existing for existing in seen_keys):
                return PreparedInvoiceBatch(), f"ТТН {ttn} повторюється у пакеті."
            seen_keys.append(keys)
            normalized.append((ttn, invoice))
        if not normalized:
            return PreparedInvoiceBatch(), ""

        headers_raw = [
            str(value or "").strip() for value in self.worksheet.row_values(1)
        ]
        required = ("ТТН", "Номер накладної")
        ambiguous = [name for name in required if headers_raw.count(name) != 1]
        if ambiguous:
            return (
                PreparedInvoiceBatch(),
                "У Orders відсутні або дублюються колонки: "
                + ", ".join(ambiguous),
            )
        headers = {
            value: index for index, value in enumerate(headers_raw, start=1) if value
        }
        resolved, error = resolve_order_ttn_rows(
            self.worksheet.col_values(headers["ТТН"]),
            [ttn for ttn, _ in normalized],
            header_rows=1,
        )
        if error:
            return PreparedInvoiceBatch(), error

        invoice_col = headers["Номер накладної"]
        current_values = self.worksheet.col_values(invoice_col)
        batch: list[dict] = []
        labels: list[str] = []
        for ttn, invoice in normalized:
            row_number = resolved[ttn]
            current = (
                current_values[row_number - 1]
                if row_number - 1 < len(current_values)
                else ""
            )
            if utils.normalize_invoice_number(current):
                continue
            batch.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_number, invoice_col),
                    "values": [[invoice]],
                }
            )
            labels.append(ttn)
        return (
            PreparedInvoiceBatch(
                batch=tuple(batch),
                row_count=len(labels),
                ttns=tuple(labels),
            ),
            "",
        )

    def apply_prepared(
        self,
        prepared: PreparedInvoiceBatch,
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
                    value_input_option="RAW",
                )
                return prepared.row_count, ""
            except Exception as exc:
                if attempt >= total_attempts or not _is_transient_google_error(exc):
                    return 0, f"Помилка доповнення номерів накладних: {exc}"
                sleep_fn(attempt)
        return 0, "Помилка доповнення номерів накладних."
