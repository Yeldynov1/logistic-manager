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


@dataclass
class MarketplaceMeestDiscovery:
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scanned: dict[str, int] = field(default_factory=dict)


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
        page_count = int(meta.get("pages") or page)
        if (
            not page_orders
            or page >= page_count
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


def _collect_rozetka(orders: list[dict], rows: list[dict], known_keys: set[str]) -> None:
    for order in orders:
        service_name, _service_id = rozetka.delivery_service_raw(order)
        if rozetka.delivery_service_kind(service_name) != "Meest":
            continue
        ttn = str(order.get("ttn") or "").strip()
        if not ttn:
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
        if promua.delivery_service_kind(order) != "Meest":
            continue
        ttn = promua.order_ttn(order)
        if not ttn:
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
        if epicentr.delivery_service_kind(order) != "Meest":
            continue
        ttn = epicentr.order_ttn(order)
        if not ttn:
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
        ],
        ...,
    ] = (
        ("Rozetka", _rozetka_orders, _collect_rozetka),
        ("Prom.ua", _prom_orders, _collect_prom),
        ("Епіцентр", _epicentr_orders, _collect_epicentr),
    )

    for source, fetcher, collector in sources:
        try:
            orders, error = fetcher(history_days=history_days)
        except Exception as exc:  # збій одного API не блокує два інші
            result.errors.append(f"{source}: {str(exc)[:180]}")
            continue
        result.scanned[source] = len(orders)
        if error:
            result.errors.append(f"{source}: {str(error)[:180]}")
        if orders:
            collector(orders, result.rows, known_keys)

    return result
