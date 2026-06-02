"""Prom.ua API integration (orders import)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import config
import utils

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


def order_to_row(order: dict) -> dict[str, Any]:
    oid = str(order.get("id") or "").strip()
    ttn = str(order.get("ttn") or order.get("tracking_number") or "").strip()
    if len(ttn) == 12 and ttn.isdigit():
        ttn = "0" + ttn
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
