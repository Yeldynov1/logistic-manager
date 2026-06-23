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
    "user,delivery,delivery_service,status_data,status_available,purchases,total_quantity,"
    "payment_type,payment_type_name,status_payment,payment_status"
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


def delivery_service_raw(order: dict) -> tuple[str, Any]:
    """Назва служби доставки та id з Rozetka (orders + expand delivery_service)."""
    if not isinstance(order, dict):
        return "", None
    ds = order.get("delivery_service")
    name = ""
    ds_id = None
    if isinstance(ds, dict):
        name = str(ds.get("name") or "").strip()
        ds_id = ds.get("id")
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    if not name:
        for key in ("delivery_service_name", "service_name", "delivery_name"):
            name = str(delivery.get(key) or "").strip()
            if name:
                break
    if ds_id is None and delivery.get("delivery_service_id") is not None:
        ds_id = delivery.get("delivery_service_id")
    return name, ds_id


def delivery_service_kind(name: str) -> str:
    """Код служби для UI: УП, НП, Meest, Rozetka, Інше."""
    n = str(name or "").lower()
    if "укр" in n or "ukrposhta" in n or "ukr poshta" in n:
        return "УП"
    if "нов" in n or "nova" in n or re.search(r"\bнп\b", n):
        return "НП"
    if "meest" in n or "міст" in n:
        return "Meest"
    if "rozetka" in n or "розетк" in n:
        return "Rozetka"
    return "Інше"


def delivery_service_label(order: dict) -> str:
    """Повна назва служби доставки для відображення."""
    name, ds_id = delivery_service_raw(order)
    if name:
        return name
    if ds_id is not None:
        return f"Служба доставки #{ds_id}"
    return "Служба доставки не вказана"


def delivery_service_badge(order: dict) -> str:
    """Текстова назва служби (для підказок і журналу)."""
    return delivery_service_label(order)


def is_ukrposhta_order(order: dict) -> bool:
    """Чи замовлення з доставкою Укрпоштою (лише тоді показуємо «Створити УП»)."""
    name, _ = delivery_service_raw(order)
    if not name:
        return False
    return delivery_service_kind(name) == "УП"


def is_ukrposhta_prefill(prefill: dict) -> bool:
    """Перевірка служби з prefill перед автостворенням ТТН."""
    if not isinstance(prefill, dict):
        return False
    carrier = str(prefill.get("shipment_carrier") or "").strip().lower()
    if carrier == "up":
        return True
    svc = str(prefill.get("delivery_service") or "").strip()
    if not svc:
        return False
    return delivery_service_kind(svc) == "УП"


def is_nova_poshta_prefill(prefill: dict) -> bool:
    from services import novaposhta

    return novaposhta.is_nova_poshta_prefill(prefill)


def delivery_place_hint(order: dict) -> str:
    """Відділення / поштомат з delivery.place_number."""
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    place = str(delivery.get("place_number") or "").strip()
    if not place:
        return ""
    method_id = delivery.get("delivery_method_id")
    if method_id == 2:
        return f"курʼєр · {place}"
    return f"відділення №{place}"


_POSTCODE_KEY_RE = re.compile(
    r"postcode|post_code|postindex|post_index|zip|postal|індекс|index",
    re.I,
)


def normalize_postcode(val) -> str:
    """5 цифр індексу України або порожньо."""
    digits = re.sub(r"\D", "", str(val or ""))
    if len(digits) >= 5:
        return digits[:5]
    if len(digits) == 4:
        return "0" + digits
    return ""


def extract_postcode_from_text(text: str) -> str:
    """5-значний індекс з довільного тексту (адреса, назва відділення)."""
    s = str(text or "")
    if not s.strip():
        return ""
    for pat in (
        r"(?i)індекс[:\s]*(\d{4,5})",
        r"(?i)post\s*code[:\s]*(\d{4,5})",
        r"\b(0\d{4})\b",
        r"\b(\d{5})\b",
        r"\b(\d{4})\b",
    ):
        for m in re.finditer(pat, s):
            code = normalize_postcode(m.group(1))
            if len(code) == 5:
                return code
    return ""


def extract_branch_number(*parts: str) -> str:
    """Номер відділення/поштомату (не плутати з 5-значним поштовим індексом)."""
    for blob in parts:
        s = str(blob or "").strip()
        if not s:
            continue
        m = re.search(
            r"(?i)(?:№|#|відділен\w*|отделен\w*|поштомат\w*|postomat)\s*(\d+)",
            s,
        )
        if m:
            n = m.group(1)
            return n.lstrip("0") or n
        if re.fullmatch(r"\d{1,3}", s):
            return s.lstrip("0") or s
    return ""


def postcode_from_place_number(place_number) -> str:
    """
    Індекс з delivery.place_number Rozetka.
    Часто це сам індекс (8371 → 08371) або текст «08371, відділення №3».
    """
    s = str(place_number or "").strip()
    if not s:
        return ""
    pc = extract_postcode_from_text(s)
    if pc:
        return pc
    digits = re.sub(r"\D", "", s)
    if len(digits) in (4, 5):
        return normalize_postcode(digits)
    return ""


