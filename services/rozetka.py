"""Rozetka Seller API — авторизація, замовлення, ТТН."""
from __future__ import annotations

import base64
import re
import time
from typing import Any

import streamlit as st

import config
import utils

# Документація: api.seller… — застарілий хост (nginx 404 HTML); робочий — api-seller…
API_BASE = "https://api-seller.rozetka.com.ua"
_TOKEN_TTL_SEC = 23 * 3600
_ORDER_EXPAND = (
    "user,delivery,delivery_service,status_data,status_available,purchases,total_quantity"
)


def _password_b64(plain: str) -> str:
    return base64.b64encode(plain.encode("utf-8")).decode("ascii")


def credentials_configured() -> bool:
    return bool(config.ROZETKA_USERNAME and config.ROZETKA_PASSWORD)


def _api_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    auth: bool = True,
    timeout: int = 45,
):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth:
        token, err = get_access_token()
        if err:
            return None, err
        headers["Authorization"] = f"Bearer {token}"
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    r = utils.make_request(
        method, url, headers=headers, json=json_body, params=params, timeout=timeout
    )
    if not r:
        return None, utils.get_last_request_error() or "Немає відповіді від Rozetka API"
    try:
        data = r.json()
    except Exception:
        snippet = (getattr(r, "text", None) or "")[:120].strip()
        if r.status_code == 404 and snippet.lstrip().startswith("<"):
            return None, (
                f"HTTP 404: некоректна адреса API ({url}). "
                "Очікується https://api-seller.rozetka.com.ua"
            )
        return None, f"HTTP {r.status_code}: не JSON"
    if r.status_code >= 400:
        msg = data.get("errors", data) if isinstance(data, dict) else r.text
        return None, f"HTTP {r.status_code}: {msg}"
    if isinstance(data, dict) and data.get("success") is False:
        err = data.get("errors") or data.get("message") or "Помилка API"
        return None, str(err)
    return data, ""


def authenticate() -> tuple[str | None, str]:
    """POST /sites — токен на ~24 год."""
    user = config.ROZETKA_USERNAME
    pwd = config.ROZETKA_PASSWORD
    if not user or not pwd:
        return None, "Додайте ROZETKA_USERNAME та ROZETKA_PASSWORD у Secrets."
    data, err = _api_request(
        "POST",
        "/sites",
        json_body={"username": user, "password": _password_b64(pwd)},
        auth=False,
    )
    if err:
        return None, err
    content = (data or {}).get("content") if isinstance(data, dict) else None
    token = ""
    if isinstance(content, dict):
        token = str(content.get("access_token") or "").strip()
    if not token:
        return None, "У відповіді немає access_token."
    st.session_state.rozetka_access_token = token
    st.session_state.rozetka_token_ts = time.time()
    return token, ""


def get_access_token() -> tuple[str | None, str]:
    token = str(st.session_state.get("rozetka_access_token") or "").strip()
    ts = float(st.session_state.get("rozetka_token_ts") or 0)
    if token and (time.time() - ts) < _TOKEN_TTL_SEC:
        return token, ""
    return authenticate()


def search_orders(
    *,
    page: int = 1,
    types: int = 2,
    sort: str = "-id",
    expand: str = _ORDER_EXPAND,
) -> tuple[dict | None, str]:
    """types=2 — замовлення в обробці."""
    params = {
        "page": page,
        "types": types,
        "sort": sort,
        "expand": expand,
    }
    return _api_request("GET", "/orders/search", params=params)


def get_order(order_id: int | str, *, expand: str = _ORDER_EXPAND) -> tuple[dict | None, str]:
    oid = int(order_id)
    return _api_request(
        "GET",
        f"/orders/{oid}",
        params={"expand": expand},
    )


def update_order(
    order_id: int | str,
    *,
    status: int,
    ttn: str = "",
    seller_comment: str = "",
) -> tuple[dict | None, str]:
    body: dict[str, Any] = {"status": int(status)}
    ttn = str(ttn or "").strip()
    if ttn:
        body["ttn"] = ttn
    comment = str(seller_comment or "").strip()
    if comment:
        body["seller_comment"] = comment
    return _api_request("PUT", f"/orders/{int(order_id)}", json_body=body)


def orders_from_search_response(data: dict | None) -> list[dict]:
    if not isinstance(data, dict):
        return []
    content = data.get("content")
    if not isinstance(content, dict):
        return []
    orders = content.get("orders")
    return [o for o in orders if isinstance(o, dict)] if isinstance(orders, list) else []


