"""Епіцентр Marketplace — Merchant API (замовлення OMS)."""
from __future__ import annotations

import re
from typing import Any

import config
import utils
from services import rozetka as rz_delivery

API_BASE = "https://merchant-api.epicentrm.com.ua"

# За замовчуванням — замовлення, що ще в обробці / доставці.
DEFAULT_STATUS_FILTER: tuple[str, ...] = (
    "new",
    "confirmed_by_merchant",
    "confirmed",
    "sent",
)

STATUS_LABELS_UA: dict[str, str] = {
    "new": "Новий",
    "confirmed_by_merchant": "Підтверджено продавцем",
    "confirmed": "Підтверджено",
    "sent": "Відправлено",
    "delivered": "Готовий до видачі",
    "completed": "Завершено",
    "closed": "Закрито",
    "canceled": "Скасовано",
    "returned": "Повернено",
    "return_requested": "Запит на повернення",
    "canceled_by_merchant": "Скасовано продавцем",
    "completed_merchant_rejection": "Завершено (відмова)",
    "closed_merchant_rejection": "Закрито (відмова)",
}

PROVIDER_LABELS: dict[str, str] = {
    "nova_poshta": "Нова пошта",
    "ukrposhta": "Укрпошта",
    "pickup": "Самовивіз",
    "meest": "Meest",
}

EPIC_UP_DEFAULT_MIDDLENAME = "О"


def _token() -> str:
    config.apply_epicentr_secrets()
    return config.get_epicentr_token() or str(getattr(config, "EPICENTR_API_TOKEN", "") or "").strip()


def token_configured() -> bool:
    return bool(_token())


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _api_request(
    method: str,
    path: str,
    *,
    params: dict | list | None = None,
    json_body: dict | None = None,
    timeout: int = 45,
) -> tuple[dict | list | None, str]:
    if not token_configured():
        return None, "Немає EPICENTR_API_TOKEN у Secrets."
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    r = utils.make_request(
        method,
        url,
        headers=_headers(),
        params=params or {},
        json=json_body,
        timeout=timeout,
    )
    if not r:
        return None, utils.get_last_request_error() or "Немає відповіді від Епіцентр API"
    try:
        data = r.json()
    except Exception:
        snippet = (getattr(r, "text", None) or "")[:160].strip()
        return None, f"HTTP {r.status_code}: не JSON ({snippet})"
    if r.status_code >= 400:
        if isinstance(data, dict):
            msg = str(data.get("message") or data.get("error") or data).strip()
            return None, msg or f"HTTP {r.status_code}"
        return None, f"HTTP {r.status_code}: {data}"
    return data, ""


def _orders_list_params(
    *,
    limit: int = 50,
    cursor: str | None = None,
    status_codes: tuple[str, ...] | None = None,
) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [
        ("limit", str(max(1, min(100, int(limit))))),
        ("sort[]", "-createdAt"),
    ]
    if cursor:
        params.append(("cursor", str(cursor).strip()))
    for code in status_codes if status_codes is not None else DEFAULT_STATUS_FILTER:
        params.append(("filter[statusCode][]", str(code)))
    return params


def fetch_orders(
    *,
    limit: int = 50,
    cursor: str | None = None,
    status_codes: tuple[str, ...] | None = DEFAULT_STATUS_FILTER,
) -> tuple[list[dict], dict, str]:
    """GET /v3/oms/orders — список замовлень (cursor pagination)."""
    data, err = _api_request(
        "GET",
        "/v3/oms/orders",
        params=_orders_list_params(limit=limit, cursor=cursor, status_codes=status_codes),
    )
    if err:
        return [], {}, err
    if not isinstance(data, dict):
        return [], {}, "Порожня відповідь Епіцентр API"
    items = data.get("items")
    orders = [o for o in items if isinstance(o, dict)] if isinstance(items, list) else []
    meta = {
        "current": str(data.get("current") or ""),
        "next": str(data.get("next") or ""),
        "prev": str(data.get("prev") or ""),
        "last": str(data.get("last") or ""),
        "limit": int(data.get("limit") or limit),
        "total": len(orders),
    }
    return orders, meta, ""


