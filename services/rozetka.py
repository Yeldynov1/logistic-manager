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
    svc = str(prefill.get("delivery_service") or "").strip()
    if not svc:
        return False
    return delivery_service_kind(svc) == "УП"


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
        for field in ("title", "street", "house", "pickup_number", "number"):
            pc = extract_postcode_from_text(str(pickup.get(field) or ""))
            if pc:
                return pc
    return ""


def resolve_rozetka_postcode(order: dict) -> str:
    """Повний пошук індексу в замовленні Rozetka (API + текст + відділення УП)."""
    delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
    city = delivery.get("city") if isinstance(delivery.get("city"), dict) else {}
    place_number = str(delivery.get("place_number") or "").strip()
    postcode = postcode_from_place_number(place_number)
    if not postcode:
        postcode = extract_postcode_from_order(order) or _postcode_from_delivery_fields(
            delivery, city
        )
    if postcode:
        return postcode
    postcode = fetch_postcode_from_pickup_search(order)
    if postcode:
        return postcode
    city_name = str(city.get("name") or city.get("title") or delivery.get("city_name") or "").strip()
    region = str(
        city.get("region_title") or city.get("region") or delivery.get("region") or ""
    ).strip()
    if place_number and city_name:
        mod = __import__("app", fromlist=["up_resolve_postcode_by_branch"])
        fn = getattr(mod, "up_resolve_postcode_by_branch", None)
        if fn:
            pc, _loc = fn(city_name, region, place_number)
            if pc:
                return pc
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

    street = str(
        delivery.get("place_street") or delivery.get("street") or user.get("street") or ""
    ).strip()
    house = str(delivery.get("place_house") or delivery.get("house") or "").strip()
    apartment = str(delivery.get("place_flat") or delivery.get("flat") or "").strip()

    oid = order.get("id")
    place_number = str(delivery.get("place_number") or "").strip()

    desc = f"RZ{oid}" if oid else ""
    try:
        declared = float(str(order.get("cost_with_discount") or order.get("amount") or 0).replace(",", "."))
    except ValueError:
        declared = 0.0

    postcode = ""
    if oid is not None and (not street or is_ukrposhta_order(order)):
        extra, _ = fetch_ttns_user_info(oid)
        if extra:
            if not street:
                street = str(extra.get("street") or street or "").strip()
            if not region:
                region = str(
                    extra.get("region") or extra.get("area") or region or ""
                ).strip()
            if not city_name:
                city_name = str(extra.get("city_name") or city_name or "").strip()
            if not house:
                house = str(extra.get("place_house") or house or "").strip()
            if not apartment:
                apartment = str(extra.get("place_flat") or apartment or "").strip()
            if not place_number:
                place_number = str(extra.get("place_number") or place_number or "").strip()
            order = dict(order)
            order["_ttns_user_info"] = extra

    postcode = resolve_rozetka_postcode(order)
    if not postcode and place_number:
        postcode = postcode_from_place_number(place_number)
    if not postcode and isinstance(order.get("_ttns_user_info"), dict):
        extra = order["_ttns_user_info"]
        postcode = (
            postcode_from_place_number(extra.get("place_number"))
            or extract_postcode_from_order(extra)
            or normalize_postcode(extra.get("postcode") or extra.get("post_index"))
        )

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
        "description": desc[:40],
        "declared_uah": max(0.0, declared),
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


def register_up_journal_draft(prefill: dict) -> None:
    """Чернетка в списку «створених» на вкладці УП ТТН (до натискання «Створити»)."""
    oid = prefill.get("rozetka_order_id")
    if oid is None:
        return
    oid_s = str(int(oid))
    last = str(prefill.get("lastname") or "").strip()
    first = str(prefill.get("firstname") or "").strip()
    middle = str(prefill.get("middlename") or "").strip()
    recipient = " ".join(p for p in (last, first, middle) if p).strip() or "—"
    phone = str(prefill.get("phone") or "").strip()
    if phone and not phone.startswith("+"):
        phone = f"+{phone}"
    desc = str(prefill.get("description") or "")[:40]
    try:
        declared = float(prefill.get("declared_uah") or 0)
    except (TypeError, ValueError):
        declared = 0.0
    declared_s = f"{declared:.0f}" if declared else ""
    user = str(st.session_state.get("auth_user", "") or "?")
    svc = str(prefill.get("delivery_service") or "").strip()
    row = {
        "Час": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
        "Користувач": user[:80],
        "ШКІ": "",
        "UUID": "",
        "Статус УП": "DRAFT",
        "Отримувач": recipient[:120],
        "Телефон": phone,
        "Тариф": "Базовий",
        "Доставка": f"Rozetka{(' · ' + svc) if svc else ''}"[:80],
        "Вартість": declared_s,
        "Післяплата": "",
        "Дод. інфо": desc,
        "JSON": "",
    }
    drafts = st.session_state.setdefault("_up_journal_drafts", {})
    drafts[oid_s] = {"row": row, "prefill": dict(prefill)}


