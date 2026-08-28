#!/usr/bin/env python3
"""Preview або мала фонова видача чеків через TurboSMS."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.status_canary import _default_load_context  # noqa: E402
from scripts.status_dry_run import _mask_ttn  # noqa: E402
from services.receipt_worker import (  # noqa: E402
    append_receipt_audit,
    process_receipt_candidates,
    read_completed_receipt_ttns,
    select_ready_receipts,
)


def _confirmation(limit: int) -> str:
    return f"SEND-RECEIPTS-{int(limit)}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Переглянути або видати малий пакет чеків через TurboSMS."
    )
    parser.add_argument("--limit", type=int, default=1, help="Максимум чеків: 1–3.")
    parser.add_argument("--apply", action="store_true", help="Дозволити TurboSMS і видалення.")
    parser.add_argument("--confirmation", default="", help="Потрібне SEND-RECEIPTS-N.")
    return parser


def _safe_error(ttn: str, error: str) -> str:
    return str(error or "").replace(str(ttn or ""), _mask_ttn(ttn))


def main(
    argv=None,
    *,
    load_context=None,
    send_func=None,
    audit_func=append_receipt_audit,
) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 3:
        print("Помилка: --limit має бути від 1 до 3.")
        return 2
    if args.apply and args.confirmation != _confirmation(args.limit):
        print("Помилка: видачу заблоковано — немає точного підтвердження.")
        return 2

    try:
        worksheet, rows = (load_context or _default_load_context)()
    except Exception as exc:
        print(f"Не вдалося прочитати Orders: {exc}")
        return 1
    completed = read_completed_receipt_ttns(worksheet)
    selection = select_ready_receipts(
        rows,
        limit=args.limit,
        completed_ttns=completed,
    )
    mode = "APPLY" if args.apply else "PREVIEW"
    print(
        f"RECEIPT {mode}: переглянуто {selection.scanned}; "
        f"готових без дублів {selection.eligible}; у пакеті {len(selection.candidates)}."
    )
    if selection.duplicate_rows:
        print(
            f"Увага: готових рядків із дубльованою ТТН пропущено: "
            f"{selection.duplicate_rows}."
        )
    for candidate in selection.candidates:
        print(f"- {_mask_ttn(candidate.ttn)}: чек, телефон і статус перевірені.")

    if not args.apply:
        print("PREVIEW OK: TurboSMS, аудит і видалення вимкнені.")
        return 0
    if not selection.candidates:
        print("BACKGROUND RECEIPT OK: готових чеків немає.")
        return 0

    if send_func is None:
        import utils

        if not utils.turbosms_configured():
            print("Помилка: у GitHub Secrets немає TURBOSMS_TOKEN.")
            return 1
        send_func = utils.turbosms_send

    result = process_receipt_candidates(
        worksheet,
        selection.candidates,
        send_func=send_func,
        completed_ttns=completed,
        audit_func=audit_func,
    )
    print(
        f"BACKGROUND RECEIPT: прийнято TurboSMS {result.accepted}; "
        f"відновлено з аудиту {result.recovered}; видалено {result.removed}."
    )
    for ttn, error in result.errors:
        print(f"Увага {_mask_ttn(ttn)}: {_safe_error(ttn, error)}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