def search_meta(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    content = data.get("content")
    if not isinstance(content, dict):
        return {}
    meta = content.get("_meta")
    return meta if isinstance(meta, dict) else {}


def order_content(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    return content if isinstance(content, dict) else None


def status_label(order: dict) -> str:
    sd = order.get("status_data")
    if isinstance(sd, dict):
        return str(sd.get("name_uk") or sd.get("name") or "").strip()
    return str(order.get("status") or "")


def split_recipient_name(title: str) -> tuple[str, str, str]:
    parts = str(title or "").strip().split()
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""


def build_up_prefill(order: dict) -> dict:
    """Мапінг замовлення Rozetka → поля майстра УП (частково, за наявними даними)."""
    user = order.get("user") if isinstance(order.get("user"), dict) else {}
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    city = delivery.get("city") if isinstance(delivery.get("city"), dict) else {}

    title = (
        str(delivery.get("recipient_title") or "")
        or str(user.get("title") or user.get("name") or user.get("full_name") or "")
    ).strip()
    last, first, middle = split_recipient_name(title)
    phone = utils.clean_phone(str(order.get("user_phone") or user.get("phone") or ""))

    postcode = re.sub(
        r"\D",
        "",
        str(
            delivery.get("postcode")
            or delivery.get("index")
            or city.get("postcode")
            or city.get("index")
            or ""
        ),
    )[:5]

    region = str(
        city.get("region_title")
        or city.get("region")
        or delivery.get("region")
        or ""
    ).strip()
    city_name = str(city.get("name") or city.get("title") or delivery.get("city_name") or "").strip()
    district = str(city.get("district_title") or delivery.get("district") or "").strip()

    street = str(
        delivery.get("place_street") or delivery.get("street") or user.get("street") or ""
    ).strip()
    house = str(delivery.get("place_house") or delivery.get("house") or "").strip()
    apartment = str(delivery.get("place_flat") or delivery.get("flat") or "").strip()

    oid = order.get("id")
    desc = f"RZ{oid}" if oid else ""
    try:
        declared = float(str(order.get("cost_with_discount") or order.get("amount") or 0).replace(",", "."))
    except ValueError:
        declared = 0.0

    place_number = str(delivery.get("place_number") or "").strip()

    return {
        "rozetka_order_id": oid,
        "lastname": last,
        "firstname": first,
        "middlename": middle,
        "phone": phone,
        "postcode": postcode,
        "region": region,
        "district": district,
        "city": city_name,
        "street": street,
        "house": house,
        "apartment": apartment,
        "place_number": place_number,
        "description": desc[:40],
        "declared_uah": max(0.0, declared),
    }


def apply_up_wizard_prefill(prefill: dict) -> None:
    """Заповнити session_state для майстра УП (вкладка «УП ТТН»)."""
    st.session_state.upwiz_form_open = True
    st.session_state.upwiz_edit_mode = False
    st.session_state.pop("upwiz_edit_barcode", None)
    st.session_state.upwiz_lastname = str(prefill.get("lastname") or "")
    st.session_state.upwiz_firstname = str(prefill.get("firstname") or "")
    st.session_state.upwiz_middlename = str(prefill.get("middlename") or "")
    ph = str(prefill.get("phone") or "").strip()
    st.session_state.upwiz_phone = ph if ph.startswith("+") else (f"+{ph}" if ph else "+38")
    st.session_state.upwiz_postcode = str(prefill.get("postcode") or "")
    st.session_state.upwiz_region = str(prefill.get("region") or "")
    st.session_state.upwiz_district = str(prefill.get("district") or "")
    st.session_state.upwiz_city = str(prefill.get("city") or "")
    st.session_state.upwiz_street = str(prefill.get("street") or "")
    st.session_state.upwiz_house = str(prefill.get("house") or "")
    st.session_state.upwiz_apartment = str(prefill.get("apartment") or "")
    has_street = bool(str(prefill.get("street") or "").strip())
    st.session_state.upwiz_index_mode = "Знайти індекс" if has_street else "Знаю індекс"
    desc = str(prefill.get("description") or "")[:40]
    st.session_state.upwiz_description_stored = desc
    st.session_state.pop("upwiz_desc_widget", None)
    declared = float(prefill.get("declared_uah") or 0)
    st.session_state.upwiz_declared_uah = declared
    st.session_state.upwiz_n_parcels = 1
    st.session_state["upwiz_w_0"] = 500
    st.session_state["upwiz_len_0"] = 30
    st.session_state["upwiz_wid_0"] = 0
    st.session_state["upwiz_h_0"] = 0
    st.session_state["upwiz_decl_0"] = declared
    st.session_state.rozetka_linked_order_id = prefill.get("rozetka_order_id")
    if prefill.get("place_number"):
        st.session_state.rozetka_place_number = prefill.get("place_number")


def statuses_for_ttn(order: dict) -> list[dict]:
    raw = order.get("status_available")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out