def up_postcode_if_known(pc: str) -> tuple[str, dict | None]:
    """Індекс лише якщо його знає класифікатор УП (з варіантами провідного 0)."""
    raw = normalize_postcode(pc)
    if len(raw) != 5:
        return "", None
    try:
        mod = __import__("app", fromlist=["up_resolve_postcode_for_up"])
        resolved, loc, _err = mod.up_resolve_postcode_for_up(raw)
        if resolved:
            return resolved, loc
    except Exception:
        pass
    return "", None


def up_postcode_by_branch(
    city_name: str,
    region_name: str,
    place_number: str,
    *,
    place_street: str = "",
    branch_number: str = "",
) -> tuple[str, dict | None]:
    """Індекс відділення УП за містом і номером відділення (Rozetka place_number)."""
    city_name = str(city_name or "").strip()
    region_name = str(region_name or "").strip()
    place_number = str(place_number or "").strip()
    place_street = str(place_street or "").strip()
    branch_number = str(branch_number or "").strip()
    if not city_name or not (place_number or place_street or branch_number):
        return "", None
    try:
        mod = __import__("app", fromlist=["up_resolve_postcode_by_branch"])
        fn = getattr(mod, "up_resolve_postcode_by_branch", None)
        if fn:
            return fn(
                city_name,
                region_name,
                place_number,
                place_street=place_street,
                branch_number=branch_number,
            )
    except Exception:
        pass
    return "", None


def resolve_postcode_from_prefill(prefill: dict) -> tuple[str, dict | None]:
    """Валідний індекс УП з prefill Rozetka/Prom (індекс або відділення)."""
    if not isinstance(prefill, dict):
        return "", None
    pc = normalize_postcode(prefill.get("postcode"))
    city_name = str(prefill.get("city") or "").strip()
    region_name = str(prefill.get("region") or "").strip()
    place_number = str(prefill.get("place_number") or "").strip()
    place_street = str(
        prefill.get("place_street") or prefill.get("delivery_place_street") or ""
    ).strip()
    branch_number = str(prefill.get("branch_number") or "").strip()
    if not branch_number:
        branch_number = extract_branch_number(place_street, place_number)

    if pc:
        known, loc = up_postcode_if_known(pc)
        if known:
            return known, loc
    if city_name and (branch_number or place_number or place_street):
        pc_branch, loc = up_postcode_by_branch(
            city_name,
            region_name,
            place_number,
            place_street=place_street,
            branch_number=branch_number,
        )
        if pc_branch:
            return pc_branch, loc
    if not pc and place_number:
        candidate = postcode_from_place_number(place_number)
        if candidate:
            known, loc = up_postcode_if_known(candidate)
            if known:
                return known, loc
    return "", None


def resolve_postcode_for_up_execution(prefill: dict) -> tuple[str, dict | None]:
    """Остання спроба визначити індекс перед автостворенням ТТН."""
    pc, loc = resolve_postcode_from_prefill(prefill)
    if pc:
        return pc, loc

    oid = prefill.get("rozetka_order_id")
    if oid is None:
        return "", None
    order, _err = get_order(oid)
    if not isinstance(order, dict):
        return "", None
    fresh = build_up_prefill(order)
    merged = dict(prefill)
    merged.update(
        {
            k: fresh[k]
            for k in (
                "postcode",
                "region",
                "district",
                "city",
                "place_number",
                "place_street",
                "branch_number",
                "delivery_place_street",
            )
            if fresh.get(k)
        }
    )
    return resolve_postcode_from_prefill(merged)


def _postcode_from_delivery_fields(delivery: dict, city: dict) -> str:
    """Індекс з явних полів delivery/city Rozetka."""
    for src in (delivery, city):
        if not isinstance(src, dict):
            continue
        for key in (
            "postcode",
            "post_code",
            "postindex",
            "post_index",
            "zip",
            "postal_code",
            "index",
            "postal",
        ):
            pc = normalize_postcode(src.get(key))
            if pc:
                return pc
    pn_pc = postcode_from_place_number(delivery.get("place_number"))
    if pn_pc:
        return pn_pc
    blobs = (
        delivery.get("place_street"),
        delivery.get("recipient_title"),
        city.get("title"),
        city.get("name"),
        city.get("name_ua"),
    )
    for blob in blobs:
        pc = extract_postcode_from_text(str(blob or ""))
        if pc:
            return pc
    return ""


