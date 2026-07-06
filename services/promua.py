"""Prom.ua API integration (orders + УП prefill)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import config
import utils
from services import rozetka as rz_delivery

API_BASE = "https://my.prom.ua/api/v1"
# УП + Prom.ua: при післяплаті, якщо по батькові порожнє — підставляємо «О».
PROM_UP_DEFAULT_MIDDLENAME = "О"


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


def _api_post(path: str, *, json_body: dict) -> tuple[dict | None, str]:
    if not token_configured():
        return None, "Немає PROM_UA_TOKEN у Secrets."
    url = f"{API_BASE}{path}"
    r = utils.make_request("POST", url, headers=_headers(), json=json_body, timeout=45)
    if not r:
        return None, utils.get_last_request_error() or "Немає відповіді від Prom.ua API"
    try:
        data = r.json()
    except Exception:
        return None, f"HTTP {r.status_code}: не JSON"
    if not isinstance(data, dict):
        data = {}
    if r.status_code >= 400:
        return None, _prom_api_error_message(data, r.status_code)
    if str(data.get("status") or "").lower() == "error":
        return None, _prom_api_error_message(data, r.status_code)
    return data, ""


def _prom_api_error_message(data: dict, status_code: int) -> str:
    msg = str(data.get("message") or data.get("error") or "").strip()
    if msg:
        return msg
    errors = data.get("errors")
    if errors:
        return str(errors)
    return f"HTTP {status_code}: {data}"


def delivery_type_for_api(order: dict) -> tuple[str | None, str]:
    """Код delivery_type для POST /delivery/save_declaration_id."""
    if not isinstance(order, dict):
        return None, "Некоректні дані замовлення."
    raw = delivery_service_raw(order).lower()
    kind = delivery_service_kind(order)
    if kind == "УП":
        return "ukrposhta", ""
    if kind == "НП":
        return "nova_poshta", ""
    if kind == "Meest" or "meest" in raw or "міст" in raw:
        return "meest", ""
    if "justin" in raw or "джаст" in raw:
        return "justin", ""
    if "mist" in raw:
        return "mist_express", ""
    label = delivery_service_label(order)
    return None, (
        f"Prom.ua API не підтримує передачу ТТН для «{label}». "
        "Зазвичай доступні: Укрпошта (ukrposhta), Нова Пошта (nova_poshta)."
    )


def save_declaration_id(
    order_id: int | str,
    declaration_id: str,
    *,
    delivery_type: str | None = None,
    order: dict | None = None,
) -> tuple[dict | None, str]:
    """Передати ШКІ в замовлення Prom.ua."""
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return None, "Невірний ID замовлення"
    decl = str(declaration_id or "").strip()
    if not decl:
        return None, "Вкажіть номер ТТН."
    dtype = str(delivery_type or "").strip()
    if not dtype:
        if not isinstance(order, dict):
            return None, "Потрібні дані замовлення для визначення служби доставки."
        dtype, err = delivery_type_for_api(order)
        if err or not dtype:
            return None, err or "Не вдалося визначити delivery_type."
    body = {
        "order_id": oid,
        "declaration_id": decl,
        "delivery_type": dtype,
    }
    return _api_post("/delivery/save_declaration_id", json_body=body)


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


def _prom_delivery_data(order: dict) -> dict:
    pdata = order.get("delivery_provider_data")
    return pdata if isinstance(pdata, dict) else {}


def _prom_recipient_entity(order: dict) -> dict:
    """Вкладений блок отримувача (не покупець)."""
    for key in ("recipient", "delivery_recipient", "receiver", "consignee"):
        block = order.get(key)
        if isinstance(block, dict) and block:
            return block
    return {}


def _field_from_recipient_sources(order: dict, keys: tuple[str, ...]) -> str:
    """Значення з блоків отримувача / доставки (без buyer і без client{{}})."""
    for block in (_prom_recipient_entity(order), _prom_delivery_data(order), order):
        if not isinstance(block, dict):
            continue
        for key in keys:
            val = block.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


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


def _prom_recipient_name_parts(order: dict) -> tuple[str, str, str]:
    """ПІБ отримувача доставки (не покупець з client/buyer)."""
    last = _field_from_recipient_sources(
        order,
        ("recipient_last_name", "receiver_last_name", "lastname", "last_name", "surname"),
    )
    first = _field_from_recipient_sources(
        order,
        ("recipient_first_name", "receiver_first_name", "firstname", "first_name"),
    )
    middle = _field_from_recipient_sources(
        order,
        (
            "recipient_second_name",
            "recipient_middle_name",
            "receiver_second_name",
            "middle_name",
            "middlename",
            "patronymic",
            "second_name",
        ),
    )
    full = _field_from_recipient_sources(
        order,
        ("recipient_name", "recipient_full_name", "receiver_name", "consignee_name"),
    )
    if not full:
        full = str(order.get("recipient_name") or order.get("receiver_name") or "").strip()
    if full and not (last and first):
        last, first, middle = rz_delivery.split_recipient_name(full)

    # Поля client_* на корені замовлення Prom — контакт для доставки (не блок client=buyer).
    if not last:
        last = str(order.get("client_last_name") or "").strip()
    if not first:
        first = str(order.get("client_first_name") or "").strip()
    if not middle:
        middle = str(order.get("client_second_name") or "").strip()

    if not (last and first) and full:
        last, first, middle = rz_delivery.split_recipient_name(full)

    return last, first, middle


def middlename_for_up_prefill(order: dict, middle: str) -> str:
    """По батькові в майстрі УП: «О» лише для Prom + післяплата + порожнє поле."""
    m = str(middle or "").strip()
    if m:
        return m
    if is_cod_payment_order(order):
        return PROM_UP_DEFAULT_MIDDLENAME
    return ""


def recipient_name(order: dict) -> str:
    last, first, middle = _prom_recipient_name_parts(order)
    parts = [last, first]
    if str(middle or "").strip():
        parts.append(middle)
    name = " ".join(p for p in parts if p).strip()
    if name:
        return name
    return "—"


def _prom_buyer_name(order: dict) -> str:
    client = _prom_client(order)
    parts = [
        str(client.get("last_name") or "").strip(),
        str(client.get("first_name") or "").strip(),
        str(client.get("second_name") or "").strip(),
    ]
    return " ".join(p for p in parts if p).strip()


def order_matches_search(order: dict, query: str) -> bool:
    """Чи збігається замовлення з пошуковим запитом (№ або прізвище/ПІБ)."""
    q = str(query or "").strip()
    if not q:
        return True
    q_lower = q.lower()
    q_digits = re.sub(r"\D", "", q)

    if q_digits:
        oid = order_id(order)
        if oid is not None and str(oid) == q_digits:
            return True
        num = str(order.get("number") or "").strip()
        num_digits = re.sub(r"\D", "", num)
        if num and num_digits and (q_digits == num_digits or q_digits in num_digits):
            return True

    if len(q_lower) >= 2:
        for name in (recipient_name(order), _prom_buyer_name(order)):
            if not name or name == "—":
                continue
            if q_lower in name.lower():
                return True
    return False


def search_orders_query(
    query: str, *, limit: int = 100, max_pages: int = 15
) -> tuple[list[dict], dict, str]:
    """Пошук Prom.ua: за ID через API; за прізвищем — по сторінках списку."""
    q = str(query or "").strip()
    if not q:
        return [], {}, ""
    if q.isdigit():
        order, err = fetch_order(int(q))
        if err:
            return [], {}, err
        if order:
            return [order], {"page": 1, "pages": 1, "total": 1}, ""
        return [], {}, f"Замовлення #{q} не знайдено"

    matched: list[dict] = []
    last_meta: dict = {}
    for page in range(1, max(1, int(max_pages)) + 1):
        orders, meta, err = fetch_orders(limit=limit, page=page)
        last_meta = meta if isinstance(meta, dict) else {}
        if err:
            return matched, last_meta, err
        for order in orders:
            if order_matches_search(order, q):
                matched.append(order)
        if page >= int(last_meta.get("pages") or 1):
            break
    return matched, {**last_meta, "page": 1, "pages": 1, "total": len(matched)}, ""


def delivery_service_raw(order: dict) -> str:
    if not isinstance(order, dict):
        return ""
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
        "recipient_address",
        "receiver_address",
        "warehouse_name",
        "pickup_point",
        "office_name",
        "place_number",
    ):
        val = _field_from_recipient_sources(order, (key,))
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


def normalize_ttn(val) -> str:
    s = str(val or "").strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return ""
    if len(s) == 12 and s.isdigit():
        s = "0" + s
    return s


_TTN_FIELD_KEYS = frozenset(
    {
        "declaration_number",
        "declaration_id",
        "declaration_num",
        "delivery_declaration",
        "int_doc_number",
        "document_number",
        "ttn",
        "tracking_number",
        "track_number",
        "barcode",
        "waybill",
        "waybill_number",
        "shipment_barcode",
        "parcel_number",
        "invoice",
    }
)

_TTN_FUZZY_KEY_PARTS = (
    "declaration",
    "tracking",
    "barcode",
    "waybill",
    "shipment",
    "ttn",
    "parcel",
    "накладн",
)


def _looks_like_tracking_number(val: str) -> bool:
    s = str(val or "").strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return False
    if re.fullmatch(r"0?\d{11,14}", s):
        return True
    digits = re.sub(r"\D", "", s)
    return len(digits) >= 10


def _ttn_from_fuzzy_keys(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    for key, val in obj.items():
        kl = str(key).lower()
        if not any(part in kl for part in _TTN_FUZZY_KEY_PARTS):
            continue
        ttn = normalize_ttn(val)
        if ttn and _looks_like_tracking_number(ttn):
            return ttn
    return ""


def _ttn_from_mapping(obj: dict) -> str:
    for key in _TTN_FIELD_KEYS:
        val = normalize_ttn(obj.get(key))
        if val and _looks_like_tracking_number(val):
            return val
    return _ttn_from_fuzzy_keys(obj)


def _ttn_from_nested(order: dict, *, max_depth: int = 4) -> str:
    if not isinstance(order, dict) or max_depth < 0:
        return ""

    pdata = _prom_delivery_data(order)
    if pdata:
        found = _ttn_from_mapping(pdata)
        if found:
            return found

    found = _ttn_from_mapping(order)
    if found:
        return found

    for key in ("delivery", "shipping", "shipment"):
        block = order.get(key)
        if isinstance(block, dict):
            found = _ttn_from_mapping(block)
            if found:
                return found

    if max_depth <= 0:
        return ""

    for val in order.values():
        if isinstance(val, dict):
            found = _ttn_from_nested(val, max_depth=max_depth - 1)
            if found:
                return found
        elif isinstance(val, list):
            for item in val[:8]:
                if isinstance(item, dict):
                    found = _ttn_from_nested(item, max_depth=max_depth - 1)
                    if found:
                        return found
    return ""


def order_ttn(order: dict) -> str:
    """ШКІ з JSON замовлення Prom.ua (delivery_provider_data.declaration_number тощо)."""
    if not isinstance(order, dict):
        return ""
    return _ttn_from_nested(order)


def fetch_order_cached(order_id: int | str) -> tuple[dict | None, str]:
    """GET /orders/{id} з кешем session_state (у списку часто немає ТТН)."""
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return None, "Невірний ID замовлення"
    try:
        import streamlit as st

        cache = st.session_state.setdefault("prom_order_detail_cache", {})
        key = str(oid)
        if key in cache:
            val = cache.get(key)
            if isinstance(val, dict):
                return val, ""
    except Exception:
        pass
    full, err = fetch_order(oid)
    if full:
        try:
            import streamlit as st

            st.session_state.setdefault("prom_order_detail_cache", {})[str(oid)] = full
        except Exception:
            pass
    return full, err


def prom_order_link_tag(order_id: int | str) -> str:
    try:
        return f"PM{int(order_id)}"[:40]
    except (TypeError, ValueError):
        return ""


def prom_order_markers(order_id: int | str, invoice_number: str = "") -> set[str]:
    markers: set[str] = set()
    tag = prom_order_link_tag(order_id)
    if tag:
        markers.add(tag.upper())
        markers.add(tag.lower())
        markers.add(tag)
    inv = utils.normalize_invoice_number(str(invoice_number or "").strip())
    if inv:
        markers.add(inv.upper())
        markers.add(inv)
    return {m for m in markers if m}


def resolve_order_ttn(
    order: dict | None,
    detail: dict | None = None,
    *,
    order_id: int | str | None = None,
    fetch_if_missing: bool = True,
) -> str:
    """Найкращий відомий ШКІ з короткого або повного замовлення."""
    for src in (detail, order):
        ttn = order_ttn(src) if isinstance(src, dict) else ""
        if ttn:
            return ttn
    if fetch_if_missing and order_id is not None:
        remote, _ = fetch_order_cached(order_id)
        if isinstance(remote, dict):
            return order_ttn(remote)
    return ""


def _up_shipments_df_session_cached():
    """Один read_up_shipments на rerun (не на кожну картку Prom)."""
    import time

    import streamlit as st

    import sheets

    cache_key = "_prom_up_shipments_df_cache"
    ts_key = "_prom_up_shipments_df_cache_ts"
    ttl = 120.0
    now = time.time()
    if cache_key in st.session_state and now - float(st.session_state.get(ts_key) or 0) < ttl:
        return st.session_state[cache_key]
    try:
        df = sheets.read_up_shipments(include_json=False)
    except Exception:
        df = None
    st.session_state[cache_key] = df
    st.session_state[ts_key] = now
    return df


def invalidate_up_shipments_session_cache() -> None:
    import streamlit as st

    for key in ("_prom_up_shipments_df_cache", "_prom_up_shipments_df_cache_ts"):
        st.session_state.pop(key, None)


def _journal_bc_by_markers(markers: set[str]) -> str:
    if not markers:
        return ""
    try:
        from services import rozetka

        df = _up_shipments_df_session_cached()
    except Exception:
        return ""
    if df is None or getattr(df, "empty", True):
        return ""
    bc_col = "ШКІ" if "ШКІ" in df.columns else None
    desc_col = "Дод. інфо" if "Дод. інфо" in df.columns else None
    if not bc_col or not desc_col:
        return ""
    norm_markers = {utils.normalize_invoice_number(m).upper() for m in markers if m}
    for _, row in df.iterrows():
        bc = normalize_ttn(row.get(bc_col))
        if not bc or rozetka.is_draft_journal_code(bc):
            continue
        desc = utils.normalize_invoice_number(str(row.get(desc_col) or "")).upper()
        if desc and desc in norm_markers:
            return bc
        for m in norm_markers:
            if m and m in desc:
                return bc
    return ""


def _orders_table_bc_by_markers(markers: set[str]) -> str:
    if not markers:
        return ""
    try:
        import streamlit as st

        df = st.session_state.get("df")
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True):
        return ""
    if "ТТН" not in df.columns:
        return ""
    inv_col = "Номер накладної" if "Номер накладної" in df.columns else None
    norm_markers = {utils.normalize_invoice_number(m).upper() for m in markers if m}
    for _, row in df.iterrows():
        bc = normalize_ttn(row.get("ТТН"))
        if not bc:
            continue
        inv = (
            utils.normalize_invoice_number(str(row.get(inv_col) or "")).upper()
            if inv_col
            else ""
        )
        if inv and inv in norm_markers:
            return bc
        for m in norm_markers:
            if m and m in inv:
                return bc
    return ""


def _session_draft_bc_for_order(order_id: int | str) -> tuple[str, bool]:
    """(ШКІ, is_draft_without_bc) з session_state чернеток УП."""
    try:
        from services import rozetka

        oid_s = str(int(order_id))
        for ent in rozetka.draft_journal_entries():
            if str(ent.get("oid")) != oid_s:
                continue
            row = ent.get("row") if isinstance(ent.get("row"), dict) else {}
            bc = normalize_ttn(row.get("ШКІ"))
            if bc and not rozetka.is_draft_journal_code(bc):
                return bc, False
            return "", True
    except Exception:
        pass
    return "", False


def shipment_state_for_order(
    order_id: int | str,
    order: dict | None = None,
    *,
    detail: dict | None = None,
    invoice_number: str = "",
    fetch_detail: bool = False,
) -> dict[str, Any]:
    """
    Стан відправлення для замовлення Prom.ua.
    keys: ttn, source, has_ttn, has_draft, can_create_up, send_blocked_same
    """
    markers = prom_order_markers(order_id, invoice_number)
    prom_ttn = resolve_order_ttn(
        order,
        detail,
        order_id=None,
        fetch_if_missing=False,
    )
    prom_detail = detail if isinstance(detail, dict) else None
    if fetch_detail and not prom_ttn and order_id is not None:
        prom_ttn = resolve_order_ttn(
            order,
            detail,
            order_id=order_id,
            fetch_if_missing=True,
        )
        if prom_ttn and not prom_detail:
            prom_detail, _ = fetch_order_cached(order_id)
    journal_ttn = _journal_bc_by_markers(markers)
    table_ttn = _orders_table_bc_by_markers(markers)
    draft_bc, has_draft = _session_draft_bc_for_order(order_id)

    has_real_ttn = bool(prom_ttn or journal_ttn or table_ttn)
    ttn = ""
    source = ""
    for candidate, src in (
        (prom_ttn, "prom"),
        (journal_ttn, "journal"),
        (table_ttn, "orders"),
        (draft_bc, "draft"),
    ):
        if candidate:
            ttn = candidate
            source = src
            break

    has_ttn = has_real_ttn or bool(draft_bc)
    can_create_up = not has_real_ttn

    return {
        "ttn": ttn,
        "source": source,
        "has_ttn": has_ttn,
        "has_real_ttn": has_real_ttn,
        "has_draft": has_draft,
        "can_create_up": can_create_up,
        "prom_ttn": prom_ttn,
        "prom_detail": prom_detail if isinstance(prom_detail, dict) else None,
        "journal_ttn": journal_ttn,
        "table_ttn": table_ttn,
    }


def shipment_source_label(source: str) -> str:
    return {
        "prom": "Prom.ua",
        "journal": "журнал УП",
        "orders": "таблиця Orders",
        "draft": "чернетка УП",
    }.get(str(source or "").strip(), "")


def mark_ttn_transferred_to_prom(order_id: int | str, ttn: str = "") -> None:
    """Запамʼятати, що ТТН уже передано в Prom.ua (для приховування зі списку)."""
    try:
        import streamlit as st

        key = str(int(order_id))
    except (TypeError, ValueError):
        return
    store = st.session_state.setdefault("prom_ttn_transferred", {})
    if not isinstance(store, dict):
        store = {}
        st.session_state.prom_ttn_transferred = store
    store[key] = normalize_ttn(ttn) or store.get(key) or "1"


def is_ttn_transferred_to_prom(
    order_id: int | str,
    order: dict | None = None,
    *,
    detail: dict | None = None,
    invoice_number: str = "",
) -> bool:
    """Чи ТТН уже в Prom.ua — такі замовлення ховаємо зі списку."""
    try:
        import streamlit as st

        key = str(int(order_id))
        store = st.session_state.get("prom_ttn_transferred")
        if isinstance(store, dict) and key in store:
            return True
    except (TypeError, ValueError):
        pass
    inv = str(invoice_number or (order or {}).get("number") or "").strip()
    state = shipment_state_for_order(
        order_id,
        order,
        detail=detail,
        invoice_number=inv,
        fetch_detail=False,
    )
    return bool(normalize_ttn(state.get("prom_ttn")))


def validate_send_declaration(
    order_id: int | str,
    new_ttn: str,
    *,
    order: dict | None = None,
    detail: dict | None = None,
    invoice_number: str = "",
    allow_overwrite: bool = False,
) -> tuple[bool, str, str]:
    """
    Перевірка перед save_declaration_id.
    Повертає (ok, error_message, existing_ttn).
    """
    new_ttn = normalize_ttn(new_ttn)
    if not new_ttn:
        return False, "Введіть номер ТТН.", ""

    state = shipment_state_for_order(
        order_id,
        order,
        detail=detail,
        invoice_number=invoice_number,
        fetch_detail=True,
    )
    existing = normalize_ttn(state.get("ttn"))
    prom_existing = normalize_ttn(state.get("prom_ttn"))

    if prom_existing and prom_existing == new_ttn:
        return True, "", prom_existing

    if existing and existing == new_ttn:
        if not prom_existing:
            return True, "", existing
        return True, "", existing

    if existing and existing != new_ttn and not allow_overwrite:
        src = shipment_source_label(str(state.get("source") or ""))
        return (
            False,
            f"У замовлення вже є ТТН {existing}"
            + (f" ({src})" if src else "")
            + f". Новий номер {new_ttn} — увімкніть «Замінити ТТН».",
            existing,
        )
    return True, "", existing


def block_up_create_message(
    order_id: int | str,
    order: dict | None = None,
    *,
    detail: dict | None = None,
    invoice_number: str = "",
    fetch_detail: bool = False,
) -> str:
    state = shipment_state_for_order(
        order_id,
        order,
        detail=detail,
        invoice_number=invoice_number,
        fetch_detail=fetch_detail,
    )
    if state.get("has_real_ttn"):
        ttn = state.get("ttn") or ""
        src = shipment_source_label(str(state.get("source") or ""))
        extra = f" ({src})" if src else ""
        return f"ТТН {ttn} уже прикріплена до #{order_id}{extra}. Нова накладна не потрібна."
    return ""


def resolve_order_amount(order: dict, detail: dict | None = None) -> float:
    """Сума з короткого або повного JSON замовлення."""
    for src in (detail, order):
        if not isinstance(src, dict):
            continue
        amt = _prom_amount(src)
        if amt > 0:
            return amt
    return 0.0


def order_amount_display(order: dict, *, detail: dict | None = None) -> str:
    amount = resolve_order_amount(order, detail=detail)
    if amount > 0:
        if abs(amount - round(amount)) < 0.01:
            return f"{int(round(amount))}"
        return f"{amount:.2f}".rstrip("0").rstrip(".")
    return "—"


def order_created_display(order: dict) -> str:
    return _prom_date(order)[:16]


def is_ukrposhta_order(order: dict) -> bool:
    return delivery_service_kind(order) == "УП"


def order_detail_payload(order: dict) -> dict:
    """Зведення для блоку «Деталі» (як на Rozetka)."""
    last, first, middle = _prom_recipient_name_parts(order)
    return {
        "id": order.get("id"),
        "status": status_label(order),
        "phone": phone(order),
        "ttn": order_ttn(order),
        "declaration_number": _prom_delivery_data(order).get("declaration_number"),
        "delivery_provider_data": _prom_delivery_data(order),
        "recipient": recipient_name(order),
        "delivery_service": delivery_service_label(order),
        "delivery_place": delivery_place_hint(order),
        "payment_type": payment_label(order),
        "payment_status": payment_status_label(order),
        "amount": order_amount_display(order),
        "price_raw": order.get("price"),
        "products_total": _prom_amount_from_products(order),
        "number": order.get("number"),
        "products_count": len(order.get("products") or order.get("order_items") or []),
        "recipient_parts": {"last": last, "first": first, "middle": middle},
    }


def phone(order: dict) -> str:
    return _prom_phone(order)


def _prom_phone(order: dict) -> str:
    """Телефон отримувача (не з профілю покупця client{{}})."""
    for key in (
        "recipient_phone",
        "receiver_phone",
        "delivery_phone",
        "consignee_phone",
        "phone",
    ):
        val = utils.clean_phone(_field_from_recipient_sources(order, (key,)))
        if val:
            return val
    return ""


def _parse_prom_money(val) -> float:
    """Prom.ua часто віддає ціни рядком: «350.00», «1 234,50 грн»."""
    if val is None:
        return 0.0
    if isinstance(val, bool):
        return 0.0
    if isinstance(val, (int, float)):
        try:
            return max(0.0, float(val))
        except Exception:
            return 0.0
    s = str(val).strip().replace("\u00a0", " ")
    if not s or s.lower() in ("none", "null", "nan"):
        return 0.0
    for token in ("грн", "uah", "₴"):
        s = re.sub(rf"(?i){re.escape(token)}", "", s)
    s = s.strip().replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        try:
            return max(0.0, float(m.group(1)))
        except Exception:
            pass
    try:
        return max(0.0, float(s))
    except Exception:
        return 0.0


def _prom_amount_from_products(order: dict) -> float:
    """Сума з кошика: products[].total_price або price × quantity."""
    total = 0.0
    for key in ("products", "order_items", "items", "purchases"):
        items = order.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            line = _parse_prom_money(item.get("total_price"))
            if line <= 0:
                try:
                    qty = max(0.0, float(item.get("quantity") or item.get("qty") or 1))
                except Exception:
                    qty = 1.0
                if qty <= 0:
                    qty = 1.0
                unit = _parse_prom_money(item.get("price"))
                if unit <= 0:
                    unit = _parse_prom_money(item.get("full_price"))
                line = unit * qty
            total += line
        if total > 0:
            return total
    return 0.0


def _prom_amount(order: dict) -> float:
    """Загальна сума замовлення (оголошена / післяплата для УП)."""
    for key in (
        "price",
        "total_price",
        "full_price",
        "sum",
        "amount",
        "order_price",
        "final_price",
        "total_amount",
    ):
        val = order.get(key)
        if val is not None and str(val).strip():
            amt = _parse_prom_money(val)
            if amt > 0:
                return amt
    products_total = _prom_amount_from_products(order)
    if products_total > 0:
        return products_total
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


def _prom_branch_number_from_text(text: str) -> str:
    """Номер відділення/поштомату (1–4 цифри), не індекс і не warehouse_id."""
    s = str(text or "").strip()
    if not s:
        return ""
    m = re.search(
        r"(?i)(?:відділен\w*|отделен\w*|поштомат\w*|postomat)\s*(?:№|#)?\s*(\d{1,4})\b",
        s,
    )
    if m:
        return m.group(1)
    m = re.search(r"(?:№|#)\s*(\d{1,4})\b", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d{1,4}", s):
        return s
    return ""


def _prom_postcode_from_order(order: dict, place_hint: str) -> str:
    """
    Індекс отримувача з Prom.ua.
    Не використовує поле index / warehouse_id (часто це дані відправника або каталогу УП).
    """
    for block in (_prom_recipient_entity(order), _prom_delivery_data(order), order):
        if not isinstance(block, dict):
            continue
        for key in (
            "postcode",
            "post_index",
            "postal_code",
            "zip",
            "recipient_postcode",
            "delivery_postcode",
        ):
            pc = rz_delivery.normalize_postcode(str(block.get(key) or ""))
            if pc:
                return pc
    for blob in (
        place_hint,
        _field_from_recipient_sources(
            order,
            ("delivery_address", "recipient_address", "receiver_address"),
        ),
    ):
        pc = rz_delivery.extract_postcode_from_text(str(blob or ""))
        if pc:
            return pc
    return ""


def _prom_parse_city_region_from_address(text: str) -> tuple[str, str]:
    """Область і місто з delivery_address Prom (якщо окремих полів немає)."""
    s = str(text or "").strip()
    if not s:
        return "", ""
    region = ""
    city = ""
    m = re.search(
        r"([А-ЯІЇЄа-яіїє''\-]+(?:ська|ський))\s+обл",
        s,
        re.I,
    )
    if m:
        region = m.group(1).strip()
        if not region.lower().endswith("область"):
            region = f"{region} область"
    m = re.search(
        r"(?i)\b(?:м\.|місто|м\s)\s*([А-ЯІЇЄа-яіїє''\-\s]+?)(?:,|\s+вул|\s+відділен|\s+поштомат|\s*$)",
        s,
    )
    if m:
        city = m.group(1).strip().strip(",")
    return region, city


def _prom_resolve_branch_postcode(
    *, city: str, region: str, branch: str
) -> tuple[str, dict | None]:
    if not city or not branch:
        return "", None
    try:
        mod = __import__("app", fromlist=["up_resolve_postcode_by_branch"])
        return mod.up_resolve_postcode_by_branch(city, region, branch)
    except Exception:
        return "", None


def build_up_prefill(order: dict) -> dict:
    """Мапінг замовлення Prom.ua → майстер УП (дані отримувача доставки)."""
    pdata = _prom_delivery_data(order)

    last, first, middle = _prom_recipient_name_parts(order)
    ph = _prom_phone(order)

    region = _field_from_recipient_sources(
        order, ("region", "area", "recipient_region", "city_region")
    )
    district = _field_from_recipient_sources(order, ("district", "recipient_district"))
    city_name = _field_from_recipient_sources(
        order, ("city_name", "city", "recipient_city", "locality")
    )
    street = _field_from_recipient_sources(
        order, ("street", "address_street", "recipient_street")
    )
    house = _field_from_recipient_sources(order, ("house", "building", "recipient_house"))
    apartment = _field_from_recipient_sources(
        order, ("flat", "apartment", "recipient_flat")
    )

    place_hint = delivery_place_hint(order)
    place_number = _prom_branch_number_from_text(place_hint)
    if not place_number:
        place_number = _prom_branch_number_from_text(
            _field_from_recipient_sources(
                order, ("warehouse_number", "branch_number", "office_number")
            )
        )

    postcode = _prom_postcode_from_order(order, place_hint)

    if not region or not city_name:
        addr_region, addr_city = _prom_parse_city_region_from_address(place_hint)
        if not region and addr_region:
            region = addr_region
        if not city_name and addr_city:
            city_name = addr_city

    if not postcode and city_name and place_number:
        pc_branch, loc_branch = _prom_resolve_branch_postcode(
            city=city_name, region=region, branch=place_number
        )
        if pc_branch:
            postcode = pc_branch
            if loc_branch:
                if not region:
                    region = str(loc_branch.get("region") or region)
                if not district:
                    district = str(loc_branch.get("district") or district)
                if not city_name:
                    city_name = str(loc_branch.get("city") or city_name)

    oid = order_id(order)
    inv = utils.normalize_invoice_number(str(order.get("number") or ""))
    declared = resolve_order_amount(order)
    postpay = declared if is_cod_payment_order(order) else 0.0
    svc_raw = delivery_service_raw(order)

    place_hint_l = place_hint.lower()
    explicit_branch = any(
        m in place_hint_l for m in ("відділен", "отделен", "поштомат", "postomat", "№")
    )
    delivery_to_branch = bool(place_number) and (
        explicit_branch or "нов" in svc_raw.lower() or (not house and not apartment)
    )
    if delivery_to_branch:
        street = ""
        house = ""
        apartment = ""

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
        "prom_order_id": oid,
        "rozetka_order_id": oid,
        "delivery_service": svc_raw,
        "lastname": last,
        "firstname": first,
        "middlename": middlename_for_up_prefill(order, middle),
        "phone": ph,
        "postcode": postcode,
        "region": region,
        "district": district,
        "city": city_name,
        "street": street,
        "house": house,
        "apartment": apartment,
        "place_number": place_number,
        "delivery_to_branch": delivery_to_branch,
        "description": (f"PM{oid}" if oid else "")[:40],
        "invoice_number": inv,
        "declared_uah": max(0.0, declared),
        "postpay_uah": postpay,
        "payment_type": payment_label(order),
    }


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
