#!/usr/bin/env python3
"""Canary 1 НП + 1 УП: preview за замовчуванням, без SMS і чеків."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.status_dry_run import (  # noqa: E402
    _google_client_from_environment,
    _mask_ttn,
    _open_google_worksheet,
    _read_google_worksheet_rows,
)
from services.status_sheet_writer import OrdersStatusBatchWriter  # noqa: E402
from services.status_worker import run_status_cycle  # noqa: E402


_CANARY_FIELDS = ("Статус", "Дата")
_APPLY_CONFIRMATION = "WRITE-1-NP-1-UP"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Перевірити або точково записати максимум 1 статус НП і 1 статус УП."
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=5,
        help="Скільки активних ТТН служби перевірити, щоб знайти одну зміну (1–10).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Виконати підготовлений пакетний запис статусу/дати.",
    )
    parser.add_argument(
        "--confirmation",
        default="",
        help="Для --apply потрібне точне значення WRITE-1-NP-1-UP.",
    )
    return parser


def _default_load_context():
    client = _google_client_from_environment()
    if client is None:
        raise RuntimeError("Немає GCP_SERVICE_ACCOUNT_TOML або GCP_SERVICE_ACCOUNT_JSON")
    workbook = str(os.environ.get("ORDERS_SPREADSHEET_NAME", "Orders") or "Orders")
    worksheet = _open_google_worksheet(client, workbook)
    rows = _read_google_worksheet_rows(worksheet)
    return worksheet, list(rows or [])


def main(
    argv=None,
    *,
    load_context=None,
    np_fetch_many=None,
    up_fetch_one=None,
) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.candidate_limit <= 10:
        print("Помилка: --candidate-limit має бути від 1 до 10.")
        return 2
    if args.apply and args.confirmation != _APPLY_CONFIRMATION:
        print("Помилка: запис заблоковано — немає точного canary-підтвердження.")
        return 2

    if load_context is None:
        load_context = _default_load_context
    if np_fetch_many is None:
        from services.novaposhta import fetch_tracking_statuses

        np_fetch_many = fetch_tracking_statuses
    if up_fetch_one is None:
        from services.ukrposhta_tracking import fetch_tracking_status

        up_fetch_one = fetch_tracking_status

    try:
        worksheet, rows = load_context()
    except Exception as exc:
        print(f"Не вдалося прочитати Orders: {exc}")
        return 1
    if not rows:
        print("Orders порожня або недоступна. Жодних змін не виконано.")
        return 1

    specs = (
        ("НП", np_fetch_many, None),
        ("УП", None, up_fetch_one),
    )
    selected: list[tuple[str, str, dict]] = []
    errors: list[str] = []
    summaries = []
    for service, np_fetch, up_fetch in specs:
        result = run_status_cycle(
            rows,
            np_fetch_many=np_fetch,
            up_fetch_one=up_fetch,
            dry_run=True,
            services=(service,),
            max_rows=args.candidate_limit,
        )
        errors.extend(result.errors)
        chosen = None
        for update in result.planned:
            changes = {
                field: update.changes[field]
                for field in _CANARY_FIELDS
                if field in update.changes
            }
            if changes:
                chosen = (update.ttn, update.service, changes)
                selected.append(chosen)
                break
        summaries.append((service, result, chosen))

    print(
        "CANARY APPLY: дозволено лише «Статус» і «Дата»."
        if args.apply
        else "CANARY PREVIEW: запис у Google Sheets і TurboSMS вимкнені."
    )
    for service, result, chosen in summaries:
        print(
            f"{service}: переглянуто {result.scanned}; активних {result.eligible}; "
            f"службових статусів відкинуто {result.ignored_statuses}."
        )
        if chosen is None:
            print(f"- {service}: немає зміни статусу/дати для canary.")
            continue
        ttn, _, changes = chosen
        labels = []
        if "Статус" in changes:
            labels.append(f"Статус → {changes['Статус']}")
        if "Дата" in changes:
            labels.append("Дата")
        print(f"- {service} {_mask_ttn(ttn)}: {', '.join(labels)}")

    for error in errors:
        print(f"Увага: {error}")
    if errors:
        print("Canary скасовано через помилки API. Жодних змін не виконано.")
        return 1

    writer = OrdersStatusBatchWriter(worksheet)
    prepared, prepare_error = writer.prepare(
        [(ttn, changes) for ttn, _, changes in selected]
    )
    if prepare_error:
        print(f"Canary скасовано: {prepare_error}")
        return 1
    if prepared.row_count > 2:
        print("Canary скасовано: підготовлено більше двох рядків.")
        return 1

    if not args.apply:
        print(
            f"PREVIEW OK: перевірено {prepared.row_count} цільових рядків; "
            "batch_update не викликався."
        )
        return 0

    written, write_error = writer.apply_prepared(prepared)
    if write_error:
        print(f"Canary запис не виконано: {write_error}")
        return 1
    print(f"CANARY WRITE OK: точково оновлено рядків: {written}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