def fetch_postcode_from_pickup_search(order: dict) -> str:
    """Індекс з каталогу пунктів видачі Rozetka (delivery-service-pickups/search)."""
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    city = delivery.get("city") if isinstance(delivery.get("city"), dict) else {}
    locality_id = city.get("id")
    ds = order.get("delivery_service")
    ds_id = ds.get("id") if isinstance(ds, dict) else delivery.get("delivery_service_id")
    place_id = delivery.get("place_id")
    place_number = str(delivery.get("place_number") or "").strip()
    if locality_id is None or ds_id is None:
        return ""
    params: dict[str, Any] = {
        "locality_id": int(locality_id),
        "delivery_service_id": int(ds_id),
    }
    if place_number:
        params["street"] = place_number
    data, err = _api_request("GET", "/delivery-service-pickups/search", params=params)
    if err or not isinstance(data, dict):
        return ""
    content = data.get("content")
    if not isinstance(content, dict):
        return ""
    pickups = content.get("deliveryServicePickups")
    if not isinstance(pickups, list):
        return ""
    for pickup in pickups:
        if not isinstance(pickup, dict):
            continue
        if place_id is not None and pickup.get("place_id") not in (None, place_id):
            continue
        for key in (
            "postindex",
            "post_index",
            "postcode",
            "post_code",
            "zip",
            "postal_code",
            "index",
        ):
            pc = normalize_postcode(pickup.get(key))
            if pc:
                return pc
        for field in ("title", "street", "house", "pickup_number", "number"):
            pc = extract_postcode_from_text(str(pickup.get(field) or ""))
            if pc:
                return pc
    return ""


def resolve_rozetka_postcode(order: dict) -> str:
    """Повний пошук індексу в замовленні Rozetka (лише якщо УП знає індекс)."""
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    city = delivery.get("city") if isinstance(delivery.get("city"), dict) else {}
    place_number = str(delivery.get("place_number") or "").strip()
    city_name = str(city.get("name") or city.get("title") or delivery.get("city_name") or "").strip()
    region = str(
        city.get("region_title") or city.get("region") or delivery.get("region") or ""
    ).strip()

    candidates: list[str] = []

    def _add(pc: str) -> None:
        pc = normalize_postcode(pc)
        if len(pc) == 5 and pc not in candidates:
            candidates.append(pc)

    _add(postcode_from_place_number(place_number))
    order_pc = extract_postcode_from_order(order) or _postcode_from_delivery_fields(delivery, city)
    _add(order_pc or "")

    for pc in candidates:
        known, _loc = up_postcode_if_known(pc)
        if known:
            return known

    pc_pickup = fetch_postcode_from_pickup_search(order)
    if pc_pickup:
        known, _loc = up_postcode_if_known(pc_pickup)
        if known:
            return known

    branch_number = extract_branch_number(
        delivery.get("place_street"),
        place_number,
        delivery.get("recipient_title"),
    )
    if city_name and (branch_number or place_number or delivery.get("place_street")):
        pc_branch, _loc = up_postcode_by_branch(
            city_name,
            region,
            place_number,
            place_street=str(delivery.get("place_street") or ""),
            branch_number=branch_number,
        )
        if pc_branch:
            return pc_branch

    return ""


_SKIP_POSTCODE_KEYS = frozenset(
    {
        "user_phone",
        "phone",
        "phonenumber",
        "id",
        "market_id",
        "ttn",
        "amount",
        "cost",
        "cost_with_discount",
        "amount_with_discount",
        "total_quantity",
        "payment_invoice_id",
    }
)


def extract_postcode_from_order(order: dict) -> str:
    """Індекс з полів Rozetka (у API часто немає окремого postcode — шукаємо в тексті)."""
    if not isinstance(order, dict):
        return ""

    def _from_text(text: str) -> str:
        return extract_postcode_from_text(text)

    priority_keys = (
        "postcode",
        "post_code",
        "postindex",
        "post_index",
        "zip",
        "postal_code",
        "index",
        "postal",
    )

    def _walk(obj, depth: int = 0) -> str:
        if depth > 10:
            return ""
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if kl in _SKIP_POSTCODE_KEYS:
                    continue
                if any(pk in kl for pk in priority_keys) or _POSTCODE_KEY_RE.search(kl):
                    pc = normalize_postcode(v)
                    if pc:
                        return pc
            for v in obj.values():
                pc = _walk(v, depth + 1)
                if pc:
                    return pc
        elif isinstance(obj, list):
            for item in obj:
                pc = _walk(item, depth + 1)
                if pc:
                    return pc
        elif isinstance(obj, str):
            return _from_text(obj)
        return ""

    pc = _walk(order)
    if pc:
        return pc

    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    pn_pc = postcode_from_place_number(delivery.get("place_number"))
    if pn_pc:
        return pn_pc
    for blob in (
        delivery.get("place_street"),
        delivery.get("recipient_title"),
        (delivery.get("city") or {}).get("title") if isinstance(delivery.get("city"), dict) else "",
    ):
        pc = _from_text(str(blob or ""))
        if pc:
            return pc
    return ""


def fetch_ttns_user_info(order_id: int | str) -> tuple[dict, str]:
    """Додаткові поля адреси (часто для НП/УП модулів Rozetka)."""
    data, err = _api_request("GET", f"/ttns/get-user-info/{int(order_id)}")
    if err:
        return {}, err
    if not isinstance(data, dict):
        return {}, ""
    content = data.get("content")
    return (content if isinstance(content, dict) else {}), ""


