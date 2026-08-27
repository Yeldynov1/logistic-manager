#!/usr/bin/env python3
"""Пробне читання статусів: без запису в таблицю та без надсилання SMS."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TRANSIENT_GOOGLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _google_error_status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    for raw in (getattr(response, "status_code", None), getattr(exc, "code", None)):
        try:
            code = int(raw)
        except (TypeError, ValueError):
            continue
        if 100 <= code <= 599:
            return code
    match = re.search(r"\[(\d{3})\]", str(exc))
    return int(match.group(1)) if match else None


def _read_google_rows(client, workbook: str, *, attempts: int = 3, sleep_fn=None):
    """Прочитати Orders з короткими повторами лише для 429/5xx."""
    total_attempts = max(1, int(attempts))
    sleeper = sleep_fn or time.sleep
    for attempt in range(total_attempts):
        try:
            return client.open(workbook).sheet1.get_all_records()
        except Exception as exc:
            code = _google_error_status_code(exc)
            if code not in _TRANSIENT_GOOGLE_STATUS_CODES or attempt + 1 >= total_attempts:
                raise
            delay = 2**attempt
            print(
                f"Google Sheets тимчасово недоступний ({code}); "
                f"повтор {attempt + 2}/{total_attempts} через {delay} с."
            )
            sleeper(delay)


def _google_client_from_environment():
    """Створити gspread-клієнт тільки з локальних/GitHub змінних середовища."""
    credentials_json = str(os.environ.get("GCP_SERVICE_ACCOUNT_JSON", "") or "").strip()
    credentials_toml = str(os.environ.get("GCP_SERVICE_ACCOUNT_TOML", "") or "").strip()
    credentials_file = str(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "") or ""
    ).strip()
    if not (credentials_json or credentials_toml or credentials_file):
        return None

    import gspread

    if credentials_json:
        return gspread.service_account_from_dict(json.loads(credentials_json))
    if credentials_toml:
        try:
            import tomllib
        except ModuleNotFoundError:  # Python 3.10 і старіше (локальна перевірка)
            import toml as tomllib

        parsed = tomllib.loads(credentials_toml)
        credentials = parsed.get("gcp_service_account", parsed)
        if not isinstance(credentials, dict) or not credentials:
            raise ValueError(
                "GCP_SERVICE_ACCOUNT_TOML не містить секцію [gcp_service_account]"
            )
        return gspread.service_account_from_dict(credentials)
    return gspread.service_account(filename=credentials_file)


def _open_google_worksheet(client, workbook: str, *, attempts: int = 3, sleep_fn=None):
    total_attempts = max(1, int(attempts))
    sleeper = sleep_fn or time.sleep
    for attempt in range(total_attempts):
        try:
            return client.open(workbook).sheet1
        except Exception as exc:
            code = _google_error_status_code(exc)
            if code not in _TRANSIENT_GOOGLE_STATUS_CODES or attempt + 1 >= total_attempts:
                raise
            delay = 2**attempt
            print(
                f"Google Sheets тимчасово недоступний ({code}); "
                f"повтор {attempt + 2}/{total_attempts} через {delay} с."
            )
            sleeper(delay)


def _read_google_worksheet_rows(worksheet, *, attempts: int = 3, sleep_fn=None):
    total_attempts = max(1, int(attempts))
    sleeper = sleep_fn or time.sleep
    for attempt in range(total_attempts):
        try:
            return worksheet.get_all_records()
        except Exception as exc:
            code = _google_error_status_code(exc)
            if code not in _TRANSIENT_GOOGLE_STATUS_CODES or attempt + 1 >= total_attempts:
                raise
            delay = 2**attempt
            print(
                f"Google Sheets тимчасово недоступний ({code}); "
                f"повтор {attempt + 2}/{total_attempts} через {delay} с."
            )
            sleeper(delay)


def _load_rows():
    client = _google_client_from_environment()
    if client is not None:
        workbook = str(os.environ.get("ORDERS_SPREADSHEET_NAME", "Orders") or "Orders")
        return _read_google_rows(client, workbook)

    import sheets

    sheets.load_data_from_gsheets.clear()
    frame = sheets.load_data_from_gsheets()
    return frame.to_dict("records") if frame is not None else []


def _mask_ttn(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 6:
        return text or "—"
    return f"…{text[-6:]}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Перевірити статуси НП/УП без будь-якого запису."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Скільки перших рядків перевірити (1–50, типово 5).",
    )
    parser.add_argument(
        "--service",
        choices=("all", "np", "up"),
        default="all",
        help="Служба: all, np або up.",
    )
    return parser


def main(
    argv=None,
    *,
    load_rows=None,
    np_fetch_many=None,
    up_fetch_one=None,
) -> int:
    args = _parser().parse_args(argv)
    if not 1 <= args.limit <= 50:
        print("Помилка: --limit має бути від 1 до 50.")
        return 2

    if load_rows is None:
        load_rows = _load_rows
    if np_fetch_many is None:
        from services.novaposhta import fetch_tracking_statuses

        np_fetch_many = fetch_tracking_statuses
    if up_fetch_one is None:
        from services.ukrposhta_tracking import fetch_tracking_status

        up_fetch_one = fetch_tracking_status

    try:
        rows = list(load_rows() or [])
    except Exception as exc:
        print(f"Не вдалося прочитати Orders: {exc}")
        return 1
    if not rows:
        print(
            "Orders порожня або недоступна. Для фонового запуску додайте "
            "GCP_SERVICE_ACCOUNT_TOML або GCP_SERVICE_ACCOUNT_JSON. "
            "Жодних змін не виконано."
        )
        return 1

    from services.status_worker import run_status_cycle

    service_map = {"all": ("НП", "УП"), "np": ("НП",), "up": ("УП",)}
    result = run_status_cycle(
        rows,
        np_fetch_many=np_fetch_many,
        up_fetch_one=up_fetch_one,
        dry_run=True,
        services=service_map[args.service],
        max_rows=args.limit,
    )

    print("DRY-RUN: запис у Google Sheets і TurboSMS вимкнені.")
    print(
        f"Переглянуто: {result.scanned}; активних: {result.eligible}; "
        f"пропозицій: {len(result.planned)}; фінальних пропущено: {result.skipped_final}; "
        f"службових статусів відкинуто: {result.ignored_statuses}."
    )
    for update in result.planned:
        labels = []
        for key in ("Статус", "Дата", "Вартість", "Телефон", "Номер накладної"):
            if key not in update.changes:
                continue
            if key == "Статус":
                labels.append(f"Статус → {update.changes[key]}")
            else:
                labels.append(key)
        print(f"- {update.service} {_mask_ttn(update.ttn)}: {', '.join(labels)}")
    for error in result.errors:
        print(f"Увага: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
