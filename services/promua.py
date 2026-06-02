"""Prom.ua API integration (orders import)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import config
import utils
from services import rozetka as rz_delivery

API_BASE = "https://my.prom.ua/api/v1"


def _token() -> str:
    config.apply_prom_secrets()
    return config.get_prom_ua_token() or str(getattr(config, "PROM_UA_TOKEN", "") or "").strip()


def token_configured() -> bool:
    return bool(_token())


def _headers() -> dict[str, str]:
    token = _token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _api_get(path: str, *, params: dict | None = None) -> tuple[dict | None, str]:
    if not token_configured():
        return None, "Немає PROM_UA_TOKEN у Secrets."
    url = f"{API_BASE}{path}"
    r = utils.make_request("GET", url, headers=_headers(), params=params or {}, timeout=45)
    if not r:
        return None, utils.get_last_request_error() or "Немає відповіді від Prom.ua API"
    try:
        data = r.json()
    except Exception:
        return None, f"HTTP {r.status_code}: не JSON"
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}: {data}"
    return data if isinstance(data, dict) else {}, ""


def fetch_orders(*, limit: int = 50, page: int = 1) -> tuple[list[dict], dict, str]:
    """Отримати замовлення Prom.ua (останні)."""
    params = {"limit": max(1, min(200, int(limit))), "page": max(1, int(page))}
    data, err = _api_get("/orders/list", params=params)
    if err:
        return [], {}, err
    if not isinstance(data, dict):
        return [], {}, "Порожня відповідь Prom.ua API"
    items = data.get("orders")
    orders = [o for o in items if isinstance(o, dict)] if isinstance(items, list) else []
    meta = {
        "page": int(data.get("page") or page),
        "pages": int(data.get("pages") or 1),
        "total": int(data.get("total") or len(orders)),
    }
    return orders, meta, ""


def fetch_order(order_id: int | str) -> tuple[dict | None, str]:
    oid = str(order_id or "").strip()
    if not oid:
        return None, "Невірний ID замовлення"
    data, err = _api_get(f"/orders/{oid}")
    if err:
        return None, err
    if isinstance(data, dict) and isinstance(data.get("order"), dict):
        return data["order"], ""
    return data if isinstance(data, dict) else None, ""


def order_id(order: dict) -> int | None:
    raw = order.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _prom_client(order: dict) -> dict:
    client = order.get("client")
    return client if isinstance(client, dict) else {}


def _prom_dict_name(block: Any) -> str:
    if not isinstance(block, dict):
        return str(block or "").strip()
    for key in ("name", "title", "name_uk", "label", "text"):
        val = str(block.get(key) or "").strip()
        if val:
            return val
    return ""


def status_label(order: dict) -> str:
    for key in ("status_name", "status_title", "status_text"):
        val = str(order.get(key) or "").strip()
        if val:
            return val
    status = order.get("status")
    if isinstance(status, dict):
        return _prom_dict_name(status) or str(status.get("id") or "").strip()
    return str(status or "").strip() or "Нове"


def recipient_name(order: dict) -> str:
    client = _prom_client(order)
    parts = [
        str(client.get("first_name") or client.get("firstname") or "").strip(),
        str(client.get("last_name") or client.get("lastname") or "").strip(),
    ]
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    for key in ("client_name", "recipient_name", "customer_name", "buyer_name"):
        val = str(order.get(key) or "").strip()
        if val:
            return val
    return _prom_dict_name(client) or "—"


def delivery_service_raw(order: dict) -> str:
    for key in (
        "delivery_option",
        "delivery_provider",
        "delivery_service",
        "delivery_method",
        "provider",
    ):
        val = order.get(key)
        name = _prom_dict_name(val) if val is not None else str(val or "").strip()
        if name:
            return name
    pdata = order.get("delivery_provider_data")
    if isinstance(pdata, dict):
        for key in ("provider", "name", "title", "delivery_type"):
            name = _prom_dict_name(pdata.get(key)) if isinstance(pdata.get(key), dict) else str(
                pdata.get(key) or ""
            ).strip()
            if name:
                return name
    return ""


def delivery_service_label(order: dict) -> str:
    name = delivery_service_raw(order)
    return name or "Служба доставки не вказана"


def delivery_service_kind(order: dict) -> str:
    return rz_delivery.delivery_service_kind(delivery_service_raw(order))


def delivery_place_hint(order: dict) -> str:
    for key in (
        "delivery_address",
        "warehouse_name",
        "pickup_point",
        "office_name",
        "place_number",
    ):
        val = str(order.get(key) or "").strip()
        if val:
            return val
    pdata = order.get("delivery_provider_data")
    if isinstance(pdata, dict):
        for key in (
            "warehouse_name",
            "pickup_point",
            "office",
            "address",
            "recipient_address",
            "city_name",
        ):
            val = str(pdata.get(key) or "").strip()
            if val:
                return val
    return ""


def payment_label(order: dict) -> str:
    for key in ("payment_option", "payment_method", "payment_type"):
        val = order.get(key)
        name = _prom_dict_name(val) if val is not None else str(val or "").strip()
        if name:
            return name
    return "—"


def payment_status_label(order: dict) -> str:
    for key in ("payment_status", "payment_status_name", "payment_state"):
        val = order.get(key)
        if isinstance(val, dict):
            name = _prom_dict_name(val)
            if name:
                return name
        val = str(val or "").strip()
        if val:
            return val
    if order.get("is_paid") is True:
        return "Оплачено"
    if order.get("is_paid") is False:
        return "Не оплачено"
    return ""


def is_cod_payment_order(order: dict) -> bool:
    pay = payment_label(order).lower()
    return any(x in pay for x in ("післяплат", "налож", "cod", "при отриманні", "накладен"))


def product_title(order: dict) -> str:
    for key in ("products", "order_items", "items", "purchases"):
        items = order.get(key)
        if not isinstance(items, list) or not items:
            continue
        first = items[0]
        if not isinstance(first, dict):
            continue
        for field in ("name", "title", "product_name", "sku"):
            val = str(first.get(field) or "").strip()
            if val:
                return val[:60]
    return ""


def order_ttn(order: dict) -> str:
    for key in (
        "ttn",
        "tracking_number",
        "declaration_id",
        "delivery_declaration",
        "barcode",
    ):
        val = str(order.get(key) or "").strip()
        if val:
            if len(val) == 12 and val.isdigit():
                val = "0" + val
            return val
    return ""


def order_amount_display(order: dict) -> str:
    amount = _prom_amount(order)
    if amount > 0:
        return f"{amount:.2f}".rstrip("0").rstrip(".")
    return "—"


def order_created_display(order: dict) -> str:
    return _prom_date(order)[:16]


def is_ukrposhta_order(order: dict) -> bool:
    return delivery_service_kind(order) == "УП"


def order_detail_payload(order: dict) -> dict:
    """Зведення для блоку «Деталі» (як на Rozetka)."""
    client = _prom_client(order)
    return {
        "id": order.get("id"),
        "status": status_label(order),
        "phone": phone(order),
        "ttn": order_ttn(order),
        "recipient": recipient_name(order),
        "delivery_service": delivery_service_label(order),
        "delivery_place": delivery_place_hint(order),
        "payment_type": payment_label(order),
        "payment_status": payment_status_label(order),
        "amount": order_amount_display(order),
        "number": order.get("number"),
        "products_count": len(order.get("products") or order.get("order_items") or []),
        "client": {
            "first_name": client.get("first_name"),
            "last_name": client.get("last_name"),
            "phone": client.get("phone"),
        },
    }


def phone(order: dict) -> str:
    return _prom_phone(order)


def _prom_phone(order: dict) -> str:
    for key in ("phone", "client_phone", "customer_phone", "receiver_phone"):
        val = utils.clean_phone(str(order.get(key) or "").strip())
        if val:
            return val
    client = order.get("client")
    if isinstance(client, dict):
        for key in ("phone", "phone_number"):
            val = utils.clean_phone(str(client.get(key) or "").strip())
            if val:
                return val
    return ""


def _prom_amount(order: dict) -> float:
    for key in ("price", "total_price", "full_price", "sum", "amount"):
        val = order.get(key)
        try:
            return max(0.0, float(str(val or 0).replace(",", ".")))
        except Exception:
            continue
    return 0.0


def _prom_status(order: dict) -> str:
    status = str(order.get("status") or order.get("status_name") or "").strip()
    if status:
        return status
    return "Нове"


def _prom_date(order: dict) -> str:
    raw = str(order.get("date_created") or order.get("created_at") or order.get("created") or "").strip()
    if not raw:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(raw[:19], fmt[:19]).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
    return raw[:19] if len(raw) >= 19 else raw


def order_to_row(order: dict, *, ttn_override: str = "") -> dict[str, Any]:
    oid = str(order.get("id") or "").strip()
    ttn = str(ttn_override or order_ttn(order) or "").strip()
    if not ttn:
        ttn = f"PROM-{oid}" if oid else f"PROM-{int(datetime.now().timestamp())}"
    return {
        "ТТН": ttn,
        "Служба": "PROM",
        "Статус": _prom_status(order) or "Нове",
        "Дата": _prom_date(order),
        "Телефон": _prom_phone(order),
        "Вартість": _prom_amount(order),
        "Номер накладної": utils.normalize_invoice_number(str(order.get("number") or oid or "")),
        "Чек": "",
        "Повідомлення": f"Prom.ua order #{oid}" if oid else "Prom.ua order",
        "Статус СМС": "",
        "Статус Нагадування": "",
        "Дія": False,
    }