def split_recipient_name(title: str) -> tuple[str, str, str]:
    parts = str(title or "").strip().split()
    if len(parts) >= 3:
        return parts[0], parts[1], " ".join(parts[2:])
    if len(parts) == 2:
        return parts[0], parts[1], ""
    if len(parts) == 1:
        return parts[0], "", ""
    return "", "", ""


def _rozetka_money(val) -> float:
    try:
        return max(0.0, float(str(val or 0).replace(",", ".").replace(" ", "")))
    except (TypeError, ValueError):
        return 0.0


def _payment_status_blob(order: dict) -> str:
    parts: list[str] = []
    sp = order.get("status_payment")
    if isinstance(sp, dict):
        for key in ("name", "title", "name_uk", "name_en"):
            parts.append(str(sp.get(key) or ""))
        for key in ("is_paid", "paid"):
            if sp.get(key) is not None:
                parts.append(str(sp.get(key)))
    ps = order.get("payment_status")
    if isinstance(ps, dict):
        for key in ("name", "title", "name_uk", "name_en"):
            parts.append(str(ps.get(key) or ""))
    else:
        parts.append(str(ps or ""))
    return " ".join(parts).lower()


def _order_payment_paid(order: dict) -> bool:
    blob = _payment_status_blob(order)
    if not blob.strip():
        return False
    if any(
        m in blob
        for m in (
            "не оплач",
            "неоплач",
            "not paid",
            "not_paid",
            "unpaid",
            "очіку",
            "ожида",
            "waiting",
            "pending",
        )
    ):
        return False
    if any(m in blob for m in ("false", "0", "no")) and "paid" in blob:
        return False
    return any(
        m in blob
        for m in (
            "оплачено",
            "оплачен",
            "paid",
            "success",
            "completed",
        )
    )


def _payment_type_blob(pt_raw, pt_name: str = "") -> str:
    return f"{str(pt_raw or '').strip().lower()} {str(pt_name or '').lower()}".strip()


def _is_seller_account_payment(pt_raw, pt_name: str = "") -> bool:
    """Оплата на рахунок продавця / безготівка — без післяплати в УП."""
    blob = _payment_type_blob(pt_raw, pt_name)
    if not blob:
        return False
    return any(
        m in blob
        for m in (
            "рахунок продавця",
            "на рахунок продав",
            "оплата на рахунок",
            "seller account",
            "to seller",
            "безготів",
            "безнал",
            "cashless",
            "переказ на рахунок",
        )
    )


def _is_cash_payment_marker(pt_raw, pt_name: str = "") -> bool:
    if _is_seller_account_payment(pt_raw, pt_name):
        return False
    pt_s = str(pt_raw or "").strip().lower()
    if pt_s in ("cash", "cod", "payment_on_delivery", "on_delivery"):
        return True
    try:
        if int(pt_raw) == 1:
            return True
    except (TypeError, ValueError):
        pass
    blob = _payment_type_blob(pt_raw, pt_name)
    if not blob:
        return False
    if "cashless" in blob or "безнал" in blob or "безготів" in blob:
        return False
    if any(m in blob for m in ("card", "rozetkapay", "liqpay", "карт", "онлайн")):
        return False
    return any(
        m in blob
        for m in (
            "cash",
            "готів",
            "отриман",
            "при получ",
            "налож",
            "післясплат",
        )
    )


def is_cod_payment_order(order: dict, extra: dict | None = None) -> bool:
    """Оплата під час отримання (готівка / післяплата для УП)."""
    if _order_payment_paid(order):
        return False
    extra = extra if isinstance(extra, dict) else {}
    pt = order.get("payment_type")
    pt_name = order.get("payment_type_name")
    if _is_seller_account_payment(pt, pt_name):
        return False
    pm = str(extra.get("payment_method") or "").strip().lower()
    if pm and _is_seller_account_payment(pm, ""):
        return False
    if pm in ("cash", "cod", "1") or _is_cash_payment_marker(pm):
        return True
    inv = order.get("payment_invoice_id")
    if inv not in (None, "", 0, "0") and not _is_cash_payment_marker(pt, pt_name):
        return False
    return _is_cash_payment_marker(pt, pt_name)


