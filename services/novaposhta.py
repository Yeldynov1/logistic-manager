"""Nova Poshta API — створення ТТН (InternetDocument)."""
from __future__ import annotations

import re
from typing import Any

import config
import utils

API_URL = "https://api.novaposhta.ua/v2.0/json/"


def _api_key() -> str:
    return str(getattr(config, "API_KEY_NP", "") or config.get_secret("NOVA_POSHTA_API_KEY") or "").strip()


def api_configured() -> bool:
    return bool(_api_key())


def _np_call(model: str, method: str, props: dict | None = None) -> tuple[list | dict | None, str]:
    key = _api_key()
    if not key:
        return None, "Немає NOVA_POSHTA_API_KEY у Secrets."
    payload = {
        "apiKey": key,
        "modelName": model,
        "calledMethod": method,
        "methodProperties": props or {},
    }
    r = utils.make_request("POST", API_URL, json=payload, timeout=45)
    if not r:
        return None, utils.get_last_request_error() or "Немає відповіді від Nova Poshta API"
    try:
        data = r.json()
    except Exception:
        return None, f"HTTP {r.status_code}: не JSON"
    if not isinstance(data, dict):
        return None, "Некоректна відповідь Nova Poshta"
    if not data.get("success"):
        errors = data.get("errors")
        if isinstance(errors, list) and errors:
            return None, "; ".join(str(e) for e in errors)
        return None, str(errors or data.get("error") or "Помилка Nova Poshta API")
    return data.get("data"), ""


def _phone_np(val: str) -> str:
    digits = re.sub(r"\D", "", str(val or ""))
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    if len(digits) == 9:
        digits = "380" + digits
    return digits[:12]


def _sender_phone() -> str:
    for key in ("NP_SENDER_PHONE", "UP_SENDER_PHONE"):
        ph = _phone_np(str(getattr(config, key, "") or config.get_secret(key) or ""))
        if len(ph) >= 12:
            return ph
    return ""


def _resolve_sender() -> tuple[dict[str, str], str]:
    """Sender refs: з Secrets або перший Sender з API."""
    refs = {
        "Sender": str(getattr(config, "NP_SENDER_REF", "") or config.get_secret("NP_SENDER_REF") or "").strip(),
        "ContactSender": str(
            getattr(config, "NP_SENDER_CONTACT_REF", "") or config.get_secret("NP_SENDER_CONTACT_REF") or ""
        ).strip(),
        "CitySender": str(
            getattr(config, "NP_SENDER_CITY_REF", "") or config.get_secret("NP_SENDER_CITY_REF") or ""
        ).strip(),
        "SenderAddress": str(
            getattr(config, "NP_SENDER_WAREHOUSE_REF", "") or config.get_secret("NP_SENDER_WAREHOUSE_REF") or ""
        ).strip(),
    }
    if all(refs.values()):
        return refs, ""

    rows, err = _np_call("Counterparty", "getCounterparties", {"CounterpartyProperty": "Sender", "Page": "1"})
    if err:
        return {}, err
    if not isinstance(rows, list) or not rows:
        return {}, "У кабінеті НП не знайдено відправника. Додайте NP_SENDER_* у Secrets."
    row = rows[0] if isinstance(rows[0], dict) else {}
    cp_ref = str(row.get("Ref") or "").strip()
    if not cp_ref:
        return {}, "Не вдалося отримати Ref відправника НП."

    if not refs["Sender"]:
        refs["Sender"] = cp_ref

    contacts, cerr = _np_call(
        "Counterparty",
        "getCounterpartyContactPersons",
        {"Ref": cp_ref, "Page": "1"},
    )
    if not refs["ContactSender"] and not cerr and isinstance(contacts, list) and contacts:
        c0 = contacts[0] if isinstance(contacts[0], dict) else {}
        refs["ContactSender"] = str(c0.get("Ref") or "").strip()

    addresses, aerr = _np_call(
        "Counterparty",
        "getCounterpartyAddresses",
        {"Ref": cp_ref, "CounterpartyProperty": "Sender", "Page": "1"},
    )
    if not refs["SenderAddress"] and not aerr and isinstance(addresses, list) and addresses:
        a0 = addresses[0] if isinstance(addresses[0], dict) else {}
        refs["SenderAddress"] = str(a0.get("Ref") or "").strip()
        if not refs["CitySender"]:
            refs["CitySender"] = str(a0.get("CityRef") or "").strip()

    missing = [k for k, v in refs.items() if not v]
    if missing:
        return refs, (
            f"Не вистачає даних відправника НП ({', '.join(missing)}). "
            "Заповніть NP_SENDER_REF, NP_SENDER_CONTACT_REF, NP_SENDER_CITY_REF, NP_SENDER_WAREHOUSE_REF у Secrets."
        )
    return refs, ""


def find_city_ref(city: str, region: str = "") -> tuple[str, str]:
    query = str(city or "").strip()
    if not query:
        return "", "Не вказано місто одержувача."
    rows, err = _np_call("Address", "getCities", {"FindByString": query, "Limit": "30"})
    if err:
        return "", err
    if not isinstance(rows, list) or not rows:
        return "", f"Місто «{query}» не знайдено в довіднику НП."

    region_l = str(region or "").strip().lower()
    best = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("Ref") or "").strip()
        if not ref:
            continue
        desc = str(row.get("Description") or row.get("Present") or "").lower()
        if region_l and region_l[:6] in desc:
            return ref, ""
        if query.lower() in desc and not best:
            best = ref
    if best:
        return best, ""
    first = rows[0] if isinstance(rows[0], dict) else {}
    ref = str(first.get("Ref") or "").strip()
    return ref, "" if ref else f"Місто «{query}» не знайдено в НП."


