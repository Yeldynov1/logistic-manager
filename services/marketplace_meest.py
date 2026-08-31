"""Автоімпорт Meest-ТТН з активних замовлень маркетплейсів.

Модуль лише читає Rozetka, Prom.ua та Епіцентр. Збереження в Orders
виконує наявний безпечний механізм ``sheets.insert_new_orders``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

import config
import utils
from core.order_identity import order_ttn_match_keys
from services import epicentr, promua, rozetka


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


def _rozetka_orders() -> tuple[list[dict], str]:
    if not rozetka.credentials_configured():
        return [], ""
    data, error = rozetka.search_orders(page=1, types=2)
    return rozetka.orders_from_search_response(data), error


def _prom_orders() -> tuple[list[dict], str]:
    if not promua.token_configured():
        return [], ""
    limit = max(1, min(200, int(getattr(config, "PROM_UA_IMPORT_LIMIT", 50) or 50)))
    orders, _meta, error = promua.fetch_orders(limit=limit, page=1)
    return orders, error


def _epicentr_orders() -> tuple[list[dict], str]:
    if not epicentr.token_configured():
        return [], ""
    limit = max(1, min(100, int(getattr(config, "EPICENTR_IMPORT_LIMIT", 50) or 50)))
    orders, _meta, error = epicentr.fetch_orders(limit=limit, cursor=None)
    return orders, error


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


def collect_marketplace_meest_orders(existing_ttns: Iterable) -> MarketplaceMeestDiscovery:
    """Один обмежений запит списку на кожен налаштований маркетплейс."""
    result = MarketplaceMeestDiscovery()
    known_keys = _identity_keys(existing_ttns)
    sources: tuple[
        tuple[str, Callable[[], tuple[list[dict], str]], Callable[[list[dict], list[dict], set[str]], None]],
        ...,
    ] = (
        ("Rozetka", _rozetka_orders, _collect_rozetka),
        ("Prom.ua", _prom_orders, _collect_prom),
        ("Епіцентр", _epicentr_orders, _collect_epicentr),
    )

    for source, fetcher, collector in sources:
        try:
            orders, error = fetcher()
        except Exception as exc:  # збій одного API не блокує два інші
            result.errors.append(f"{source}: {str(exc)[:180]}")
            continue
        result.scanned[source] = len(orders)
        if error:
            result.errors.append(f"{source}: {str(error)[:180]}")
            continue
        collector(orders, result.rows, known_keys)

    return result
