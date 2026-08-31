#!/usr/bin/env python3
"""Фонове доповнення порожніх номерів накладних УП без SMS і видалень."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.up_invoice_sync import plan_missing_up_invoice_updates  # noqa: E402
from scripts.status_dry_run import (  # noqa: E402
    _google_client_from_environment,
    _mask_ttn,
    _read_google_worksheet_rows,
)
from services.up_invoice_sheet_writer import OrdersMissingInvoiceWriter  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Звірити Orders і UP_Shipments за ТТН та доповнити порожні номери."
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    return parser


def _load_context():
    client = _google_client_from_environment()
    if client is None:
        raise RuntimeError("Немає GCP_SERVICE_ACCOUNT_TOML або GCP_SERVICE_ACCOUNT_JSON")
    workbook = str(os.environ.get("ORDERS_SPREADSHEET_NAME", "Orders") or "Orders")
    spreadsheet = client.open(workbook)
    return spreadsheet.sheet1, spreadsheet.worksheet("UP_Shipments")


def main(argv=None, *, load_context=None) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 50:
        print("Помилка: --limit має бути від 1 до 50.")
        return 2
    expected = f"FILL-UP-INVOICES-{args.limit}"
    if args.apply and args.confirmation != expected:
        print("Помилка: запис заблоковано — немає точного підтвердження.")
        return 2
    loader = load_context or _load_context
    try:
        orders_ws, journal_ws = loader()
        orders = pd.DataFrame(_read_google_worksheet_rows(orders_ws) or [])
        journal = pd.DataFrame(_read_google_worksheet_rows(journal_ws) or [])
    except Exception as exc:
        print(f"Не вдалося прочитати таблиці: {exc}")
        return 1

    planned = plan_missing_up_invoice_updates(orders, journal)[: args.limit]
    writer = OrdersMissingInvoiceWriter(orders_ws)
    prepared, error = writer.prepare(planned)
    if error:
        print(f"Звірку скасовано: {error}")
        return 1
    print(
        f"{'APPLY' if args.apply else 'PREVIEW'}: "
        f"підготовлено {prepared.row_count} порожніх номерів накладних."
    )
    for ttn in prepared.ttns:
        print(f"- УП {_mask_ttn(ttn)}")
    if not args.apply:
        return 0
    written, write_error = writer.apply_prepared(prepared)
    if write_error:
        print(write_error)
        return 1
    print(f"Записано номерів накладних: {written}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