def postpay_uah_from_order(order: dict, extra: dict | None = None) -> float:
    """Сума післяплати для УП — лише для COD (готівка / при отриманні)."""
    if not is_cod_payment_order(order, extra):
        return 0.0
    extra = extra if isinstance(extra, dict) else {}
    for src in (extra, order):
        cod = _rozetka_money(src.get("cod_amount"))
        if cod >= 1.0:
            return cod
    order_amount = _rozetka_money(
        order.get("cost_with_discount")
        or order.get("cost")
        or order.get("amount_with_discount")
        or order.get("amount")
    )
    extra_amount = _rozetka_money(extra.get("amount"))
    if order_amount >= 1.0:
        return order_amount
    if extra_amount >= 1.0:
        return extra_amount
    return 0.0


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

    region = str(
        city.get("region_title")
        or city.get("region")
        or delivery.get("region")
        or ""
    ).strip()
    city_name = str(city.get("name") or city.get("title") or delivery.get("city_name") or "").strip()
    district = str(city.get("district_title") or delivery.get("district") or "").strip()

    place_street_raw = str(
        delivery.get("place_street") or delivery.get("street") or user.get("street") or ""
    ).strip()
    street = place_street_raw
    house = str(delivery.get("place_house") or delivery.get("house") or "").strip()
    apartment = str(delivery.get("place_flat") or delivery.get("flat") or "").strip()

    oid = order.get("id")
    place_number = str(delivery.get("place_number") or "").strip()
    branch_number = extract_branch_number(
        place_street_raw,
        place_number,
        delivery.get("recipient_title"),
    )

    desc = f"RZ{oid}" if oid else ""
    try:
        declared = float(str(order.get("cost_with_discount") or order.get("amount") or 0).replace(",", "."))
    except ValueError:
        declared = 0.0

    ttns_extra: dict = {}
    postcode = ""
    if oid is not None and (not street or is_ukrposhta_order(order)):
        ttns_extra, _ = fetch_ttns_user_info(oid)
        if ttns_extra:
            if not street:
                street = str(ttns_extra.get("street") or street or "").strip()
            if not region:
                region = str(
                    ttns_extra.get("region") or ttns_extra.get("area") or region or ""
                ).strip()
            if not city_name:
                city_name = str(ttns_extra.get("city_name") or city_name or "").strip()
            if not house:
                house = str(ttns_extra.get("place_house") or house or "").strip()
            if not apartment:
                apartment = str(ttns_extra.get("place_flat") or apartment or "").strip()
            if not place_number:
                place_number = str(ttns_extra.get("place_number") or place_number or "").strip()
            order = dict(order)
            order["_ttns_user_info"] = ttns_extra

    postpay = postpay_uah_from_order(order, ttns_extra)

    postcode = resolve_rozetka_postcode(order)
    if not postcode and isinstance(order.get("_ttns_user_info"), dict):
        extra = order["_ttns_user_info"]
        for raw in (
            postcode_from_place_number(extra.get("place_number")),
            extract_postcode_from_order(extra),
            normalize_postcode(extra.get("postcode") or extra.get("post_index")),
        ):
            known, _loc = up_postcode_if_known(raw)
            if known:
                postcode = known
                break
        if not postcode and city_name:
            pn_extra = str(extra.get("place_number") or place_number or "").strip()
            ps_extra = str(extra.get("place_street") or place_street_raw or "").strip()
            br_extra = extract_branch_number(
                ps_extra, pn_extra, extra.get("recipient_title")
            )
            if pn_extra or ps_extra or br_extra:
                pc_branch, _loc = up_postcode_by_branch(
                    city_name,
                    region,
                    pn_extra,
                    place_street=ps_extra,
                    branch_number=br_extra,
                )
                if pc_branch:
                    postcode = pc_branch

    if postcode and (not region or not city_name):
        try:
            mod = __import__("app", fromlist=["up_lookup_by_postcode"])
            loc, _ = mod.up_lookup_by_postcode(postcode)
            if loc:
                if not region:
                    region = str(loc.get("region") or region)
                if not district:
                    district = str(loc.get("district") or district)
                if not city_name:
                    city_name = str(loc.get("city") or city_name)
        except Exception:
            pass

    # Для Rozetka "доставка у відділення" інколи приходить із place_street,
    # що помилково веде до W2D. Якщо є номер відділення і немає квартири/будинку
    # (або в place_number явний маркер відділення/поштомату) — примусово W2W.
    place_hint = str(place_number or "").lower()
    explicit_branch_marker = any(
        m in place_hint for m in ("відділен", "отделен", "поштомат", "postomat", "№")
    )
    delivery_to_branch = bool(place_number) and (
        explicit_branch_marker or (not house and not apartment)
    )
    if delivery_to_branch:
        street = ""
        house = ""
        apartment = ""

    return {
        "rozetka_order_id": oid,
        "delivery_service": str(
            (order.get("delivery_service") or {}).get("name")
            if isinstance(order.get("delivery_service"), dict)
            else ""
        ).strip(),
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
        "place_street": place_street_raw,
        "delivery_place_street": place_street_raw,
        "branch_number": branch_number,
        "delivery_to_branch": delivery_to_branch,
        "description": desc[:40],
        "declared_uah": max(0.0, declared),
        "postpay_uah": postpay,
        "payment_type": str(order.get("payment_type") or "").strip(),
        "payment_type_name": str(order.get("payment_type_name") or "").strip(),
        "payment_method": str(ttns_extra.get("payment_method") or "").strip(),
    }


def draft_shipment_code(order_id) -> str:
    """Застарілий псевдо-код (лише для сумісності сесії). Не є ШКІ Укрпошти."""
    return f"RZ{int(order_id)}"