def fetch_order(order_id: str) -> tuple[dict | None, str]:
    """GET /v5/oms/orders/{orderId} — повні дані замовлення."""
    oid = str(order_id or "").strip()
    if not oid:
        return None, "Невірний ID замовлення"
    data, err = _api_request("GET", f"/v5/oms/orders/{oid}")
    if err:
        return None, err
    return data if isinstance(data, dict) else None, ""


def save_shipment_number(order_id: str, number: str) -> tuple[dict | None, str]:
    """PATCH /v1/oms/orders/{orderId}/shipment-number — передати ТТН."""
    oid = str(order_id or "").strip()
    decl = str(number or "").strip()
    if not oid:
        return None, "Невірний ID замовлення"
    if not decl:
        return None, "Вкажіть номер ТТН."
    _, err = _api_request(
        "PATCH",
        f"/v1/oms/orders/{oid}/shipment-number",
        json_body={"number": decl},
    )
    if err:
        return None, err
    return {}, ""


def order_uuid(order: dict) -> str:
    return str(order.get("id") or "").strip()


def order_number(order: dict) -> str:
    return str(order.get("number") or "").strip()


def normalize_ttn(val: Any) -> str:
    return utils.clean_ttn(str(val or "").strip())


def status_label(order: dict) -> str:
    code = str(order.get("statusCode") or "").strip()
    return STATUS_LABELS_UA.get(code, code or "Нове")


def _shipment_block(order: dict) -> dict:
    addr = order.get("address")
    if isinstance(addr, dict):
        ship = addr.get("shipment")
        if isinstance(ship, dict):
            return ship
    return {}


def delivery_provider_code(order: dict) -> str:
    ship = _shipment_block(order)
    provider = ship.get("provider")
    if isinstance(provider, str):
        return provider.strip()
    return str(provider or "").strip()


def delivery_service_label(order: dict) -> str:
    code = delivery_provider_code(order)
    return PROVIDER_LABELS.get(code, code or "Служба доставки не вказана")


def delivery_service_kind(order: dict) -> str:
    code = delivery_provider_code(order).lower()
    if code == "ukrposhta":
        return "УП"
    if code == "nova_poshta":
        return "НП"
    if code == "meest":
        return "Meest"
    if code == "pickup":
        return "Інше"
    return "Інше"


def is_ukrposhta_order(order: dict) -> bool:
    return delivery_provider_code(order).lower() == "ukrposhta"


def _recipient_block(order: dict) -> dict:
    addr = order.get("address")
    if not isinstance(addr, dict):
        return {}
    alt = addr.get("recipient")
    if isinstance(alt, dict) and alt:
        return alt
    return addr


def recipient_name(order: dict) -> str:
    block = _recipient_block(order)
    last = str(block.get("lastName") or "").strip()
    first = str(block.get("firstName") or "").strip()
    middle = str(block.get("patronymic") or "").strip()
    if not (last and first):
        last, first, middle = rz_delivery.split_recipient_name(
            " ".join(p for p in (last, first, middle) if p).strip()
        )
    parts = [last, first]
    if middle:
        parts.append(middle)
    name = " ".join(p for p in parts if p).strip()
    return name or "—"


def phone(order: dict) -> str:
    block = _recipient_block(order)
    raw = str(block.get("phone") or "").strip()
    if not raw:
        addr = order.get("address")
        if isinstance(addr, dict):
            raw = str(addr.get("phone") or "").strip()
    return utils.clean_phone(raw) if raw else ""


def payment_provider(order: dict) -> str:
    return str(_shipment_block(order).get("paymentProvider") or "").strip()


def is_cod_payment_order(order: dict) -> bool:
    return payment_provider(order) == "pay_on_delivery"


def payment_label(order: dict) -> str:
    code = payment_provider(order)
    labels = {
        "pay_on_delivery": "Накладений платіж",
        "pay_on_pickup": "Оплата при отриманні",
        "easypay": "EasyPay",
        "monobank": "Monobank",
        "invoice": "Рахунок",
    }
    return labels.get(code, code or "—")


def payment_status_label(order: dict) -> str:
    return str(_shipment_block(order).get("paymentStatus") or "").strip()


