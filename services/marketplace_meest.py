"""Автоімпорт Meest-ТТН з активних замовлень маркетплейсів.

Модуль лише читає Rozetka, Prom.ua та Епіцентр. Збереження в Orders
виконує наявний безпечний механізм ``sheets.insert_new_orders``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable

import config
import utils
from core.order_identity import order_ttn_match_keys
from services import epicentr, promua, rozetka


_MAX_HISTORY_PAGES = 8
_MAX_HISTORY_DETAIL_LOOKUPS = 25


@dataclass
class MarketplaceMeestDiscovery:
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned: dict[str, int] = field(default_factory=dict)
    added: dict[str, int] = field(default_factory=dict)
    detail_lookups: dict[str, int] = field(default_factory=dict)
    detail_failures: dict[str, int] = field(default_factory=dict)


def _identity_keys(values: Iterable) -> set[str]:
    keys: set[str] = set()
    for value in values or []:
        keys.update(order_ttn_match_keys(value))
    return keys


def _safe_money(value) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    text = text.replace("\u00a0", " ").replace(" ", "").replace("грн", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return 0.0


def _ttn_looks_like_meest(value) -> bool:
    ttn = str(value or "").strip()
    return bool(ttn and utils.identify_service(utils.clean_ttn(ttn)) == "Meest")


def _contains_meest_marker(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_meest_marker(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_meest_marker(item) for item in value[:20])
    text = str(value or "").strip().lower()
    return "meest" in text or "міст" in text


def _rozetka_is_meest(order: dict) -> bool:
    service_name, _service_id = rozetka.delivery_service_raw(order)
    return (
        rozetka.delivery_service_kind(service_name) == "Meest"
        or _ttn_looks_like_meest(order.get("ttn"))
    )


def _prom_is_meest(order: dict) -> bool:
    provider_data = order.get("delivery_provider_data")
    return (
        promua.delivery_service_kind(order) == "Meest"
        or _contains_meest_marker(provider_data)
        or _ttn_looks_like_meest(promua.order_ttn(order))
    )


def _epicentr_is_meest(order: dict) -> bool:
    delivery_blocks = (
        order.get("address"),
        order.get("office"),
        order.get("delivery"),
        order.get("shipping"),
        order.get("deliveryMethod"),
        order.get("deliveryType"),
    )
    return (
        epicentr.delivery_service_kind(order) == "Meest"
        or any(_contains_meest_marker(block) for block in delivery_blocks)
        or _ttn_looks_like_meest(epicentr.order_ttn(order))
    )


def _row(*, ttn: str, phone: str, amount, created: str) -> dict:
    """Рядок Orders без видаткової накладної.

    Статус маркетплейсу навмисно не копіюємо: «Отримано» має
    прийти лише з трекінгу Meest, щоб не видати чек зарано.
    """
    raw_ttn = str(ttn or "").strip()
    return {
        "ТТН": raw_ttn,
        "Служба": "Meest",
        "Статус": "Нове",
        "Дата": utils.normalize_date(created),
        "Телефон": utils.clean_phone(str(phone or "")),
        "Вартість": _safe_money(amount),
        "Номер накладної": "",
        "Чек": "",
        "Повідомлення": "",
        "Статус СМС": "",
        "Статус Нагадування": "",
        "Дія": False,
    }


def _append_if_new(rows: list[dict], known_keys: set[str], row: dict) -> bool:
    ttn_keys = set(order_ttn_match_keys(row.get("ТТН")))
    if not ttn_keys or ttn_keys & known_keys:
        return False
    rows.append(row)
    known_keys.update(ttn_keys)
    return True


def _created_datetime(value) -> datetime | None:
    normalized = utils.normalize_date(value)
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _history_cutoff(history_days: int | None) -> datetime | None:
    if history_days is None:
        return None
    try:
        days = max(1, min(31, int(history_days)))
    except (TypeError, ValueError):
        days = 7
    return utils.now_kyiv_naive() - timedelta(days=days)


def _within_history(orders: list[dict], created_getter, cutoff: datetime) -> list[dict]:
    return [
        order
        for order in orders
        if (created := _created_datetime(created_getter(order))) is not None
        and created >= cutoff
    ]


def _page_reached_cutoff(orders: list[dict], created_getter, cutoff: datetime) -> bool:
    dates = [
        created
        for order in orders
        if (created := _created_datetime(created_getter(order))) is not None
    ]
    return bool(dates and min(dates) < cutoff)


def _rozetka_created(order: dict):
    return order.get("created") or order.get("created_at") or order.get("date_created")


def _prom_created(order: dict):
    return order.get("date_created") or order.get("created_at") or order.get("created")


def _epicentr_created(order: dict):
    return order.get("createdAt") or order.get("created_at") or order.get("created")


def _rozetka_orders(*, history_days: int | None = None) -> tuple[list[dict], str]:
    if not rozetka.credentials_configured():
        return [], ""
    cutoff = _history_cutoff(history_days)
    if cutoff is None:
        data, error = rozetka.search_orders(page=1, types=2)
        return rozetka.orders_from_search_response(data), error

    found: list[dict] = []
    for page in range(1, _MAX_HISTORY_PAGES + 1):
        data, error = rozetka.search_orders(page=page, types=1)
        page_orders = rozetka.orders_from_search_response(data)
        found.extend(page_orders)
        if error:
            return _within_history(found, _rozetka_created, cutoff), error
        meta = rozetka.search_meta(data)
        page_count = int(meta.get("pageCount") or page)
        if (
            not page_orders
            or page >= page_count
            or _page_reached_cutoff(page_orders, _rozetka_created, cutoff)
        ):
            break
    return _within_history(found, _rozetka_created, cutoff), ""


def _prom_orders(*, history_days: int | None = None) -> tuple[list[dict], str]:
    if not promua.token_configured():
        return [], ""
    limit = max(1, min(200, int(getattr(config, "PROM_UA_IMPORT_LIMIT", 50) or 50)))
    cutoff = _history_cutoff(history_days)
    if cutoff is None:
        orders, _meta, error = promua.fetch_orders(limit=limit, page=1)
        return orders, error

    found: list[dict] = []
    for page in range(1, _MAX_HISTORY_PAGES + 1):
        page_orders, meta, error = promua.fetch_orders(limit=limit, page=page)
        found.extend(page_orders)
        if error:
            return _within_history(found, _prom_created, cutoff), error
        if (
            not page_orders
            or len(page_orders) < limit
            or _page_reached_cutoff(page_orders, _prom_created, cutoff)
        ):
            break
    return _within_history(found, _prom_created, cutoff), ""


def _epicentr_orders(*, history_days: int | None = None) -> tuple[list[dict], str]:
    if not epicentr.token_configured():
        return [], ""
    limit = max(1, min(100, int(getattr(config, "EPICENTR_IMPORT_LIMIT", 50) or 50)))
    cutoff = _history_cutoff(history_days)
    if cutoff is None:
        orders, _meta, error = epicentr.fetch_orders(limit=limit, cursor=None)
        return orders, error

    found: list[dict] = []
    cursor: str | None = None
    for _page in range(_MAX_HISTORY_PAGES):
        page_orders, meta, error = epicentr.fetch_orders(
            limit=limit,
            cursor=cursor,
            status_codes=(),  # за 7 днів враховуємо і вже завершені
        )
        found.extend(page_orders)
        if error:
            return _within_history(found, _epicentr_created, cutoff), error
        if not page_orders or _page_reached_cutoff(page_orders, _epicentr_created, cutoff):
            break
        next_cursor = str(meta.get("next") or "").strip()
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return _within_history(found, _epicentr_created, cutoff), ""


def _merge_detail(summary: dict, detail: dict | None) -> dict:
    if not isinstance(detail, dict):
        return summary
    merged = dict(summary)
    for key, value in detail.items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        merged[key] = value
    return merged


def _hydrate_missing_rozetka_ttns(orders: list[dict]) -> tuple[list[dict], int, int]:
    hydrated: list[dict] = []
    looked_up = 0
    failures = 0
    for order in orders:
        needs_detail = (
            _rozetka_is_meest(order)
            and not str(order.get("ttn") or "").strip()
            and looked_up < _MAX_HISTORY_DETAIL_LOOKUPS
        )
        if not needs_detail:
            hydrated.append(order)
            continue
        oid = order.get("id")
        if oid is None:
            hydrated.append(order)
            failures += 1
            continue
        looked_up += 1
        try:
            data, error = rozetka.get_order(oid)
            detail = rozetka.order_content(data)
        except Exception:
            detail, error = None, "detail error"
        if error or not isinstance(detail, dict):
            failures += 1
            hydrated.append(order)
        else:
            hydrated.append(_merge_detail(order, detail))
    return hydrated, looked_up, failures


def _hydrate_missing_prom_ttns(orders: list[dict]) -> tuple[list[dict], int, int]:
    hydrated: list[dict] = []
    looked_up = 0
    failures = 0
    for order in orders:
        needs_detail = (
            _prom_is_meest(order)
            and not promua.order_ttn(order)
            and looked_up < _MAX_HISTORY_DETAIL_LOOKUPS
        )
        if not needs_detail:
            hydrated.append(order)
            continue
        oid = promua.order_id(order)
        if oid is None:
            hydrated.append(order)
            failures += 1
            continue
        looked_up += 1
        try:
            detail, error = promua.fetch_order(oid)
        except Exception:
            detail, error = None, "detail error"
        if error or not isinstance(detail, dict):
            failures += 1
            hydrated.append(order)
        else:
            hydrated.append(_merge_detail(order, detail))
    return hydrated, looked_up, failures


def _hydrate_missing_epicentr_ttns(orders: list[dict]) -> tuple[list[dict], int, int]:
    hydrated: list[dict] = []
    looked_up = 0
    failures = 0
    for order in orders:
        # У короткому списку Епіцентру спосіб доставки може називатись
        # «Самовивіз Meest-Епіцентр» або взагалі мати provider=pickup.
        # За 7 днів читаємо деталі всіх рядків без ТТН (до ліміту).
        needs_detail = not epicentr.order_ttn(order) and looked_up < _MAX_HISTORY_DETAIL_LOOKUPS
        if not needs_detail:
            hydrated.append(order)
            continue
        oid = epicentr.order_uuid(order)
        if not oid:
            hydrated.append(order)
            failures += 1
            continue
        looked_up += 1
        try:
            detail, error = epicentr.fetch_order(oid)
        except Exception:
            detail, error = None, "detail error"
        if error or not isinstance(detail, dict):
            failures += 1
            hydrated.append(order)
        else:
            hydrated.append(_merge_detail(order, detail))
    return hydrated, looked_up, failures


def _collect_rozetka(orders: list[dict], rows: list[dict], known_keys: set[str]) -> None:
    for order in orders:
        ttn = str(order.get("ttn") or "").strip()
        if not ttn or not _rozetka_is_meest(order):
            continue
        user = order.get("user") if isinstance(order.get("user"), dict) else {}
        _append_if_new(
            rows,
            known_keys,
            _row(
                ttn=ttn,
                phone=order.get("user_phone") or user.get("phone") or "",
                amount=(
                    order.get("cost_with_discount")
                    or order.get("amount_with_discount")
                    or order.get("cost")
                    or order.get("amount")
                    or 0
                ),
                created=(
                    order.get("created")
                    or order.get("created_at")
                    or order.get("date_created")
                    or ""
                ),
            ),
        )


def _collect_prom(orders: list[dict], rows: list[dict], known_keys: set[str]) -> None:
    for order in orders:
        ttn = promua.order_ttn(order)
        if not ttn or not _prom_is_meest(order):
            continue
        _append_if_new(
            rows,
            known_keys,
            _row(
                ttn=ttn,
                phone=promua.phone(order),
                amount=promua.resolve_order_amount(order),
                created=promua.order_created_display(order),
            ),
        )


def _collect_epicentr(orders: list[dict], rows: list[dict], known_keys: set[str]) -> None:
    for order in orders:
        ttn = epicentr.order_ttn(order)
        if not ttn or not _epicentr_is_meest(order):
            continue
        _append_if_new(
            rows,
            known_keys,
            _row(
                ttn=ttn,
                phone=epicentr.phone(order),
                amount=epicentr.order_amount_display(order),
                created=epicentr.order_created_display(order),
            ),
        )


def collect_marketplace_meest_orders(
    existing_ttns: Iterable,
    *,
    history_days: int | None = None,
) -> MarketplaceMeestDiscovery:
    """Активний список для автоциклу або посторінкова історія за ``history_days``."""
    result = MarketplaceMeestDiscovery()
    known_keys = _identity_keys(existing_ttns)
    sources: tuple[
        tuple[
            str,
            Callable[..., tuple[list[dict], str]],
            Callable[[list[dict], list[dict], set[str]], None],
            Callable[[list[dict]], tuple[list[dict], int, int]],
        ],
        ...,
    ] = (
        ("Rozetka", _rozetka_orders, _collect_rozetka, _hydrate_missing_rozetka_ttns),
        ("Prom.ua", _prom_orders, _collect_prom, _hydrate_missing_prom_ttns),
        ("Епіцентр", _epicentr_orders, _collect_epicentr, _hydrate_missing_epicentr_ttns),
    )

    for source, fetcher, collector, hydrator in sources:
        try:
            orders, error = fetcher(history_days=history_days)
        except Exception as exc:  # збій одного API не блокує два інші
            result.errors.append(f"{source}: {str(exc)[:180]}")
            continue
        result.scanned[source] = len(orders)
        if error:
            result.errors.append(f"{source}: {str(error)[:180]}")
        if history_days is not None and orders:
            orders, looked_up, failures = hydrator(orders)
            result.detail_lookups[source] = looked_up
            result.detail_failures[source] = failures
        before = len(result.rows)
        if orders:
            collector(orders, result.rows, known_keys)
        result.added[source] = len(result.rows) - before

    return result
