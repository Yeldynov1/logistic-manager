"""Nova Poshta API — створення ТТН (InternetDocument)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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


def _phone_local(val: str) -> str:
    """Телефон для Counterparty.save — формат 0XXXXXXXXX."""
    digits = _phone_np(val)
    if len(digits) == 12 and digits.startswith("38"):
        return "0" + digits[2:]
    if len(digits) == 9:
        return "0" + digits
    return digits


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


def _norm_region_token(region: str) -> str:
    s = str(region or "").strip().lower()
    s = s.replace(" область", "").replace(" обл.", "").replace(" обл", "")
    return s[:12]


def find_city_ref(city: str, region: str = "") -> tuple[str, str]:
    query = str(city or "").strip()
    if not query:
        return "", "Не вказано місто одержувача."
    if " - " in query:
        query = query.split(" - ", 1)[0].strip()
    rows, err = _np_call("Address", "getCities", {"FindByString": query, "Limit": "50"})
    if err:
        return "", err
    if not isinstance(rows, list) or not rows:
        return "", f"Місто «{query}» не знайдено в довіднику НП."

    region_tok = _norm_region_token(region)
    query_l = query.lower()
    best = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("Ref") or "").strip()
        if not ref:
            continue
        desc = str(row.get("Description") or row.get("Present") or "").lower()
        areas = str(row.get("AreaDescription") or row.get("SettlementTypeDescription") or "").lower()
        blob = f"{desc} {areas}"
        if region_tok and region_tok[:6] in blob:
            if query_l in desc or desc.startswith(query_l):
                return ref, ""
        if (query_l in desc or desc.startswith(query_l)) and not best:
            best = ref
    if best:
        return best, ""
    first = rows[0] if isinstance(rows[0], dict) else {}
    ref = str(first.get("Ref") or "").strip()
    return ref, "" if ref else f"Місто «{query}» не знайдено в НП."


def warehouse_by_ref(warehouse_ref: str) -> tuple[dict | None, str]:
    ref = str(warehouse_ref or "").strip()
    if not ref:
        return None, ""
    rows, err = _np_call("Address", "getWarehouses", {"Ref": ref, "Language": "UA"})
    if err:
        return None, err
    if isinstance(rows, list) and rows:
        row = rows[0] if isinstance(rows[0], dict) else None
        return row, ""
    if isinstance(rows, dict):
        return rows, ""
    return None, ""


def _warehouse_matches_branch(row: dict, branch: str) -> bool:
    if not isinstance(row, dict) or not branch:
        return False
    branch_cmp = branch.lstrip("0") or branch
    num = str(row.get("Number") or "").strip()
    if num and (num == branch or num.lstrip("0") == branch_cmp):
        return True
    desc = str(row.get("Description") or row.get("ShortAddress") or "").lower()
    if not desc:
        return False
    if re.search(rf"(?:№|#|n[oо]\.?\s*){re.escape(branch_cmp)}\b", desc):
        return True
    return branch_cmp in desc


def find_warehouse_ref(
    city_ref: str,
    branch_number: str,
    *,
    office_title: str = "",
    office_address: str = "",
) -> tuple[str, str]:
    branch = re.sub(r"\D", "", str(branch_number or ""))
    if not city_ref:
        return "", "Немає CityRef для пошуку відділення НП."
    if not branch and not office_title and not office_address:
        return "", "Не вказано відділення НП (немає номера чи адреси з Епіцентр)."

    search_calls: list[dict] = [{"CityRef": city_ref, "Limit": "500", "Language": "UA"}]
    if branch:
        search_calls.insert(
            0,
            {
                "CityRef": city_ref,
                "FindByString": branch,
                "Limit": "50",
                "Language": "UA",
            },
        )
    title_q = str(office_title or "").strip()
    if len(title_q) >= 3:
        search_calls.append(
            {
                "CityRef": city_ref,
                "FindByString": title_q[:40],
                "Limit": "50",
                "Language": "UA",
            },
        )

    seen: set[str] = set()
    rows_all: list[dict] = []
    for props in search_calls:
        rows, err = _np_call("Address", "getWarehouses", props)
        if err:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = str(row.get("Ref") or "").strip()
            if ref and ref not in seen:
                seen.add(ref)
                rows_all.append(row)

    if branch:
        for row in rows_all:
            if _warehouse_matches_branch(row, branch):
                ref = str(row.get("Ref") or "").strip()
                if ref:
                    return ref, ""

    title_l = title_q.lower()
    addr_l = str(office_address or "").strip().lower()
    if title_l or addr_l:
        for row in rows_all:
            desc = str(row.get("Description") or row.get("ShortAddress") or "").lower()
            if title_l and title_l[:24] in desc:
                ref = str(row.get("Ref") or "").strip()
                if ref:
                    return ref, ""
            if addr_l and len(addr_l) >= 8 and addr_l in desc:
                ref = str(row.get("Ref") or "").strip()
                if ref:
                    return ref, ""

    hint = f"№{branch}" if branch else (title_q[:60] or office_address[:60] or "—")
    return "", f"Відділення {hint} не знайдено в НП для обраного міста."


def resolve_recipient_warehouse(prefill: dict, city_ref: str) -> tuple[str, str, str]:
    """Повертає (warehouse_ref, city_ref, error)."""
    np_ref = str(prefill.get("np_warehouse_ref") or "").strip()
    if np_ref:
        wh, werr = warehouse_by_ref(np_ref)
        if werr:
            return "", city_ref, werr
        if isinstance(wh, dict):
            city_from_wh = str(wh.get("CityRef") or "").strip()
            return np_ref, city_from_wh or city_ref, ""
        return np_ref, city_ref, ""

    place_number = str(prefill.get("place_number") or "").strip()
    wh_ref, werr = find_warehouse_ref(
        city_ref,
        place_number,
        office_title=str(prefill.get("office_title") or ""),
        office_address=str(prefill.get("office_address") or ""),
    )
    if werr:
        place_hint = str(prefill.get("office_title") or prefill.get("place_number") or "").strip()
        extra = f" ({place_hint})" if place_hint else ""
        return "", city_ref, werr + extra
    return wh_ref, city_ref, ""


_NAME_BAD_CHARS = re.compile(r"[^А-ЯІЇЄҐа-яіїєґA-Za-z'\-\s]", re.UNICODE)


def _sanitize_name_part(val: str) -> str:
    s = _NAME_BAD_CHARS.sub("", str(val or "").strip())
    return re.sub(r"\s+", " ", s).strip()[:64]


def _recipient_name_parts(prefill: dict) -> tuple[str, str, str, str]:
    last = _sanitize_name_part(prefill.get("lastname"))
    first = _sanitize_name_part(prefill.get("firstname"))
    middle = _sanitize_name_part(prefill.get("middlename")) or "О"
    if len(last) < 2 or len(first) < 2:
        return "", "", "", "Некоректне ПІБ одержувача (потрібні прізвище та ім'я)."
    return last, first, middle, ""


def _np_date() -> str:
    try:
        tz = ZoneInfo("Europe/Kyiv")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).strftime("%d.%m.%Y")


def _parcel_dims(prefill: dict) -> tuple[float, int, int, int]:
    weight_kg = 0.0
    if prefill.get("weight_kg") is not None:
        try:
            weight_kg = float(prefill.get("weight_kg"))
        except (TypeError, ValueError):
            weight_kg = 0.0
    if weight_kg <= 0:
        try:
            weight_g = int(prefill.get("weight_g") or 500)
        except (TypeError, ValueError):
            weight_g = 500
        weight_kg = weight_g / 1000.0
    try:
        length_cm = int(prefill.get("length_cm") or 30)
    except (TypeError, ValueError):
        length_cm = 30
    try:
        width_cm = int(prefill.get("width_cm") or 20)
    except (TypeError, ValueError):
        width_cm = 20
    try:
        height_cm = int(prefill.get("height_cm") or 10)
    except (TypeError, ValueError):
        height_cm = 10
    weight_kg = max(0.1, min(30.0, weight_kg))
    length_cm = max(1, min(200, length_cm))
    width_cm = max(1, min(200, width_cm))
    height_cm = max(1, min(200, height_cm))
    return weight_kg, length_cm, width_cm, height_cm


def _options_seat_from_prefill(prefill: dict) -> list[dict[str, str]]:
    weight_kg, length_cm, width_cm, height_cm = _parcel_dims(prefill)
    volume = max((length_cm * width_cm * height_cm) / 1_000_000.0, 0.0001)
    return [
        {
            "volumetricVolume": str(round(volume, 4)),
            "volumetricLength": str(length_cm),
            "volumetricWidth": str(width_cm),
            "volumetricHeight": str(height_cm),
            "weight": str(round(weight_kg, 2)),
        }
    ]


def _extract_contact_ref(counterparty_row: dict) -> str:
    if not isinstance(counterparty_row, dict):
        return ""
    contact = counterparty_row.get("ContactPerson")
    if isinstance(contact, dict):
        items = contact.get("data")
        if isinstance(items, list) and items:
            row = items[0]
            if isinstance(row, dict):
                return str(row.get("Ref") or "").strip()
    for key in ("ContactRecipient", "ContactSender"):
        val = str(counterparty_row.get(key) or "").strip()
        if val:
            return val
    return ""


def _recipient_name_line(last: str, first: str, middle: str) -> str:
    parts = [last, first]
    if middle:
        parts.append(middle)
    return " ".join(p for p in parts if p).strip()


def _phone_matches_np(row_phone: str, target: str) -> bool:
    a = _phone_np(row_phone)
    b = _phone_np(target)
    if not a or not b:
        return False
    return a == b or a[-10:] == b[-10:]


def _find_recipient_by_phone(phone: str) -> tuple[str, str]:
    phone = _phone_np(phone)
    if len(phone) < 12:
        return "", ""
    rows, err = _np_call(
        "Counterparty",
        "getCounterparties",
        {"CounterpartyProperty": "Recipient", "Page": "1", "FindByString": phone[-10:]},
    )
    if err or not isinstance(rows, list):
        return "", ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        phones = row.get("Phones")
        phone_ok = _phone_matches_np(str(row.get("Phone") or ""), phone)
        if isinstance(phones, str) and phones:
            phone_ok = phone_ok or _phone_matches_np(phones, phone)
        if not phone_ok:
            continue
        cp_ref = str(row.get("Ref") or "").strip()
        if not cp_ref:
            continue
        contacts, _ = _np_call(
            "Counterparty",
            "getCounterpartyContactPersons",
            {"Ref": cp_ref, "Page": "1"},
        )
        if isinstance(contacts, list) and contacts:
            c0 = contacts[0] if isinstance(contacts[0], dict) else {}
            contact_ref = str(c0.get("Ref") or "").strip()
            if contact_ref:
                return cp_ref, contact_ref
    return "", ""


def _resolve_recipient_refs(
    *,
    last: str,
    first: str,
    middle: str,
    phone: str,
    city_ref: str,
    warehouse_ref: str = "",
) -> tuple[str, str, str]:
    """Знайти або створити отримувача в НП (як у lis-dev/nova-poshta-api-2)."""
    phone = _phone_np(phone)
    cp_ref, contact_ref = _find_recipient_by_phone(phone)
    if cp_ref and contact_ref:
        return cp_ref, contact_ref, ""

    phone_local = _phone_local(phone)
    props: dict[str, Any] = {
        "CounterpartyProperty": "Recipient",
        "CounterpartyType": "PrivatePerson",
        "FirstName": first,
        "LastName": last,
        "MiddleName": middle or "",
        "Phone": phone_local,
        "Email": "",
    }
    if city_ref:
        props["CityRef"] = city_ref
    if warehouse_ref:
        props["RecipientAddress"] = warehouse_ref
    data, err = _np_call("Counterparty", "save", props)
    if err:
        return "", "", err
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        return "", "", "НП не повернула дані отримувача."
    cp_ref = str(row.get("Ref") or "").strip()
    contact_ref = _extract_contact_ref(row)
    if cp_ref and contact_ref:
        return cp_ref, contact_ref, ""

    if cp_ref and not contact_ref:
        cdata, cerr = _np_call(
            "ContactPerson",
            "save",
            {
                "CounterpartyRef": cp_ref,
                "FirstName": first,
                "LastName": last,
                "MiddleName": middle or "",
                "Phone": phone_local,
            },
        )
        if cerr:
            return "", "", cerr
        crow = cdata[0] if isinstance(cdata, list) and cdata else cdata
        if isinstance(crow, dict):
            contact_ref = str(crow.get("Ref") or "").strip()
        if cp_ref and contact_ref:
            return cp_ref, contact_ref, ""

    return "", "", "Не вдалося створити контрагента-отримувача в НП."


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

    last, first, middle, nerr = _recipient_name_parts(prefill)
    if nerr:
        return "", nerr
    rphone = _phone_np(str(prefill.get("phone") or ""))
    if len(rphone) < 12:
        return "", "Некоректний телефон одержувача."

    city = str(prefill.get("city") or "").strip()
    region = str(prefill.get("region") or "").strip()
    city_ref, cerr = find_city_ref(city, region)
    if cerr:
        return "", cerr

    place_number = str(prefill.get("place_number") or "").strip()
    np_ref_direct = str(prefill.get("np_warehouse_ref") or "").strip()
    to_branch = bool(prefill.get("delivery_to_branch")) or bool(place_number) or bool(np_ref_direct)
    recipient_address_ref = ""
    service_type = "WarehouseWarehouse"
    if to_branch:
        recipient_address_ref, city_ref, werr = resolve_recipient_warehouse(prefill, city_ref)
        if werr:
            return "", werr
    else:
        street = str(prefill.get("street") or "").strip()
        house = str(prefill.get("house") or "").strip()
        if not street:
            return "", "Для НП потрібне відділення або адреса доставки (вулиця)."
        service_type = "WarehouseDoors"

    weight_kg, length_cm, width_cm, height_cm = _parcel_dims(prefill)
    volume = max((length_cm * width_cm * height_cm) / 1_000_000.0, 0.0001)
    options_seat = _options_seat_from_prefill(prefill)
    if not options_seat:
        return "", "Не задані габарити відправлення (OptionsSeat)."
    recipient_name = _recipient_name_line(last, first, middle)

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

    def _base_props() -> dict[str, Any]:
        props: dict[str, Any] = {
            "PayerType": "Recipient",
            "PaymentMethod": "Cash",
            "DateTime": _np_date(),
            "CargoType": "Cargo",
            "Weight": str(round(weight_kg, 2)),
            "VolumeGeneral": str(round(volume, 4)),
            "VolumeWeight": str(round(weight_kg, 2)),
            "ServiceType": service_type,
            "SeatsAmount": "1",
            "Description": desc,
            "Cost": str(int(round(cost))),
            "CitySender": sender["CitySender"],
            "Sender": sender["Sender"],
            "SenderAddress": sender["SenderAddress"],
            "ContactSender": sender["ContactSender"],
            "SendersPhone": phone,
            "RecipientsPhone": rphone,
            "OptionsSeat": options_seat,
        }
        if invoice:
            props["AdditionalInformation"] = invoice[:100]
        if postpay >= 1:
            props["AfterpaymentOnGoodsCost"] = str(int(round(postpay)))
        return props

    attempts: list[tuple[str, dict[str, Any]]] = []

    recipient_ref = ""
    contact_ref = ""
    if service_type == "WarehouseWarehouse" and recipient_address_ref:
        recipient_ref, contact_ref, _ = _resolve_recipient_refs(
            last=last,
            first=first,
            middle=middle,
            phone=rphone,
            city_ref=city_ref,
            warehouse_ref=recipient_address_ref,
        )
    if recipient_ref and contact_ref:
        by_ref = _base_props()
        by_ref.update(
            {
                "CityRecipient": city_ref,
                "Recipient": recipient_ref,
                "ContactRecipient": contact_ref,
                "RecipientAddress": recipient_address_ref,
            }
        )
        attempts.append(("refs", by_ref))

    by_name_uuid = _base_props()
    by_name_uuid.update(
        {
            "NewAddress": "1",
            "RecipientName": recipient_name,
            "RecipientType": "PrivatePerson",
            "RecipientContactName": recipient_name,
            "CityRecipient": city_ref,
        }
    )
    if service_type == "WarehouseWarehouse":
        by_name_uuid["RecipientAddress"] = recipient_address_ref
    else:
        by_name_uuid["RecipientCityName"] = city
        if region:
            by_name_uuid["RecipientArea"] = region
        by_name_uuid["RecipientAddressName"] = street
        by_name_uuid["RecipientHouse"] = house
        apt = str(prefill.get("apartment") or "").strip()
        if apt:
            by_name_uuid["RecipientFlat"] = apt
    attempts.append(("name_uuid", by_name_uuid))

    if service_type == "WarehouseWarehouse" and place_number:
        by_name_str = _base_props()
        by_name_str.update(
            {
                "NewAddress": "1",
                "RecipientName": recipient_name,
                "RecipientType": "PrivatePerson",
                "RecipientContactName": recipient_name,
                "RecipientCityName": city,
                "RecipientArea": region,
                "RecipientAreaRegions": "",
                "RecipientAddressName": place_number,
                "RecipientHouse": "",
                "RecipientFlat": "",
            }
        )
        attempts.append(("name_string", by_name_str))

    data = None
    err = ""
    for _mode, props in attempts:
        data, err = _np_call("InternetDocument", "save", props)
        if not err:
            break
    if err:
        return "", err
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        return "", "НП прийняла запит, але номер ТТН не повернула."
    ttn = utils.clean_ttn(str(row.get("IntDocNumber") or row.get("Ref") or ""))
    if not ttn:
        return "", "У відповіді НП немає номера ТТН."
    return ttn, ""