def find_warehouse_ref(city_ref: str, branch_number: str) -> tuple[str, str]:
    branch = re.sub(r"\D", "", str(branch_number or ""))
    if not city_ref:
        return "", "Немає CityRef для пошуку відділення НП."
    if not branch:
        return "", "Не вказано номер відділення НП."
    rows, err = _np_call(
        "Address",
        "getWarehouses",
        {"CityRef": city_ref, "Limit": "500", "Language": "UA"},
    )
    if err:
        return "", err
    if not isinstance(rows, list):
        return "", "Порожній список відділень НП."
    branch_cmp = branch.lstrip("0") or branch
    for row in rows:
        if not isinstance(row, dict):
            continue
        num = str(row.get("Number") or "").strip()
        if not num:
            continue
        if num == branch or num.lstrip("0") == branch_cmp:
            ref = str(row.get("Ref") or "").strip()
            if ref:
                return ref, ""
    return "", f"Відділення №{branch} не знайдено в НП для обраного міста."


def is_nova_poshta_prefill(prefill: dict) -> bool:
    if not isinstance(prefill, dict):
        return False
    carrier = str(prefill.get("shipment_carrier") or "").strip().lower()
    if carrier == "np":
        return True
    svc = str(prefill.get("delivery_service") or "").lower()
    if "нова" in svc or "nova" in svc:
        return True
    return False


def create_shipment_from_prefill(prefill: dict) -> tuple[str, str]:
    """
    Створити ТТН НП за prefill (як з Епіцентр / маркетплейсу).
    Повертає (ttn_14_digits, error).
    """
    if not api_configured():
        return "", "Немає NOVA_POSHTA_API_KEY у Secrets."

    sender, serr = _resolve_sender()
    if serr:
        return "", serr

    phone = _sender_phone()
    if not phone:
        return "", "Вкажіть NP_SENDER_PHONE або UP_SENDER_PHONE у Secrets."

    last = str(prefill.get("lastname") or "").strip()
    first = str(prefill.get("firstname") or "").strip()
    middle = str(prefill.get("middlename") or "").strip()
    recipient_name = " ".join(p for p in (last, first, middle) if p).strip()
    if not recipient_name:
        return "", "Немає ПІБ одержувача."
    rphone = _phone_np(str(prefill.get("phone") or ""))
    if len(rphone) < 12:
        return "", "Некоректний телефон одержувача."

    city = str(prefill.get("city") or "").strip()
    region = str(prefill.get("region") or "").strip()
    city_ref, cerr = find_city_ref(city, region)
    if cerr:
        return "", cerr

    place_number = str(prefill.get("place_number") or "").strip()
    to_branch = bool(prefill.get("delivery_to_branch")) or bool(place_number)
    recipient_address_ref = ""
    service_type = "WarehouseWarehouse"
    if to_branch:
        recipient_address_ref, werr = find_warehouse_ref(city_ref, place_number)
        if werr:
            return "", werr
    else:
        street = str(prefill.get("street") or "").strip()
        house = str(prefill.get("house") or "").strip()
        if not street:
            return "", "Для НП потрібне відділення або адреса доставки (вулиця)."
        service_type = "WarehouseDoors"

    try:
        weight_g = int(prefill.get("weight_g") or 500)
    except (TypeError, ValueError):
        weight_g = 500
    weight_kg = max(0.1, min(30.0, weight_g / 1000.0))

    try:
        declared = float(prefill.get("declared_uah") or 0)
    except (TypeError, ValueError):
        declared = 0.0
    try:
        postpay = float(prefill.get("postpay_uah") or 0)
    except (TypeError, ValueError):
        postpay = 0.0
    cost = max(declared, postpay, 1.0)

    invoice = utils.normalize_invoice_number(str(prefill.get("invoice_number") or ""))
    desc = str(prefill.get("description") or invoice or "Замовлення")[:64]

    props: dict[str, Any] = {
        "PayerType": "Recipient",
        "PaymentMethod": "Cash",
        "CargoType": "Parcel",
        "Weight": str(round(weight_kg, 2)),
        "ServiceType": service_type,
        "SeatsAmount": "1",
        "Description": desc,
        "Cost": str(int(round(cost))),
        "CitySender": sender["CitySender"],
        "Sender": sender["Sender"],
        "SenderAddress": sender["SenderAddress"],
        "ContactSender": sender["ContactSender"],
        "SendersPhone": phone,
        "CityRecipient": city_ref,
        "RecipientName": recipient_name,
        "RecipientType": "PrivatePerson",
        "RecipientsPhone": rphone,
        "NewAddress": "1",
    }
    if invoice:
        props["AdditionalInformation"] = invoice[:100]
    if postpay >= 1:
        props["AfterpaymentOnGoodsCost"] = str(int(round(postpay)))

    if service_type == "WarehouseWarehouse":
        props["RecipientAddress"] = recipient_address_ref
    else:
        props["RecipientCityName"] = city
        props["RecipientArea"] = region
        props["RecipientAddressName"] = street
        props["RecipientHouse"] = house
        apt = str(prefill.get("apartment") or "").strip()
        if apt:
            props["RecipientFlat"] = apt

    data, err = _np_call("InternetDocument", "save", props)
    if err:
        return "", err
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        return "", "НП прийняла запит, але номер ТТН не повернула."
    ttn = utils.clean_ttn(str(row.get("IntDocNumber") or row.get("Ref") or ""))
    if not ttn:
        return "", "У відповіді НП немає номера ТТН."
    return ttn, ""
