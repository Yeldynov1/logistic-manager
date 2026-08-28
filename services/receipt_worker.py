"""Безпечна фонова видача чеків: SMS → аудит → точкове видалення Orders."""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Iterable, Optional

import gspread

import utils
from core.order_identity import order_ttn_match_keys, resolve_order_ttn_rows
from core.receipt_delivery import receipt_sms_text_for_send, row_ready_for_turbosms
from services.status_sheet_writer import _is_transient_google_error


AUDIT_WORKSHEET_TITLE = "LogisticAudit"
AUDIT_HEADERS = (
    "Час",
    "Користувач",
    "Дія",
    "ТТН",
    "Деталі",
    "Вартість ТТН",
    "Сума чеку",
)
_CRITICAL_HEADERS = (
    "ТТН",
    "Статус",
    "Телефон",
    "Чек",
    "Статус СМС",
)


@dataclass(frozen=True)
class ReceiptCandidate:
    ttn: str
    phone: str
    text: str
    receipt: str
    ship_cost: Optional[float] = None


@dataclass(frozen=True)
class ReceiptSelection:
    scanned: int = 0
    eligible: int = 0
    duplicate_rows: int = 0
    candidates: tuple[ReceiptCandidate, ...] = ()


@dataclass
class ReceiptProcessResult:
    accepted: int = 0
    removed: int = 0
    recovered: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def _candidate_from_row(
    row,
    *,
    allow_completed: bool = False,
) -> Optional[ReceiptCandidate]:
    if not row_ready_for_turbosms(row, allow_completed=allow_completed):
        return None
    ttn = str(row.get("ТТН", "") or "").strip()
    if not order_ttn_match_keys(ttn):
        return None
    phone = utils.clean_phone(row.get("Телефон", ""))
    text = receipt_sms_text_for_send(row)
    receipt = str(row.get("Чек", "") or "").strip()
    try:
        ship_cost = float(str(row.get("Вартість", 0) or 0).replace(",", ".").strip())
    except (TypeError, ValueError):
        ship_cost = None
    return ReceiptCandidate(
        ttn=ttn,
        phone=phone,
        text=text,
        receipt=receipt,
        ship_cost=ship_cost,
    )


def select_ready_receipts(
    rows: Iterable,
    *,
    limit: int = 3,
    completed_ttns: Iterable[str] = (),
) -> ReceiptSelection:
    """Вибрати до трьох готових рядків, повністю відкинувши дубльовані ТТН."""
    max_rows = max(0, int(limit))
    completed_keys = {
        key
        for ttn in completed_ttns or ()
        for key in order_ttn_match_keys(ttn)
    }
    provisional: list[tuple[ReceiptCandidate, frozenset[str]]] = []
    scanned = 0
    for row in rows or []:
        scanned += 1
        raw_ttn = str(row.get("ТТН", "") or "").strip()
        already_accepted = bool(order_ttn_match_keys(raw_ttn) & completed_keys)
        candidate = _candidate_from_row(row, allow_completed=already_accepted)
        if candidate is not None:
            provisional.append((candidate, order_ttn_match_keys(candidate.ttn)))

    duplicate_indices: set[int] = set()
    for left in range(len(provisional)):
        for right in range(left + 1, len(provisional)):
            if provisional[left][1] & provisional[right][1]:
                duplicate_indices.update((left, right))
    safe = [
        candidate
        for index, (candidate, _keys) in enumerate(provisional)
        if index not in duplicate_indices
    ]
    return ReceiptSelection(
        scanned=scanned,
        eligible=len(safe),
        duplicate_rows=len(duplicate_indices),
        candidates=tuple(safe[:max_rows]),
    )


def _worksheet_headers(worksheet) -> tuple[list[str], dict[str, int], str]:
    headers_raw = [str(value or "").strip() for value in worksheet.row_values(1)]
    invalid = [name for name in _CRITICAL_HEADERS if headers_raw.count(name) != 1]
    if invalid:
        return [], {}, "У Orders відсутні або дублюються колонки: " + ", ".join(invalid)
    header_map = {
        value: index for index, value in enumerate(headers_raw, start=1) if value
    }
    return headers_raw, header_map, ""


def _load_live_candidate(
    worksheet,
    expected: ReceiptCandidate,
    *,
    allow_completed: bool = False,
) -> tuple[Optional[ReceiptCandidate], str]:
    headers, header_map, error = _worksheet_headers(worksheet)
    if error:
        return None, error
    ttn_values = worksheet.col_values(header_map["ТТН"])
    resolved, error = resolve_order_ttn_rows(
        ttn_values,
        [expected.ttn],
        header_rows=1,
    )
    if error:
        return None, error
    row_values = list(worksheet.row_values(resolved[expected.ttn]))
    live_row = {
        header: row_values[index] if index < len(row_values) else ""
        for index, header in enumerate(headers)
        if header
    }
    current = _candidate_from_row(live_row, allow_completed=allow_completed)
    if current is None:
        return None, "Рядок уже не відповідає безпечним умовам видачі чека."
    if (
        current.phone != expected.phone
        or current.text != expected.text
        or current.receipt != expected.receipt
    ):
        return None, "Телефон, чек або текст змінилися після попереднього читання."
    return current, ""