def draft_row_label(order_id) -> str:
    """Підпис у списку до створення ТТН (офіційний ШКІ — після «Створити»)."""
    return f"Rozetka #{int(order_id)}"


def is_draft_journal_code(bc: str) -> bool:
    """Старі чернетки з псевдо-кодом RZ… у колонці ШКІ."""
    return bool(re.fullmatch(r"RZ\d+", str(bc or "").strip(), flags=re.IGNORECASE))


def _draft_order_key(prefill: dict) -> str:
    epic_id = str(prefill.get("epicentr_order_id") or "").strip()
    if epic_id:
        return epic_id
    oid = prefill.get("rozetka_order_id")
    if oid is None:
        oid = prefill.get("prom_order_id")
    if oid is None:
        return ""
    try:
        return str(int(oid))
    except (TypeError, ValueError):
        return str(oid).strip()


def description_from_prefill(prefill: dict) -> str:
    """Текст для «Дод. інфо» / опису УП: номер накладної або PM#/RZ# замовлення."""
    inv = utils.normalize_invoice_number(str(prefill.get("invoice_number") or "").strip())
    if inv:
        return inv[:40]
    if prefill.get("epicentr_order_id"):
        num = str(prefill.get("epicentr_order_number") or "").strip()
        if num:
            return f"EP{num}"[:40]
        return str(prefill.get("epicentr_order_id") or "")[:40]
    if prefill.get("prom_order_id") is not None:
        return f"PM{int(prefill['prom_order_id'])}"[:40]
    oid = prefill.get("rozetka_order_id")
    if oid is not None:
        return f"RZ{int(oid)}"[:40]
    return str(prefill.get("description") or "")[:40]


def _persist_invoice_to_orders_table(prefill: dict) -> bool:
    """Записати номер накладної в Google-таблицю Orders (за телефоном, якщо рядок уже є)."""
    inv = str(prefill.get("invoice_number") or "").strip()
    if not inv:
        return False
    df = st.session_state.get("df")
    if df is None or getattr(df, "empty", True):
        return False
    if "Номер накладної" not in df.columns:
        return False
    phone = utils.clean_phone(str(prefill.get("phone") or ""))
    if not phone:
        return False
    changed = False
    for idx in df.index:
        row_phone = utils.clean_phone(str(df.at[idx, "Телефон"] if "Телефон" in df.columns else ""))
        if row_phone != phone:
            continue
        cur = str(df.at[idx, "Номер накладної"]).strip()
        if cur and cur.lower() != "nan":
            continue
        df.at[idx, "Номер накладної"] = inv
        changed = True
    if not changed:
        return False
    try:
        from core.messages import ensure_messages_exist
        import sheets

        st.session_state.df = ensure_messages_exist(df)
        return bool(sheets.save_manual(st.session_state.df))
    except Exception:
        return False


def merge_invoice_into_prefill(
    prefill: dict, invoice_raw: str, *, register_draft: bool = True
) -> dict:
    """Додати номер накладної в prefill; чернетка — лише якщо register_draft."""
    out = dict(prefill)
    inv = utils.normalize_invoice_number(str(invoice_raw or "").strip())
    if inv:
        out["invoice_number"] = inv
    out["description"] = description_from_prefill(out)
    if register_draft:
        register_up_journal_draft(out)
    oid = out.get("rozetka_order_id")
    if oid is not None and inv:
        by_oid = st.session_state.setdefault("rozetka_invoice_by_order", {})
        if isinstance(by_oid, dict):
            by_oid[str(int(oid))] = inv
    if inv:
        _persist_invoice_to_orders_table(out)
    return out


def merge_dialog_inputs_into_prefill(
    prefill: dict,
    *,
    invoice_raw: str,
    weight_g=None,
    weight_kg=None,
    length_cm,
    width_cm,
    height_cm,
    register_draft: bool = True,
) -> dict:
    """Оновити prefill із даних діалогу Rozetka (накладна + габарити + вага)."""
    out = merge_invoice_into_prefill(prefill, invoice_raw, register_draft=register_draft)
    if weight_kg is not None:
        try:
            kg = float(weight_kg)
        except Exception:
            kg = 0.5
        kg = max(0.1, min(30.0, kg))
        out["weight_kg"] = kg
        out["weight_g"] = max(1, min(30000, int(round(kg * 1000))))
    else:
        try:
            w = int(weight_g if weight_g is not None else 500)
        except Exception:
            w = 500
        out["weight_g"] = max(1, min(30000, w))
    try:
        ln = int(length_cm)
    except Exception:
        ln = 30
    try:
        wid = int(width_cm)
    except Exception:
        wid = 20
    try:
        hgt = int(height_cm)
    except Exception:
        hgt = 10
    out["length_cm"] = max(1, min(200, ln))
    out["width_cm"] = max(1, min(200, wid))
    out["height_cm"] = max(1, min(200, hgt))
    if register_draft:
        register_up_journal_draft(out)
    return out


