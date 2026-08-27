"""Фонове планування статусів замовлень без Streamlit UI та без SMS.

Модуль навмисно не імпортує ``app`` і не звертається до Google Sheets сам.
API-функції та точковий запис передаються ззовні, тому цикл можна спочатку
запускати у ``dry_run`` і повністю тестувати без мережі.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional

import utils


SUPPORTED_SERVICES = frozenset({"НП", "УП"})


@dataclass(frozen=True)
class CarrierStatus:
    status: str = ""
    date: str = ""
    cost: float = 0.0
    phone: str = ""
    invoice: str = ""


@dataclass(frozen=True)
class PlannedStatusUpdate:
    """Точкові зміни одного рядка; ``ttn`` завжди лишається ключем запису."""

    ttn: str
    service: str
    changes: dict


@dataclass
class StatusCycleResult:
    scanned: int = 0
    eligible: int = 0
    skipped_final: int = 0
    ignored_statuses: int = 0
    planned: list[PlannedStatusUpdate] = field(default_factory=list)
    written: int = 0
    errors: list[str] = field(default_factory=list)


def _service_code(value, ttn: str) -> str:
    raw = str(value or "").strip()
    low = raw.lower()
    if raw == "НП" or "нова" in low:
        return "НП"
    if raw == "УП" or "укрпошт" in low:
        return "УП"
    inferred = utils.identify_service(ttn)
    return inferred if inferred in SUPPORTED_SERVICES else raw


def _lookup_ttn(ttn: str, service: str) -> str:
    clean = utils.clean_ttn(ttn)
    if service == "УП" and clean.isdigit() and len(clean) == 12:
        return "0" + clean
    return clean


def _coerce_carrier_status(value) -> Optional[CarrierStatus]:
    if value is None:
        return None
    if isinstance(value, CarrierStatus):
        return value
    if isinstance(value, Mapping):
        try:
            cost = float(str(value.get("cost", value.get("Cost", 0)) or 0).replace(",", "."))
        except (TypeError, ValueError):
            cost = 0.0
        return CarrierStatus(
            status=str(value.get("status", value.get("Status", "")) or "").strip(),
            date=str(value.get("date", value.get("Date", "")) or "").strip(),
            cost=cost,
            phone=str(value.get("phone", value.get("Phone", "")) or "").strip(),
            invoice=str(
                value.get("invoice", value.get("ClientBarcode", "")) or ""
            ).strip(),
        )
    return None


def _status_is_usable(status: str) -> bool:
    value = str(status or "").strip()
    normalized = value.casefold()
    blocked_fragments = (
        "не знайдено",
        "не найдено",
        "not found",
        "невідомо",
        "unknown",
    )
    return bool(
        value
        and not normalized.startswith("error")
        and not any(fragment in normalized for fragment in blocked_fragments)
    )


def _phone_is_missing(row) -> bool:
    return len(utils.clean_phone(row.get("Телефон", ""))) < 10


def _build_changes(row, carrier: CarrierStatus) -> dict:
    changes = {}
    if _status_is_usable(carrier.status):
        current = str(row.get("Статус", "") or "").strip()
        if carrier.status != current:
            changes["Статус"] = carrier.status
    if carrier.date:
        date = utils.normalize_date(carrier.date)
        if date and date != str(row.get("Дата", "") or "").strip():
            changes["Дата"] = date
    if carrier.cost > 0:
        try:
            current_cost = float(
                str(row.get("Вартість", 0) or 0).replace(",", ".").strip()
            )
        except (TypeError, ValueError):
            current_cost = 0.0
        if carrier.cost != current_cost:
            changes["Вартість"] = carrier.cost
    if carrier.phone and _phone_is_missing(row):
        changes["Телефон"] = utils.clean_phone(carrier.phone)
    if carrier.invoice:
        invoice = utils.normalize_invoice_number(carrier.invoice)
        if invoice and invoice != str(row.get("Номер накладної", "") or "").strip():
            changes["Номер накладної"] = invoice
    return changes


def run_status_cycle(
    rows: Iterable,
    *,
    np_fetch_many: Optional[Callable[[list[str]], Mapping]] = None,
    up_fetch_one: Optional[Callable[[str], object]] = None,
    write_changes: Optional[Callable[[str, dict], tuple[bool, str]]] = None,
    dry_run: bool = True,
    services: Iterable[str] = ("НП", "УП"),
    max_rows: Optional[int] = None,
    candidate_offset: int = 0,
    up_workers: int = 1,
) -> StatusCycleResult:
    """Спланувати й, якщо дозволено, точково записати оновлення статусів.

    ``dry_run=True`` ніколи не викликає ``write_changes``. Поля чеків і SMS
    модуль не формує та не змінює.
    """
    allowed = SUPPORTED_SERVICES.intersection(str(s) for s in services)
    result = StatusCycleResult()
    candidates = []
    rotation_offset = max(0, int(candidate_offset or 0))

    for row in rows:
        if (
            rotation_offset == 0
            and max_rows is not None
            and result.eligible >= max(0, int(max_rows))
        ):
            break
        result.scanned += 1
        raw_ttn = str(row.get("ТТН", "") or "").strip()
        service = _service_code(row.get("Служба", ""), raw_ttn)
        if service not in allowed:
            continue
        current_status = str(row.get("Статус", "") or "")
        if utils.status_has_any(current_status, utils.STOP_TRACKING_STATUS_KEYWORDS):
            result.skipped_final += 1
            continue
        lookup_ttn = _lookup_ttn(raw_ttn, service)
        if len(lookup_ttn) < 5:
            result.errors.append(f"Некоректна ТТН: {raw_ttn or 'порожня'}")
            continue
        result.eligible += 1
        candidates.append((row, raw_ttn, lookup_ttn, service))

    # Фоновий workflow передає зсув, що зростає на розмір пакета. Так він
    # поступово обходить усі активні ТТН, а не перевіряє одні й ті самі перші.
    if rotation_offset and candidates:
        offset = rotation_offset % len(candidates)
        candidates = candidates[offset:] + candidates[:offset]
        if max_rows is not None:
            candidates = candidates[: max(0, int(max_rows))]
        result.eligible = len(candidates)

    np_candidates = [c for c in candidates if c[3] == "НП"]
    np_results: Mapping = {}
    if np_candidates:
        if np_fetch_many is None:
            result.errors.append("Для НП не передано функцію отримання статусів.")
        else:
            try:
                np_results = np_fetch_many([c[2] for c in np_candidates]) or {}
            except Exception as exc:
                result.errors.append(f"НП: {exc}")

    up_worker_count = max(1, int(up_workers or 1))
    up_prefetched: dict[str, object] = {}
    up_candidates = [c for c in candidates if c[3] == "УП"]
    if up_candidates and up_fetch_one is not None and up_worker_count > 1:
        unique_up = {}
        for _row, raw_ttn, lookup_ttn, _service in up_candidates:
            unique_up.setdefault(lookup_ttn, raw_ttn)
        with ThreadPoolExecutor(
            max_workers=min(up_worker_count, len(unique_up)),
            thread_name_prefix="up-status",
        ) as executor:
            futures = {
                executor.submit(up_fetch_one, lookup_ttn): (lookup_ttn, raw_ttn)
                for lookup_ttn, raw_ttn in unique_up.items()
            }
            for future in as_completed(futures):
                lookup_ttn, raw_ttn = futures[future]
                try:
                    up_prefetched[lookup_ttn] = future.result()
                except Exception as exc:
                    result.errors.append(f"УП {raw_ttn}: {exc}")

    for row, raw_ttn, lookup_ttn, service in candidates:
        carrier = None
        try:
            if service == "НП":
                carrier = _coerce_carrier_status(np_results.get(lookup_ttn))
            elif up_fetch_one is None:
                result.errors.append(f"УП {raw_ttn}: не передано функцію статусу.")
            elif up_worker_count > 1:
                carrier = _coerce_carrier_status(up_prefetched.get(lookup_ttn))
            else:
                carrier = _coerce_carrier_status(up_fetch_one(lookup_ttn))
        except Exception as exc:
            result.errors.append(f"{service} {raw_ttn}: {exc}")
            continue
        if carrier is None:
            continue
        if carrier.status and not _status_is_usable(carrier.status):
            result.ignored_statuses += 1
        changes = _build_changes(row, carrier)
        if changes:
            result.planned.append(
                PlannedStatusUpdate(ttn=raw_ttn, service=service, changes=changes)
            )

    if dry_run or write_changes is None:
        return result

    for update in result.planned:
        try:
            ok, error = write_changes(update.ttn, dict(update.changes))
        except Exception as exc:
            ok, error = False, str(exc)
        if ok:
            result.written += 1
        else:
            result.errors.append(
                f"{update.service} {update.ttn}: {error or 'помилка запису'}"
            )
    return result