def clear_up_journal_draft(order_id) -> None:
    if order_id is None:
        return
    drafts = st.session_state.get("_up_journal_drafts")
    if isinstance(drafts, dict):
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


def apply_up_wizard_prefill(prefill: dict, *, register_draft: bool = False) -> None:
    """Заповнити session_state для майстра УП (вкладка «УП ТТН»)."""
    if register_draft:
        register_up_journal_draft(prefill)
    st.session_state.up_journal_selected_day = utils.today_kyiv()
    st.session_state.upwiz_form_open = True
    st.session_state.upwiz_edit_mode = False
    st.session_state.pop("upwiz_edit_barcode", None)
    st.session_state.upwiz_lastname = str(prefill.get("lastname") or "")
    st.session_state.upwiz_firstname = str(prefill.get("firstname") or "")
    st.session_state.upwiz_middlename = str(prefill.get("middlename") or "")
    st.session_state.pop("upwiz_recipient_uuid_created", None)
    st.session_state.pop("upwiz_recipient_fp", None)
    ph = str(prefill.get("phone") or "").strip()
    st.session_state.upwiz_phone = ph if ph.startswith("+") else (f"+{ph}" if ph else "+38")
    pc = normalize_postcode(prefill.get("postcode")) or postcode_from_place_number(
        prefill.get("place_number")
    )
    st.session_state.upwiz_postcode_value = pc
    if pc:
        st.session_state.pop("upwiz_postcode", None)
    st.session_state.rozetka_last_prefill = dict(prefill)
    st.session_state.upwiz_region = str(prefill.get("region") or "")
    st.session_state.upwiz_district = str(prefill.get("district") or "")
    st.session_state.upwiz_city = str(prefill.get("city") or "")
    pc = re.sub(r"\D", "", str(pc or ""))[:5]
    if len(pc) == 5 and st.session_state.upwiz_region.strip() and st.session_state.upwiz_city.strip():
        st.session_state.upwiz_postcode_lookup_ok = True
        st.session_state.upwiz_postcode_lookup_last = pc
    elif len(pc) == 5:
        st.session_state.upwiz_postcode_lookup_ok = False
        st.session_state.upwiz_postcode_lookup_last = pc
    st.session_state.upwiz_street = str(prefill.get("street") or "")
    st.session_state.upwiz_house = str(prefill.get("house") or "")
    st.session_state.upwiz_apartment = str(prefill.get("apartment") or "")
    place_number = str(prefill.get("place_number") or "").strip()
    has_street = bool(str(prefill.get("street") or "").strip())
    st.session_state.upwiz_index_mode = "Знаю індекс"
    st.session_state.upwiz_sms = True
    st.session_state.upwiz_paid_shipment_who = "Одержувач"
    st.session_state.upwiz_paid_postpay_who = "Одержувач"
    st.session_state.upwiz_paid_shipment_recipient = True
    st.session_state.upwiz_paid_postpay_recipient = True
    if place_number and not has_street:
        st.session_state.upwiz_address_note = f"Відділення/поштомат №{place_number}"[:255]
    else:
        st.session_state.pop("upwiz_address_note", None)
    desc = str(prefill.get("description") or "")[:40]
    st.session_state.upwiz_description_stored = desc
    st.session_state.pop("upwiz_desc_widget", None)
    declared = float(prefill.get("declared_uah") or 0)
    st.session_state.upwiz_declared_uah = declared
    st.session_state.upwiz_n_parcels = 1
    st.session_state["upwiz_w_0"] = 500
    st.session_state["upwiz_len_0"] = 30
    st.session_state["upwiz_wid_0"] = 20
    st.session_state["upwiz_h_0"] = 10
    st.session_state["upwiz_decl_0"] = declared
    st.session_state.rozetka_linked_order_id = prefill.get("rozetka_order_id")
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
            "oid": prefill.get("rozetka_order_id"),
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