def register_up_journal_draft(prefill: dict) -> None:
    """Чернетка в списку «створених» на вкладці УП ТТН (до натискання «Створити»)."""
    oid_s = _draft_order_key(prefill)
    if not oid_s:
        return
    last = str(prefill.get("lastname") or "").strip()
    first = str(prefill.get("firstname") or "").strip()
    middle = str(prefill.get("middlename") or "").strip()
    recipient = " ".join(p for p in (last, first, middle) if p).strip() or "—"
    phone = str(prefill.get("phone") or "").strip()
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    desc = description_from_prefill(prefill)
    try:
        declared = float(prefill.get("declared_uah") or 0)
    except (TypeError, ValueError):
        declared = 0.0
    declared_s = f"{declared:.0f}" if declared else ""
    try:
        postpay = float(prefill.get("postpay_uah") or 0)
    except (TypeError, ValueError):
        postpay = 0.0
    postpay_s = f"{postpay:.0f}" if postpay >= 1 else ""
    user = str(st.session_state.get("auth_user", "") or "?")
    svc = str(prefill.get("delivery_service") or "").strip()
    postcode = normalize_postcode(prefill.get("postcode"))
    city = str(prefill.get("city") or "").strip()[:80]
    row = {
        "Час": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
        "Користувач": user[:80],
        "ШКІ": "",
        "UUID": "",
        "Статус УП": "DRAFT",
        "Отримувач": recipient[:120],
        "Телефон": phone,
        "Тариф": "Базовий",
        "Доставка": (
            (
                f"Епіцентр{(' · ' + svc) if svc else ''}"
                if prefill.get("epicentr_order_id")
                else f"Rozetka{(' · ' + svc) if svc else ''}"
            )
        )[:80],
        "Вартість": declared_s,
        "Післяплата": postpay_s,
        "Дод. інфо": desc,
        "JSON": "",
        "Індекс": postcode if len(postcode) == 5 else "",
        "Місто": city,
    }
    drafts = st.session_state.setdefault("_up_journal_drafts", {})
    drafts[oid_s] = {"row": row, "prefill": dict(prefill)}


def clear_up_journal_draft(order_id) -> None:
    if order_id is None:
        return
    drafts = st.session_state.get("_up_journal_drafts")
    if isinstance(drafts, dict):
        key = str(order_id).strip()
        if key:
            drafts.pop(key, None)
        try:
            drafts.pop(str(int(order_id)), None)
        except (TypeError, ValueError):
            pass


def draft_journal_entries() -> list[dict]:
    drafts = st.session_state.get("_up_journal_drafts")
    if not isinstance(drafts, dict):
        return []
    out = []
    for oid_s, item in drafts.items():
        if not isinstance(item, dict):
            continue
        row = item.get("row")
        if isinstance(row, dict):
            row = dict(row)
            bc = str(row.get("ШКІ") or "").strip()
            if is_draft_journal_code(bc):
                row["ШКІ"] = ""
            out.append(
                {
                    "oid": oid_s,
                    "row": row,
                    "prefill": item.get("prefill") if isinstance(item.get("prefill"), dict) else {},
                }
            )
    return out