def _delete_order_by_ttn(
    worksheet,
    ttn: str,
    *,
    attempts: int = 3,
    sleep_fn=time.sleep,
) -> tuple[bool, str]:
    total_attempts = max(1, int(attempts))
    for attempt in range(1, total_attempts + 1):
        try:
            headers, header_map, error = _worksheet_headers(worksheet)
            if error:
                return False, error
            del headers
            ttn_values = worksheet.col_values(header_map["ТТН"])
            resolved, error = resolve_order_ttn_rows(
                ttn_values,
                [ttn],
                header_rows=1,
            )
            if error:
                if "не знайдено" in error.casefold():
                    return True, ""
                return False, error
            row_number = resolved[ttn]
            worksheet.spreadsheet.batch_update(
                {
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": int(worksheet.id),
                                    "dimension": "ROWS",
                                    "startIndex": row_number - 1,
                                    "endIndex": row_number,
                                }
                            }
                        }
                    ]
                }
            )
            return True, ""
        except Exception as exc:
            if attempt >= total_attempts or not _is_transient_google_error(exc):
                return False, f"Помилка видалення Orders: {exc}"
            sleep_fn(attempt)
    return False, "Помилка видалення Orders."


def read_completed_receipt_ttns(worksheet) -> set[str]:
    """ТТН із наявним аудитом прийнятої TurboSMS — стійкий захист від повтору."""
    try:
        audit = worksheet.spreadsheet.worksheet(AUDIT_WORKSHEET_TITLE)
        completed = set()
        for row in audit.get_all_records():
            if str(row.get("Дія", "") or "").strip() != "смс_turbosms":
                continue
            ttn = str(row.get("ТТН", "") or "").strip()
            if ttn:
                completed.add(ttn)
        return completed
    except Exception:
        return set()


def append_receipt_audit(
    worksheet,
    candidate: ReceiptCandidate,
    message_id: Optional[str],
) -> bool:
    """Спочатку зафіксувати прийняту SMS; лише після цього дозволене видалення."""
    try:
        spreadsheet = worksheet.spreadsheet
        try:
            audit = spreadsheet.worksheet(AUDIT_WORKSHEET_TITLE)
        except gspread.WorksheetNotFound:
            audit = spreadsheet.add_worksheet(
                title=AUDIT_WORKSHEET_TITLE,
                rows=2000,
                cols=len(AUDIT_HEADERS),
            )
            audit.append_row(list(AUDIT_HEADERS))
        headers = [str(value or "").strip() for value in audit.row_values(1)]
        if tuple(headers[: len(AUDIT_HEADERS)]) != AUDIT_HEADERS:
            audit.update("A1:G1", [list(AUDIT_HEADERS)])
        detail = candidate.receipt[:120]
        if message_id:
            detail = f"{detail} · id={str(message_id)[:80]}" if detail else f"id={str(message_id)[:80]}"
        audit.append_row(
            [
                utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
                "Фон GitHub",
                "смс_turbosms",
                candidate.ttn[:40],
                detail[:500],
                "" if candidate.ship_cost is None else candidate.ship_cost,
                "",
            ],
            value_input_option="USER_ENTERED",
        )
        return True
    except Exception:
        return False


def _ttn_in_completed(ttn: str, completed_keys: set[str]) -> bool:
    return bool(order_ttn_match_keys(ttn) & completed_keys)


def process_receipt_candidates(
    worksheet,
    candidates: Iterable[ReceiptCandidate],
    *,
    send_func: Callable[[str, str, str], tuple[bool, Optional[str], str]],
    completed_ttns: Iterable[str] = (),
    audit_func: Callable[[object, ReceiptCandidate, Optional[str]], bool] = append_receipt_audit,
    delete_func: Callable[[object, str], tuple[bool, str]] = _delete_order_by_ttn,
) -> ReceiptProcessResult:
    """Для кожного рядка: повторна перевірка → SMS → аудит → видалення."""
    result = ReceiptProcessResult()
    completed_keys = {
        key
        for ttn in completed_ttns or ()
        for key in order_ttn_match_keys(ttn)
    }
    for expected in candidates or ():
        expected_already_accepted = _ttn_in_completed(expected.ttn, completed_keys)
        current, validation_error = _load_live_candidate(
            worksheet,
            expected,
            allow_completed=expected_already_accepted,
        )
        if current is None:
            result.errors.append((expected.ttn, validation_error))
            continue

        already_accepted = _ttn_in_completed(current.ttn, completed_keys)
        message_id = None
        if not already_accepted:
            try:
                ok, message_id, send_error = send_func(
                    current.phone,
                    current.text,
                    idempotency_key=current.ttn,
                )
            except Exception as exc:
                ok, message_id, send_error = False, None, str(exc)
            if not ok:
                result.errors.append(
                    (current.ttn, send_error or "TurboSMS не підтвердив прийняття.")
                )
                continue
            result.accepted += 1
            try:
                audit_ok = bool(audit_func(worksheet, current, message_id))
            except Exception:
                audit_ok = False
            if not audit_ok:
                result.errors.append(
                    (
                        current.ttn,
                        "TurboSMS прийняв повідомлення, але аудит не записано; рядок залишено для безпечного повтору.",
                    )
                )
                continue
            completed_keys.update(order_ttn_match_keys(current.ttn))
        else:
            result.recovered += 1

        try:
            deleted, delete_error = delete_func(worksheet, current.ttn)
        except Exception as exc:
            deleted, delete_error = False, str(exc)
        if deleted:
            result.removed += 1
        else:
            result.errors.append(
                (current.ttn, delete_error or "Не вдалося видалити рядок Orders.")
            )
    return result