def order_ttn(order: dict, detail: dict | None = None) -> str:
    for src in (detail, order):
        if not isinstance(src, dict):
            continue
        ship = _shipment_block(src)
        ttn = normalize_ttn(ship.get("number"))
        if ttn:
            return ttn
    return ""


def _settlement(order: dict) -> dict:
    block = order.get("settlement")
    return block if isinstance(block, dict) else {}


def _office(order: dict) -> dict:
    block = order.get("office")
    return block if isinstance(block, dict) else {}


def _branch_number_from_text(text: str) -> str:
    m = re.search(r"(?:№|#|n[oо]\.?\s*)(\d{1,6})", str(text or ""), flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def delivery_place_hint(order: dict) -> str:
    office = _office(order)
    settlement = _settlement(order)
    bits: list[str] = []
    if settlement:
        for key in ("city", "title", "region"):
            val = str(settlement.get(key) or "").strip()
            if val and val not in bits:
                bits.append(val)
    off_title = str(office.get("title") or "").strip()
    off_addr = str(office.get("address") or "").strip()
    if off_title:
        bits.append(off_title)
    elif off_addr:
        bits.append(off_addr)
    return " · ".join(bits)


def product_title(order: dict) -> str:
    items = order.get("items")
    if not isinstance(items, list) or not items:
        return ""
    first = items[0] if isinstance(items[0], dict) else {}
    title = str(first.get("title") or "").strip()
    if len(items) > 1:
        return f"{title} (+{len(items) - 1})" if title else f"{len(items)} товарів"
    return title


def order_amount_display(order: dict, detail: dict | None = None) -> str:
    for src in (detail, order):
        if not isinstance(src, dict):
            continue
        try:
            val = float(src.get("subtotal") or 0)
        except (TypeError, ValueError):
            val = 0.0
        if val > 0:
            return f"{val:.2f}".rstrip("0").rstrip(".")
    return "0"


def order_created_display(order: dict) -> str:
    raw = str(order.get("createdAt") or "").strip()
    if not raw:
        return "—"
    return raw.replace("T", " ")[:19]


def order_detail_payload(order: dict) -> dict:
    return {
        "id": order_uuid(order),
        "number": order_number(order),
        "status": status_label(order),
        "recipient": recipient_name(order),
        "phone": phone(order),
        "delivery": delivery_service_label(order),
        "place": delivery_place_hint(order),
        "ttn": order_ttn(order),
        "payment": payment_label(order),
        "items": order.get("items"),
        "address": order.get("address"),
        "settlement": order.get("settlement"),
        "office": order.get("office"),
    }


def _journal_bc_by_invoice(invoice: str) -> str:
    inv = utils.normalize_invoice_number(str(invoice or "")).upper()
    if not inv:
        return ""
    try:
        import streamlit as st

        df = st.session_state.get("df")
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True) or "ТТН" not in df.columns:
        return ""
    inv_col = "Номер накладної" if "Номер накладної" in df.columns else None
    for _, row in df.iterrows():
        bc = normalize_ttn(row.get("ТТН"))
        if not bc:
            continue
        row_inv = (
            utils.normalize_invoice_number(str(row.get(inv_col) or "")).upper()
            if inv_col
            else ""
        )
        if row_inv and row_inv == inv:
            return bc
    return ""


def _session_draft_for_order(order_id: str) -> tuple[str, bool]:
    try:
        from services import rozetka

        oid_s = str(order_id or "").strip()
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
    order_id: str,
    order: dict | None = None,
    *,
    detail: dict | None = None,
    invoice_number: str = "",
) -> dict[str, Any]:
    inv = utils.normalize_invoice_number(invoice_number or order_number(order or {}))
    epic_ttn = order_ttn(order, detail)
    if not epic_ttn and detail is None and order_id:
        full, _ = fetch_order(order_id)
        if isinstance(full, dict):
            detail = full
            epic_ttn = order_ttn(order, detail)
    journal_ttn = _journal_bc_by_invoice(inv)
    draft_bc, has_draft = _session_draft_for_order(order_id)

    has_real_ttn = bool(epic_ttn or journal_ttn)
    ttn = ""
    source = ""
    for candidate, src in (
        (epic_ttn, "epicentr"),
        (journal_ttn, "journal"),
        (draft_bc, "draft"),
    ):
        if candidate:
            ttn = candidate
            source = src
            break

    return {
        "ttn": ttn,
        "source": source,
        "has_ttn": bool(ttn),
        "has_real_ttn": has_real_ttn,
        "has_draft": has_draft,
        "epic_ttn": epic_ttn,
        "epic_detail": detail if isinstance(detail, dict) else None,
        "journal_ttn": journal_ttn,
    }


