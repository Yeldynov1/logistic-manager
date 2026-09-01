"""Persistent delayed transfer queue for Ukrposhta TTNs to Prom.ua."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import gspread

import utils


WORKSHEET_TITLE = "PromTTNQueue"
HEADERS = [
    "Створено",
    "Передати після",
    "Prom ID",
    "ТТН",
    "Статус",
    "Спроб",
    "Остання спроба",
    "Помилка",
]
PENDING_STATUS = "pending"
DONE_STATUS = "done"
CONFLICT_STATUS = "conflict"
DEFAULT_DELAY_MINUTES = 20


@dataclass(frozen=True)
class PendingPromTtnTransfer:
    row_number: int
    order_id: int
    ttn: str
    due_at: datetime
    attempts: int = 0


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp(value) -> datetime | None:
    text = str(value or "").strip().replace("T", " ")[:19]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _order_id(value) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _attempts(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def ensure_queue_worksheet(spreadsheet):
    """Return the queue worksheet, creating only this small sheet when absent."""
    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_TITLE)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=WORKSHEET_TITLE,
            rows=1000,
            cols=len(HEADERS),
        )
        worksheet.append_row(HEADERS)
        return worksheet

    try:
        if int(getattr(worksheet, "col_count", 0) or 0) < len(HEADERS):
            worksheet.resize(cols=len(HEADERS))
        if worksheet.row_values(1) != HEADERS:
            worksheet.update("A1:H1", [HEADERS])
    except Exception:
        pass
    return worksheet


def enqueue_transfer(
    worksheet,
    order_id: int | str,
    ttn: str,
    *,
    now: datetime | None = None,
    delay_minutes: int = DEFAULT_DELAY_MINUTES,
) -> tuple[bool, str]:
    """Add one delayed transfer, rejecting a different pending TTN for that order."""
    oid = _order_id(order_id)
    normalized_ttn = utils.clean_ttn(ttn)
    if oid is None or not normalized_ttn:
        return False, "Немає Prom ID або ТТН для відкладеної передачі."

    try:
        records = list(worksheet.get_all_records() or [])
    except Exception as exc:
        return False, f"Не вдалося прочитати чергу Prom.ua: {str(exc)[:180]}"

    for record in records:
        if _order_id(record.get("Prom ID")) != oid:
            continue
        queued_ttn = utils.clean_ttn(record.get("ТТН"))
        status = str(record.get("Статус") or PENDING_STATUS).strip().lower()
        if queued_ttn == normalized_ttn and status in (PENDING_STATUS, DONE_STATUS):
            return True, "ТТН уже є в черзі Prom.ua."
        if queued_ttn != normalized_ttn and status == PENDING_STATUS:
            return False, (
                f"Для Prom.ua #{oid} вже очікує інша ТТН. "
                "Автоматичну заміну заблоковано."
            )

    created_at = now or utils.now_kyiv_naive()
    delay = max(20, min(30, int(delay_minutes or DEFAULT_DELAY_MINUTES)))
    due_at = created_at + timedelta(minutes=delay)
    try:
        worksheet.append_row(
            [
                _timestamp(created_at),
                _timestamp(due_at),
                str(oid),
                normalized_ttn,
                PENDING_STATUS,
                "0",
                "",
                "",
            ],
            value_input_option="RAW",
        )
        return True, f"Передачу в Prom.ua заплановано після {_timestamp(due_at)[11:16]}."
    except Exception as exc:
        return False, f"Не вдалося записати чергу Prom.ua: {str(exc)[:180]}"


def select_due_transfers(
    records: list[dict],
    *,
    now: datetime | None = None,
    limit: int = 5,
) -> list[PendingPromTtnTransfer]:
    current = now or utils.now_kyiv_naive()
    selected: list[PendingPromTtnTransfer] = []
    seen: set[tuple[int, str]] = set()
    for row_number, record in enumerate(records or [], start=2):
        status = str(record.get("Статус") or PENDING_STATUS).strip().lower()
        if status != PENDING_STATUS:
            continue
        oid = _order_id(record.get("Prom ID"))
        ttn = utils.clean_ttn(record.get("ТТН"))
        due_at = _parse_timestamp(record.get("Передати після"))
        if oid is None or not ttn or due_at is None or due_at > current:
            continue
        key = (oid, ttn)
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            PendingPromTtnTransfer(
                row_number=row_number,
                order_id=oid,
                ttn=ttn,
                due_at=due_at,
                attempts=_attempts(record.get("Спроб")),
            )
        )
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def record_transfer_result(
    worksheet,
    transfer: PendingPromTtnTransfer,
    *,
    status: str,
    error: str = "",
    now: datetime | None = None,
) -> None:
    """Update only status/attempt metadata for the exact queue row."""
    row = int(transfer.row_number)
    attempted_at = now or utils.now_kyiv_naive()
    worksheet.batch_update(
        [
            {"range": f"E{row}", "values": [[str(status or PENDING_STATUS)[:40]]]},
            {"range": f"F{row}", "values": [[str(transfer.attempts + 1)]]},
            {"range": f"G{row}", "values": [[_timestamp(attempted_at)]]},
            {"range": f"H{row}", "values": [[str(error or "")[:300]]]},
        ],
        value_input_option="USER_ENTERED",
    )