def apply_up_wizard_prefill(
    prefill: dict, *, register_draft: bool = False, open_form: bool = True
) -> None:
    """Заповнити session_state для майстра УП (вкладка «УП ТТН»)."""
    if register_draft:
        register_up_journal_draft(prefill)
    st.session_state.up_journal_selected_day = utils.today_kyiv()
    st.session_state.upwiz_form_open = open_form
    st.session_state.upwiz_edit_mode = False
    st.session_state.pop("upwiz_edit_barcode", None)
    st.session_state.upwiz_lastname = str(prefill.get("lastname") or "")
    st.session_state.upwiz_firstname = str(prefill.get("firstname") or "")
    middle = str(prefill.get("middlename") or "").strip()
    if (
        not middle
        and _rozetka_money(prefill.get("postpay_uah")) >= 1
        and (
            prefill.get("prom_order_id") is not None
            or prefill.get("epicentr_order_id")
        )
    ):
        from services.promua import PROM_UP_DEFAULT_MIDDLENAME

        middle = PROM_UP_DEFAULT_MIDDLENAME
    st.session_state.upwiz_middlename = middle
    st.session_state.pop("upwiz_recipient_uuid_created", None)
    st.session_state.pop("upwiz_recipient_fp", None)
    ph = str(prefill.get("phone") or "").strip()
    st.session_state.upwiz_phone = ph if ph.startswith("+") else (f"+{ph}" if ph else "+38")
    st.session_state.rozetka_last_prefill = dict(prefill)
    st.session_state.upwiz_region = str(prefill.get("region") or "")
    st.session_state.upwiz_district = str(prefill.get("district") or "")
    st.session_state.upwiz_city = str(prefill.get("city") or "")
    pc, loc = resolve_postcode_from_prefill(prefill)
    if not pc and prefill.get("prom_order_id") is None and not prefill.get("epicentr_order_id"):
        raw_pn = postcode_from_place_number(prefill.get("place_number"))
        pc, loc = up_postcode_if_known(raw_pn)
    if not pc:
        pc = normalize_postcode(prefill.get("postcode"))
    st.session_state.upwiz_postcode_value = pc
    if pc:
        st.session_state.pop("upwiz_postcode", None)
    if loc:
        if loc.get("region"):
            st.session_state.upwiz_region = str(loc.get("region") or "")
        if loc.get("district"):
            st.session_state.upwiz_district = str(loc.get("district") or "")
        if loc.get("city"):
            st.session_state.upwiz_city = str(loc.get("city") or "")
    pc = re.sub(r"\D", "", str(pc or ""))[:5]
    lookup_ok = bool(loc) and len(pc) == 5
    st.session_state.upwiz_postcode_lookup_ok = lookup_ok
    st.session_state.upwiz_postcode_lookup_last = pc if len(pc) == 5 else ""
    st.session_state.upwiz_street = str(prefill.get("street") or "")
    st.session_state.upwiz_house = str(prefill.get("house") or "")
    st.session_state.upwiz_apartment = str(prefill.get("apartment") or "")
    place_number = str(prefill.get("place_number") or "").strip()
    has_street = bool(str(prefill.get("street") or "").strip())
    to_branch = bool(prefill.get("delivery_to_branch"))
    st.session_state.upwiz_index_mode = "Знаю індекс"
    st.session_state.upwiz_sms = True
    st.session_state.upwiz_paid_shipment_who = "Одержувач"
    st.session_state.upwiz_paid_postpay_who = "Одержувач"
    st.session_state.upwiz_paid_shipment_recipient = True
    st.session_state.upwiz_paid_postpay_recipient = True
    st.session_state.upwiz_check_delivery = True
    # ВАЖЛИВО: завжди явно задаємо тип доставки для prefill,
    # щоб не залипав попередній вибір користувача із session_state.
    if to_branch or place_number:
        st.session_state.upwiz_address_note = f"Відділення/поштомат №{place_number}"[:255]
        st.session_state.upwiz_delivery_label = "склад – склад"
    else:
        st.session_state.pop("upwiz_address_note", None)
        st.session_state.upwiz_delivery_label = "склад – двері" if has_street else "склад – склад"
    desc = description_from_prefill(prefill)
    st.session_state.upwiz_description_stored = desc
    st.session_state.pop("upwiz_desc_widget", None)
    declared = float(prefill.get("declared_uah") or 0)
    st.session_state.upwiz_declared_uah = declared
    postpay = _rozetka_money(prefill.get("postpay_uah"))
    if _is_seller_account_payment(
        prefill.get("payment_type"), prefill.get("payment_type_name")
    ):
        postpay = 0.0
    if postpay >= 1:
        st.session_state.pop("upwiz_postpay_uah", None)
    st.session_state.upwiz_postpay_uah = postpay
    st.session_state.upwiz_transfer_postpay_iban = postpay >= 1
    st.session_state.upwiz_n_parcels = 1
    try:
        w = int(prefill.get("weight_g") or 500)
    except Exception:
        w = 500
    try:
        ln = int(prefill.get("length_cm") or 30)
    except Exception:
        ln = 30
    try:
        wid = int(prefill.get("width_cm") or 20)
    except Exception:
        wid = 20
    try:
        hgt = int(prefill.get("height_cm") or 10)
    except Exception:
        hgt = 10
    st.session_state["upwiz_w_0"] = max(1, min(30000, w))
    st.session_state["upwiz_len_0"] = max(1, min(200, ln))
    st.session_state["upwiz_wid_0"] = max(1, min(200, wid))
    st.session_state["upwiz_h_0"] = max(1, min(200, hgt))
    st.session_state["upwiz_decl_0"] = declared
    st.session_state.rozetka_linked_order_id = (
        prefill.get("epicentr_order_number")
        or prefill.get("rozetka_order_id")
        or prefill.get("prom_order_id")
        or prefill.get("epicentr_order_id")
    )
    if prefill.get("place_number"):
        st.session_state.rozetka_place_number = prefill.get("place_number")


def run_up_create_from_prefill(prefill: dict) -> dict:
    """Виклик створення ТТН УП (lazy import app — працює з вкладки Rozetka)."""
    import sys

    mod = sys.modules.get("app")
    if mod is None or not hasattr(mod, "execute_rozetka_up_create"):
        mod = sys.modules.get("__main__")
    fn = getattr(mod, "execute_rozetka_up_create", None) if mod else None
    if fn is None:
        return {
            "ok": False,
            "err": "Модуль створення УП недоступний — зробіть Reboot app.",
            "bc": "",
            "oid": prefill.get("rozetka_order_id") or prefill.get("prom_order_id"),
        }
    return fn(prefill)


def statuses_for_ttn(order: dict) -> list[dict]:
    raw = order.get("status_available")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out
