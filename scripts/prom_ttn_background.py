#!/usr/bin/env python3
"""Attach queued Ukrposhta TTNs to Prom.ua after the marketplace delay."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import utils  # noqa: E402
from scripts.status_dry_run import _google_client_from_environment, _mask_ttn  # noqa: E402
from services import promua  # noqa: E402
from services.prom_ttn_queue import (  # noqa: E402
    CONFLICT_STATUS,
    DONE_STATUS,
    PENDING_STATUS,
    ensure_queue_worksheet,
    record_transfer_result,
    select_due_transfers,
)


def _confirmation(limit: int) -> str:
    return f"SEND-PROM-TTNS-{int(limit)}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Передати в Prom.ua дозрілі ТТН із постійної черги."
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    return parser


def _load_context():
    client = _google_client_from_environment()
    if client is None:
        raise RuntimeError("Немає GCP_SERVICE_ACCOUNT_TOML або GCP_SERVICE_ACCOUNT_JSON")
    workbook = str(os.environ.get("ORDERS_SPREADSHEET_NAME", "Orders") or "Orders")
    spreadsheet = client.open(workbook)
    worksheet = ensure_queue_worksheet(spreadsheet)
    return worksheet, list(worksheet.get_all_records() or [])


def main(
    argv=None,
    *,
    load_context=None,
    fetch_order=None,
    send_ttn=None,
    now=None,
) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 10:
        print("Помилка: --limit має бути від 1 до 10.")
        return 2
    if args.apply and args.confirmation != _confirmation(args.limit):
        print("Помилка: передавання заблоковано — немає точного підтвердження.")
        return 2

    try:
        worksheet, records = (load_context or _load_context)()
    except Exception as exc:
        print(f"Не вдалося прочитати чергу Prom.ua: {exc}")
        return 1

    current_time = now or utils.now_kyiv_naive()
    due = select_due_transfers(records, now=current_time, limit=args.limit)
    mode = "APPLY" if args.apply else "PREVIEW"
    print(f"PROM TTN {mode}: готових до передачі {len(due)}.")
    for transfer in due:
        print(f"- Prom.ua #{transfer.order_id}: УП {_mask_ttn(transfer.ttn)}")
    if not args.apply:
        print("PREVIEW OK: Prom.ua і чергу не змінено.")
        return 0
    if not due:
        print("BACKGROUND PROM TTN OK: черга поки порожня.")
        return 0

    fetch = fetch_order or promua.fetch_order
    sender = send_ttn or promua.save_declaration_id
    completed = 0
    retried = 0
    conflicts = 0
    write_errors = 0

    for transfer in due:
        status = PENDING_STATUS
        error = ""
        try:
            detail, fetch_error = fetch(transfer.order_id)
            if fetch_error:
                error = f"Prom.ua ще недоступний: {str(fetch_error)[:220]}"
            else:
                attached = promua.normalize_ttn(
                    promua.order_ttn(detail if isinstance(detail, dict) else {})
                )
                if attached:
                    if attached == promua.normalize_ttn(transfer.ttn):
                        status = DONE_STATUS
                        completed += 1
                    else:
                        status = CONFLICT_STATUS
                        error = "У замовленні вже є інша ТТН; автоматичну заміну заблоковано."
                        conflicts += 1
                else:
                    _, send_error = sender(
                        transfer.order_id,
                        transfer.ttn,
                        order=detail if isinstance(detail, dict) else None,
                        delivery_type="ukrposhta",
                    )
                    if send_error:
                        error = str(send_error)[:220]
                    else:
                        status = DONE_STATUS
                        completed += 1
        except Exception as exc:
            error = str(exc)[:220]

        if status == PENDING_STATUS:
            retried += 1
        try:
            record_transfer_result(
                worksheet,
                transfer,
                status=status,
                error=error,
                now=current_time,
            )
        except Exception as exc:
            write_errors += 1
            print(
                f"Помилка черги Prom.ua #{transfer.order_id}: "
                f"{str(exc)[:180]}"
            )

    print(
        f"BACKGROUND PROM TTN: передано/вже було {completed}; "
        f"чекатимуть повтору {retried}; конфліктів {conflicts}."
    )
    return 1 if write_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