def shipment_source_label(source: str) -> str:
    return {
        "epicentr": "Епіцентр",
        "journal": "журнал УП",
        "draft": "чернетка УП",
    }.get(str(source or "").strip(), "")


def block_up_create_message(
    order_id: str,
    order: dict | None = None,
    *,
    detail: dict | None = None,
    invoice_number: str = "",
) -> str:
    state = shipment_state_for_order(
        order_id,
        order,
        detail=detail,
        invoice_number=invoice_number,
    )
    if state.get("has_real_ttn"):
        ttn = state.get("ttn") or ""
        src = shipment_source_label(str(state.get("source") or ""))
        extra = f" ({src})" if src else ""
        num = invoice_number or order_number(order or {})
        return f"ТТН {ttn} уже прикріплена до #{num}{extra}."
    return ""


def build_up_prefill(order: dict) -> dict:
    """Мапінг замовлення Епіцентр → майстер УП."""
    block = _recipient_block(order)
    last = str(block.get("lastName") or "").strip()
    first = str(block.get("firstName") or "").strip()
    middle = str(block.get("patronymic") or "").strip()
    if not (last and first):
        last, first, middle = rz_delivery.split_recipient_name(recipient_name(order))

    settlement = _settlement(order)
    office = _office(order)
    region = str(settlement.get("region") or "").strip()
    district = str(settlement.get("district") or "").strip()
    city_name = str(settlement.get("city") or settlement.get("title") or "").strip()
    place_hint = delivery_place_hint(order)
    place_number = _branch_number_from_text(str(office.get("title") or ""))
    if not place_number:
        ext = str(office.get("externalId") or "").strip()
        if ext.isdigit() and len(ext) <= 6:
            place_number = ext

    postcode = ""
    if place_number and city_name:
        try:
            mod = __import__("app", fromlist=["up_resolve_postcode_by_branch"])
            pc_branch, loc_branch = mod.up_resolve_postcode_by_branch(
                city_name, region, place_number
            )
        except Exception:
            pc_branch, loc_branch = "", None
        if isinstance(loc_branch, dict):
            if not region:
                region = str(loc_branch.get("region") or region)
            if not district:
                district = str(loc_branch.get("district") or district)
            if not city_name:
                city_name = str(loc_branch.get("city") or city_name)
        if pc_branch:
            postcode = str(pc_branch)

    oid = order_uuid(order)
    num = order_number(order)
    inv = utils.normalize_invoice_number(num)
    try:
        declared = float(order.get("subtotal") or 0)
    except (TypeError, ValueError):
        declared = 0.0
    postpay = declared if is_cod_payment_order(order) else 0.0
    svc = delivery_service_label(order)
    delivery_to_branch = bool(place_number) and is_ukrposhta_order(order)

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

    middle_up = middle
    if not middle_up and is_cod_payment_order(order):
        middle_up = EPIC_UP_DEFAULT_MIDDLENAME

    return {
        "epicentr_order_id": oid,
        "epicentr_order_number": num,
        "rozetka_order_id": num or oid,
        "delivery_service": svc,
        "lastname": last,
        "firstname": first,
        "middlename": middle_up,
        "phone": phone(order),
        "postcode": postcode,
        "region": region,
        "district": district,
        "city": city_name,
        "street": "",
        "house": "",
        "apartment": "",
        "place_number": place_number,
        "delivery_to_branch": delivery_to_branch,
        "description": (f"EP{num}" if num else oid)[:40],
        "invoice_number": inv,
        "declared_uah": max(0.0, declared),
        "postpay_uah": postpay,
        "payment_type": payment_label(order),
    }
