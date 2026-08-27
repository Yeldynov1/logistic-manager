"""Читання статусу Укрпошти без залежності від Streamlit-інтерфейсу."""
from __future__ import annotations

import re

import config
import utils
from services.status_worker import CarrierStatus


def _barcode(value) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits and len(digits) == 12:
        return "0" + digits
    return digits or raw


def _extract_phone(value) -> str:
    phone_keys = {
        "phone",
        "phoneNumber",
        "phone_number",
        "recipientPhone",
        "senderPhone",
        "contactPhone",
        "phoneMobile",
        "mobile",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if key in phone_keys and item:
                phone = utils.clean_phone(item)
                if len(phone) >= 10:
                    return phone
            phone = _extract_phone(item)
            if phone:
                return phone
    elif isinstance(value, list):
        for item in value:
            phone = _extract_phone(item)
            if phone:
                return phone
    return ""


def _ecom_headers() -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if config.UP_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {config.UP_BEARER_TOKEN}"
    if config.UP_UUID:
        headers["X-UUID"] = config.UP_UUID
    if config.UP_UUID_SAND:
        headers["X-UUID-SAND"] = config.UP_UUID_SAND
    if config.UP_COUNTERPARTY_TOKEN:
        headers["X-COUNTERPARTY-TOKEN"] = config.UP_COUNTERPARTY_TOKEN
    return headers


def _from_ecom(barcode: str):
    if not config.UP_USER_TOKEN:
        return None
    url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
    response = utils.make_request(
        "GET",
        url,
        headers=_ecom_headers(),
        params={"token": config.UP_USER_TOKEN},
        timeout=45,
    )
    if not response or response.status_code != 200:
        return None
    data = response.json()
    if not isinstance(data, dict):
        return None
    lifecycle = data.get("lifecycle") if isinstance(data.get("lifecycle"), dict) else {}
    status = lifecycle.get("eventName") or lifecycle.get("status")
    if not status:
        return None
    return CarrierStatus(
        status=utils.up_status_to_ukrainian(status),
        date=str(lifecycle.get("date") or data.get("lastModified") or ""),
        phone=_extract_phone(data),
    )


def _from_tracking(barcode: str):
    if not config.UP_TRACKING_TOKEN:
        return None
    response = utils.make_request(
        "GET",
        "https://www.ukrposhta.ua/status-tracking/0.0.1/statuses",
        headers={
            "Authorization": f"Bearer {config.UP_TRACKING_TOKEN}",
            "Accept": "application/json",
        },
        params={"barcode": barcode, "lang": "UA"},
        timeout=45,
    )
    if not response or response.status_code != 200:
        return None
    data = response.json()
    if not isinstance(data, list) or not data:
        return None
    last = data[-1] if isinstance(data[-1], dict) else {}
    status = last.get("eventName") or last.get("status")
    if not status:
        return None
    return CarrierStatus(
        status=utils.up_status_to_ukrainian(status),
        date=str(last.get("date") or ""),
        phone=_extract_phone(data),
    )


def fetch_tracking_status(value):
    """Спочатку eCom, потім офіційний tracking API як резерв."""
    barcode = _barcode(value)
    if not barcode:
        return None
    try:
        result = _from_ecom(barcode)
        if result is not None:
            return result
    except Exception:
        pass
    try:
        return _from_tracking(barcode)
    except Exception:
        return None
