import streamlit as st
import pandas as pd
import time
import threading
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import hashlib
import html
import requests
import re

# --- ПІДКЛЮЧЕННЯ МОДУЛІВ ---
import auth  # Локальний вхід (bcrypt + Secrets)
import config  # Налаштування
import utils  # Технічні функції
import ui_theme
from core.audit import (
    audit_log,
    audit_lookup_receipt_sum,
    cached_audit_log_df,
    render_audit_tab,
)
from core.messages import ensure_messages_exist
from core.table_data import (
    apply_table_column_order,
    ensure_columns,
    get_table_column_order,
    restore_leading_zero,
)
from services.checkbox_archive import (
    archive_shift_day,
    fetch_checkbox_archive,
    used_checkbox_links_from_df,
)
from tabs import tab1_checkout, tab2_table, tab3_refusals, tab4_archive, tab5_reminders, tab_rozetka
from services import rozetka as rozetka_api
from tabs.tab1_checkout import _tab1_without_sent_rows
from ui.components import render_copyable_invoice, render_smart_buttons

_cached_audit_log_df = cached_audit_log_df
_audit_lookup_receipt_sum = audit_lookup_receipt_sum

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="Alius Checkbox", page_icon="☑️", layout="wide")

import sheets  # Google Sheets (після set_page_config — коректна реєстрація st.cache_data у sheets)


@st.cache_data(ttl=30)
def _cached_up_shipments_df():
    return sheets.read_up_shipments()




# ==========================================
# 🔌 АВТО-ПІДКЛЮЧЕННЯ СЕКРЕТІВ
# ==========================================
def _read_st_secret(key: str) -> str:
    return config.get_secret(key)


def _up_mask_token(val: str) -> str:
    s = str(val or "").strip()
    if len(s) <= 10:
        return "✓" if s else "—"
    return f"{s[:6]}…{s[-4:]}"


_UP_CONFIG_KEYS = (
    "UP_TRACKING_TOKEN",
    "UP_BEARER_TOKEN",
    "UP_CLASSIFIER_BEARER",
    "UP_USER_TOKEN",
    "UP_UUID",
    "UP_UUID_SAND",
    "UP_COUNTERPARTY_TOKEN",
    "UP_SENDER_UUID",
    "UP_SENDER_ADDRESS_ID",
    "UP_SENDER_NAME",
    "UP_SENDER_PHONE",
    "UP_SENDER_ADDRESS",
    "UP_SENDER_POSTCODE",
    "UP_SENDER_BRANCH_INDEX",
    "UP_SENDER_TIN",
    "UP_SENDER_BANK_ACCOUNT",
    "UP_SENDER_TYPE",
    "UP_CABINET_URL",
    "API_KEY_NP",
    "CHECKBOX_LICENSE_KEY",
    "CHECKBOX_PASSWORD",
    "MEEST_API_TOKEN",
)


def _up_secrets_diag() -> dict:
    """Статус ключів УП у Secrets (для діагностики на вкладці)."""
    load_secrets_to_config()
    keys = (
        "UP_BEARER_TOKEN",
        "UP_CLASSIFIER_BEARER",
        "UP_USER_TOKEN",
        "UP_COUNTERPARTY_TOKEN",
        "UP_UUID",
        "UP_SENDER_UUID",
        "UP_TRACKING_TOKEN",
    )
    out = {}
    for k in keys:
        v = _read_st_secret(k) or str(getattr(config, k, "") or "").strip()
        out[k] = _up_mask_token(v)
    top = config.list_secret_top_keys()
    out["_sections"] = ", ".join(top[:16]) if top else "?"
    up_nested = config.list_up_keys_in_secrets()
    up_top = [k for k in top if str(k).startswith("UP_")]
    up_all = list(dict.fromkeys(up_top + up_nested))
    out["_up_keys_in_file"] = ", ".join(up_all) if up_all else "(немає ключів UP_* у файлі)"
    out["_has_inline"] = bool(config.get_secret("UP_INLINE_SECRETS"))
    out["_has_ukrposhta_section"] = "ukrposhta" in top
    missing = [k for k in keys if _up_mask_token(_read_st_secret(k)) == "—"]
    out["_missing"] = missing
    if _up_mask_token(_read_st_secret("UP_TRACKING_TOKEN")) != "—":
        src = config.secret_source("UP_TRACKING_TOKEN")
        if src:
            out["_tracking_source"] = src
    return out


def load_secrets_to_config():
    for key, val in config.load_up_inline_secrets().items():
        if val:
            setattr(config, key, val)
    for key in _UP_CONFIG_KEYS:
        val = _read_st_secret(key)
        if val:
            setattr(config, key, val)
    turbosms = _read_st_secret("TURBOSMS_TOKEN")
    if turbosms:
        setattr(config, "TURBOSMS_TOKEN", turbosms)
    turbosms_sender = _read_st_secret("TURBOSMS_SENDER")
    if turbosms_sender:
        setattr(config, "TURBOSMS_SENDER", turbosms_sender)
    elif not str(getattr(config, "TURBOSMS_SENDER", "") or "").strip():
        config.TURBOSMS_SENDER = "Zamovlenya"
    if not _read_st_secret("UP_USER_TOKEN"):
        cp = _read_st_secret("UP_COUNTERPARTY_TOKEN")
        if cp:
            config.UP_USER_TOKEN = cp

load_secrets_to_config()


# ==========================================
# 🔐 АВТОРИЗАЦІЯ
# ==========================================
def check_password():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            ui_theme.render_theme_selector(sidebar=False)
            ui_theme.inject_app_theme()
            st.markdown('<div class="app-login-card">', unsafe_allow_html=True)
            st.header("🔒 Вхід у систему")
            with st.form("login_form"):
                username = st.text_input("Логін", placeholder="Введіть логін")
                password = st.text_input("Пароль", type="password", placeholder="Введіть пароль")
                submit = st.form_submit_button("Увійти", use_container_width=True, type="primary")

                if submit:
                    if auth.verify_credentials(username, password):
                        st.session_state.logged_in = True
                        st.session_state.auth_user = str(username).strip() or "?"
                        st.toast("Успішний вхід!", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ Невірний логін або пароль")
            st.markdown("</div>", unsafe_allow_html=True)
            try:
                au = dict(st.secrets["auth_users"]) if hasattr(st, "secrets") and "auth_users" in st.secrets else {}
                has_legacy = bool(getattr(config, "USERS", None))
                if not au and not has_legacy:
                    st.info(
                        "Налаштуйте вхід: у Secrets додайте секцію **[auth_users]** (логін = bcrypt-хеш). "
                        "Згенерувати хеш локально: `python auth.py 'ВашПароль'`"
                    )
            except Exception:
                pass
        return False
    return True

if not check_password():
    st.stop()


# ==========================================
# 🌐 API ФУНКЦІЇ
# ==========================================

# --- НОВА ПОШТА ---
def get_np_statuses_bulk(ttn_list):
    if not ttn_list: return {}
    chunks = [ttn_list[i:i + 100] for i in range(0, len(ttn_list), 100)]
    results = {}
    for chunk in chunks:
        documents = [{"DocumentNumber": ttn} for ttn in chunk]
        try:
            r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
                "apiKey": config.API_KEY_NP, "modelName": "TrackingDocument", 
                "calledMethod": "getStatusDocuments", "methodProperties": {"Documents": documents}
            })
            if r and r.json()['success']:
                for item in r.json()['data']:
                    ttn = item.get('Number')
                    if ttn:
                        results[ttn] = {
                            "Status": item.get('Status', ''),
                            "Cost": float(item.get('AnnouncedPrice') or 0),
                            "Phone": item.get('RecipientPhone', ''),
                            "ClientBarcode": item.get('ClientBarcode', '')
                        }
        except Exception: pass
    return results

def debug_np_api(ttn):
    """Показує все поля з API Novaposhta для одного ТТН"""
    documents = [{"DocumentNumber": ttn}]
    try:
        r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
            "apiKey": config.API_KEY_NP, 
            "modelName": "TrackingDocument", 
            "calledMethod": "getStatusDocuments", 
            "methodProperties": {"Documents": documents}
        })
        if r and r.json().get('success'):
            data = r.json().get('data', [])
            return data[0] if data else {"error": "Дані не знайдені для цього ТТН"}
        return {"error": r.json().get('errors', 'Помилка API') if r else 'No response'}
    except Exception as e:
        return {"error": str(e)}


def debug_make_request(method, url, **kwargs):
    try:
        r = requests.request(method, url, **kwargs)
        return r, None
    except Exception as e:
        return None, str(e)


def debug_up_api(barcode, uuid=None, uuid_sand=None, bearer_token=None, user_token=None, tracking_token=None, custom_url=None):
    """Показує всі поля з API Укрпошти для одного баркоду"""
    if len(barcode) == 12 and barcode.isdigit():
        barcode = "0" + barcode
    result = {'uuid': uuid, 'uuid_sand': uuid_sand}

    if bearer_token and len(bearer_token) > 10 and user_token:
        url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
        headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        params = {"token": user_token}
        headers["X-COUNTERPARTY-TOKEN"] = user_token
        r, err = debug_make_request("GET", url, headers=headers, params=params)
        result['ecom_url'] = url
        result['ecom_headers'] = headers
        result['ecom_params'] = params
        result['ecom_status_code'] = r.status_code if r else None
        if r:
            try:
                result['ecom_json'] = r.json()
            except Exception:
                result['ecom_text'] = r.text
        else:
            result['ecom_error'] = err

    if tracking_token and len(tracking_token) > 10:
        url = f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}"
        headers = {"Authorization": f"Bearer {tracking_token}", "Accept": "application/json"}
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        r, err = debug_make_request("GET", url, headers=headers)
        result['tracking_url'] = url
        result['tracking_headers'] = headers
        result['tracking_status_code'] = r.status_code if r else None
        if r:
            try:
                result['tracking_json'] = r.json()
            except Exception:
                result['tracking_text'] = r.text
        else:
            result['tracking_error'] = err

    if custom_url:
        url = custom_url.strip()
        headers = {}
        params = {}
        if bearer_token and len(bearer_token) > 10:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if user_token:
            params["token"] = user_token
            headers["X-COUNTERPARTY-TOKEN"] = user_token
        if tracking_token and not headers:
            headers["Authorization"] = f"Bearer {tracking_token}"
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        r, err = debug_make_request("GET", url, headers=headers or None, params=params or None)
        result['custom_url'] = url
        result['custom_headers'] = headers
        result['custom_params'] = params
        result['custom_status_code'] = r.status_code if r else None
        if r:
            try:
                result['custom_json'] = r.json()
            except Exception:
                result['custom_text'] = r.text
        else:
            result['custom_error'] = err

    if len(result) == 2 and not result.get('ecom_json') and not result.get('tracking_json') and not result.get('custom_json'):
        result['error'] = 'Не передано жодного токена або URL для перевірки'
    return result

def fetch_new_orders_np(existing_ttns):
    date_from = (utils.now_kyiv_naive() - timedelta(days=60)).strftime("%d.%m.%Y")
    date_to = utils.now_kyiv_naive().strftime("%d.%m.%Y")
    new_rows = []

    r_out = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList",
        "methodProperties": {"DateFrom": date_from, "DateTo": date_to, "GetFullList": "1", "Limit": "500"}
    })
    r_in = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getIncomingDocuments",
        "methodProperties": {"DateFrom": date_from, "DateTo": date_to, "Limit": "500"}
    })

    out_list = r_out.json().get('data', []) if r_out and r_out.json()['success'] else []
    in_list = r_in.json().get('data', []) if r_in and r_in.json()['success'] else []
    
    st.toast(f"📡 Знайдено в API: Вихідних {len(out_list)}, Вхідних {len(in_list)}", icon="🕵️")
    all_docs = out_list + in_list

    for doc in all_docs:
        ttn = utils.clean_ttn(str(doc.get('IntDocNumber') or doc.get('DocumentNumber'))) 
        client_barcode = doc.get('ClientBarcode', '')
        status = str(doc.get('StateName', ''))
        
        if ttn and ttn not in existing_ttns and not utils.status_has_any(status, utils.DELIVERED_STATUS_KEYWORDS + utils.DECLINED_STATUS_KEYWORDS):
            cost = float(doc.get('Cost') or doc.get('DeclaredCost') or 0)
            date = utils.normalize_date(doc.get('CreateTime') or doc.get('DateTime', ''))
            phone = utils.clean_phone(doc.get('RecipientContactPhone') or doc.get('SenderContactPhone', ''))

            new_rows.append({
                "ТТН": ttn, "Служба": "НП", "Статус": status, "Дата": date,
                "Телефон": phone, "Вартість": cost, "Номер накладної": utils.normalize_invoice_number(client_barcode), "Чек": "", 
                "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
            })
            existing_ttns.append(ttn)
    return new_rows

# --- УКРПОШТА ---
def extract_phone_from_data(data):
    if isinstance(data, dict):
        phone_keys = {"phone", "phoneNumber", "phone_number", "recipientPhone", "senderPhone", "contactPhone", "phoneMobile", "mobile"}
        for key, value in data.items():
            if isinstance(key, str) and key in phone_keys and value:
                return utils.clean_phone(str(value))
            if isinstance(value, dict):
                p = extract_phone_from_data(value)
                if p:
                    return p
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        p = extract_phone_from_data(item)
                        if p:
                            return p
                    elif isinstance(item, str):
                        digits = re.sub(r"\D", "", item)
                        if len(digits) >= 9:
                            return utils.clean_phone(item)
    return ""

def format_up_extra_info(data, barcode=None):
    if not isinstance(data, dict):
        return ""
    info = []
    recipient = data.get('recipient') or {}
    sender = data.get('sender') or {}
    if isinstance(recipient, dict):
        name = " ".join(filter(None, [recipient.get('fullName'), recipient.get('firstName'), recipient.get('lastName')]))
        if name:
            info.append(f"Отримувач: {name}")
        phone = extract_phone_from_data(recipient)
        if phone:
            info.append(f"Телефон отримувача: {phone}")
    if isinstance(sender, dict):
        name = " ".join(filter(None, [sender.get('fullName'), sender.get('firstName'), sender.get('lastName')]))
        if name:
            info.append(f"Відправник: {name}")
        phone = extract_phone_from_data(sender)
        if phone:
            info.append(f"Телефон відправника: {phone}")
    for key, label in [
        ('originLocationName', 'Звідки'),
        ('destinationLocationName', 'Куди'),
        ('shipmentNumber', 'Номер відправлення'),
        ('registrationDate', 'Зареєстровано'),
        ('lastModified', 'Останнє оновлення'),
        ('deliveryDate', 'Дата доставки'),
        ('status', 'Статус'),
        ('barcode', 'Barcode'),
        ('barCode', 'Barcode')
    ]:
        value = data.get(key)
        if not value:
            continue
        if key == 'shipmentNumber' and barcode and str(value) == str(barcode):
            continue
        info.append(f"{label}: {value}")
    if not info:
        return ""
    return " | ".join(info)

def build_up_headers(bearer_token=None, uuid=None, uuid_sand=None, counterparty_token=None, include_content_type=True):
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if uuid:
        headers["X-UUID"] = uuid
    if uuid_sand:
        headers["X-UUID-SAND"] = uuid_sand
    if counterparty_token:
        headers["X-COUNTERPARTY-TOKEN"] = counterparty_token
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def get_up_status_smart(barcode):
    if len(barcode) == 12 and barcode.isdigit():
        barcode = "0" + barcode
    phone = ""
    extra = ""
    if config.UP_USER_TOKEN:
        try:
            url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
            headers = build_up_headers(
                bearer_token=config.UP_BEARER_TOKEN,
                uuid=config.UP_UUID,
                uuid_sand=config.UP_UUID_SAND,
                counterparty_token=config.UP_COUNTERPARTY_TOKEN
            )
            params = {"token": config.UP_USER_TOKEN}
            r = utils.make_request("GET", url, headers=headers, params=params)
            if r and r.status_code == 200:
                data = r.json() or {}
                status_raw = data.get('lifecycle', {}).get('status')
                last_event = data.get('lifecycle', {}).get('eventName')
                final_status = last_event if last_event else (status_raw if status_raw else "В дорозі")
                date_raw = data.get('lifecycle', {}).get('date') or data.get('lastModified')
                phone = extract_phone_from_data(data)
                extra = format_up_extra_info(data, barcode)
                return final_status, utils.normalize_date(date_raw), 0.0, phone, extra
        except Exception:
            pass
    try:
        r = utils.make_request("GET", f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}", 
                         headers={"Authorization": f"Bearer {config.UP_TRACKING_TOKEN}", "Accept": "application/json"})
        if r and r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                last = data[-1]
                phone = extract_phone_from_data(data)
                extra = format_up_extra_info(data, barcode)
                return last.get('eventName', 'В дорозі'), utils.normalize_date(last.get('date', '')), 0.0, phone, extra
    except Exception:
        pass
    return "Не знайдено", None, 0.0, phone, extra

def fetch_new_orders_up(existing_ttns):
    if not config.UP_USER_TOKEN: return []
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    d_from = (utils.now_kyiv_naive() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {"token": config.UP_USER_TOKEN, "lastModifiedFrom": d_from}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID,
        uuid_sand=config.UP_UUID_SAND,
        counterparty_token=config.UP_COUNTERPARTY_TOKEN
    )
    try:
        r = utils.make_request("GET", url, headers=headers, params=params)
        if not r or r.status_code != 200: return []
        new_rows = []
        data = r.json()
        shipments = data if isinstance(data, list) else data.get('shipments', [])
        for s in shipments:
            ttn = s.get('barcode')
            if ttn and ttn not in existing_ttns:
                date = utils.normalize_date(s.get('registrationDate', '') or s.get('lastModified', ''))
                cost = float(s.get('declaredPrice', 0))
                phone = ""
                if s.get('recipient'): phone = utils.clean_phone(s.get('recipient', {}).get('phoneNumber', ''))
                new_rows.append({
                    "ТТН": ttn, "Служба": "УП", "Статус": "Нове", "Дата": date,
                    "Телефон": phone, "Вартість": cost, "Номер накладної": "", "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                })
        return new_rows
    except Exception:
        return []


def up_post_shipment_create(body: dict):
    """Створює відправлення Укрпошти (eCom POST /shipments). Повертає (response_dict|None, error_or_status)."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN у Secrets."
    if not str(getattr(config, "UP_UUID", "") or "").strip():
        return None, "Немає UP_UUID у Secrets."
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    params = {"token": ecom_token}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token,
        include_content_type=True,
    )
    try:
        r = utils.make_request("POST", url, headers=headers, params=params, json=body, timeout=60)
        if not r:
            hint = utils.get_last_request_error()
            msg = "Немає відповіді від сервера Укрпошти (eCom)."
            if hint:
                msg += f" ({hint})"
            return None, msg
        if r.status_code == 200 or r.status_code == 201:
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        try:
            err_js = r.json()
        except Exception:
            err_js = {"text": r.text[:800]}
        return None, _up_format_ecom_error(f"HTTP {r.status_code}: {err_js}")
    except Exception as e:
        return None, str(e)[:500]


def _up_normalize_bc(barcode_or_uuid: str) -> str:
    return _up_format_bc_display(barcode_or_uuid)


def _up_format_bc_display(val) -> str:
    """ШКІ як текст: зберігаємо провідний 0 (13 цифр)."""
    if val is None:
        return ""
    if isinstance(val, float):
        if val != val:
            return ""
        try:
            val = int(val)
        except Exception:
            pass
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return s
    if len(digits) == 12:
        digits = "0" + digits
    return digits


def _up_phone_for_input(val) -> str:
    """Телефон для полів вводу та журналу: завжди з префіксом +38."""
    raw = str(val or "").strip()
    if not raw or raw in ("+3", "+38", "+380"):
        return "+38"
    d = utils.clean_phone(raw)
    if d:
        return f"+{d}"
    if raw.startswith("+38"):
        return raw
    return "+38"


def _up_phone_for_journal(val) -> str:
    p = _up_phone_for_input(val)
    return "" if p == "+38" else p


def _up_on_phone_input_change(key: str):
    st.session_state[key] = _up_phone_for_input(st.session_state.get(key, ""))


def _up_tariff_journal_label(val) -> str:
  s = str(val or "").strip()
  if s.startswith("Прі") or s.upper() in ("EXPRESS", "P", "П"):
    return "П"
  if s.startswith("Баз") or s.upper() in ("STANDARD", "B", "Б"):
    return "Б"
  return s[:1] if s else "—"


# eCom API: shipment.description — до 40 символів (док. Укрпошти)
_UP_SHIPMENT_DESC_MAX = 40
# eCom: width/height обовʼязкові для розрахунку (UPE01002), якщо користувач не вказав — типове місце
_UP_DEFAULT_PARCEL_WEIGHT_G = 500
_UP_DEFAULT_PARCEL_LENGTH_CM = 30
_UP_DEFAULT_PARCEL_WIDTH_CM = 20
_UP_DEFAULT_PARCEL_HEIGHT_CM = 10


def _up_normalize_parcel_dims(
    grams=None, length=None, width=None, height=None
) -> tuple[int, int, int, int]:
    """Вага та габарити (см) для POST/PUT parcels — width/height не можуть бути 0."""
    w = max(1, _up_num_int(grams if grams is not None else _UP_DEFAULT_PARCEL_WEIGHT_G))
    ln = max(
        1,
        min(
            _up_num_int(length if length is not None else _UP_DEFAULT_PARCEL_LENGTH_CM),
            200,
        ),
    )
    wid = _up_num_int(width)
    hgt = _up_num_int(height)
    if wid < 1:
        wid = _UP_DEFAULT_PARCEL_WIDTH_CM
    if hgt < 1:
        hgt = _UP_DEFAULT_PARCEL_HEIGHT_CM
    return w, ln, min(wid, 200), min(hgt, 200)


def _up_status_journal_label(val) -> str:
  s = str(val or "").strip().upper()
  if s == "DRAFT":
    return "чернетка"
  if s == "CREATED":
    return "створено"
  if len(s) <= 12:
    return s or "—"
  return s[:12]


def _up_journal_cell(
  text: str, *, lines: list[str] | None = None, cell_class: str = ""
) -> None:
  if lines:
    parts = [str(x).strip() for x in lines if str(x or "").strip()]
    if not parts:
      parts = ["—"]
    inner = "<br>".join(html.escape(p) for p in parts)
    title = html.escape(" · ".join(parts))
    extra_cls = " up-journal-multiline"
  else:
    inner = html.escape(str(text if text not in (None, "") else "—"))
    title = inner
    extra_cls = ""
  if cell_class:
    extra_cls += f" {cell_class}"
  st.markdown(
    f'<p class="up-journal-cell{extra_cls}" title="{title}">{inner}</p>',
    unsafe_allow_html=True,
  )


def _up_journal_time_lines(ts) -> list[str]:
  s = str(ts or "").strip()[:19]
  if not s:
    return ["—"]
  if " " in s:
    date_part, time_part = s.split(" ", 1)
    if len(date_part) == 10 and date_part[4] == "-":
      try:
        date_part = datetime.strptime(date_part, "%Y-%m-%d").strftime("%d.%m.%Y")
      except Exception:
        pass
    return [date_part, time_part[:8]]
  if "T" in s:
    date_part, time_part = s.split("T", 1)
    if len(date_part) == 10 and date_part[4] == "-":
      try:
        date_part = datetime.strptime(date_part, "%Y-%m-%d").strftime("%d.%m.%Y")
      except Exception:
        pass
    return [date_part, time_part[:8]]
  return [s]


def _up_journal_recipient_lines(name, phone) -> list[str]:
  name = str(name or "").strip()
  ph = _up_phone_for_journal(phone)
  lines: list[str] = []
  if name and name != "—":
    words = name.split()
    if len(words) <= 2:
      lines.append(" ".join(words))
    else:
      lines.append(" ".join(words[:2]))
      lines.append(" ".join(words[2:])[:32])
  if ph:
    lines.append(ph)
  return lines or ["—"]


def _up_fill_wizard_recipient_name_fields(rec: dict) -> None:
  last = str(rec.get("lastName") or "").strip()
  first = str(rec.get("firstName") or "").strip()
  middle = str(rec.get("middleName") or "").strip()
  if not last and not first:
    name = str(rec.get("name") or "").strip()
    if name:
      parts = name.split()
      if len(parts) >= 1:
        last = parts[0]
      if len(parts) >= 2:
        first = parts[1]
      if len(parts) >= 3:
        middle = " ".join(parts[2:])
  st.session_state.upwiz_lastname = last
  st.session_state.upwiz_firstname = first
  st.session_state.upwiz_middlename = middle


def _up_seed_wizard_from_shipment(data: dict, force: bool = False) -> bool:
  """Заповнити форму створення (upwiz_*) для редагування існуючого відправлення."""
  suuid = _up_shipment_uuid_from_response(data)
  if not suuid:
    return False
  if not force and st.session_state.get("upwiz_edit_seeded_uuid") == suuid:
    return True
  _upwiz_clear_parcel_widget_keys()
  parcels = _up_parcels_list_from_response(data)
  n = max(1, len(parcels))
  st.session_state.upwiz_n_parcels = n
  for i in range(n):
    p = parcels[i] if i < len(parcels) else {}
    st.session_state[_upwiz_parcel_key(i, "w")] = int(p.get("weight") or 500)
    st.session_state[_upwiz_parcel_key(i, "len")] = int(p.get("length") or 30)
    st.session_state[_upwiz_parcel_key(i, "wid")] = int(
        p.get("width") or 0
    ) or _UP_DEFAULT_PARCEL_WIDTH_CM
    st.session_state[_upwiz_parcel_key(i, "h")] = int(
        p.get("height") or 0
    ) or _UP_DEFAULT_PARCEL_HEIGHT_CM
    st.session_state[_upwiz_parcel_key(i, "decl")] = float(
      p.get("declaredPrice") or data.get("declaredPrice") or 0
    )
  ship_type = str(data.get("type") or "STANDARD").upper()
  st.session_state.upwiz_service = (
    "Пріоритетний" if ship_type == "EXPRESS" else "Базовий"
  )
  api_delivery = str(data.get("deliveryType") or "W2D").strip()
  inv = {v: k for k, v in _UP_DELIVERY_LABELS.items()}
  st.session_state.upwiz_delivery_label = inv.get(api_delivery, "склад – двері")
  rec = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
  _up_fill_wizard_recipient_name_fields(rec)
  phone = utils.clean_phone(
    str(data.get("recipientPhone") or rec.get("phoneNumber") or "")
  )
  st.session_state.upwiz_phone = _up_phone_for_input(phone)
  addr = _up_recipient_address_from_shipment(data)
  st.session_state.upwiz_index_mode = (
    "Знайти індекс" if str(addr.get("street") or "").strip() else "Знаю індекс"
  )
  for k, v in addr.items():
    st.session_state[f"upwiz_{k}"] = v
    st.session_state[f"upwiz_saved_{k}"] = v
  if addr.get("postcode"):
    st.session_state.upwiz_postcode_lookup_ok = True
    st.session_state.upwiz_postcode_lookup_last = str(addr.get("postcode", ""))[:5]
  _up_set_wizard_description(_up_description_from_shipment_response(data))
  st.session_state.upwiz_postpay_uah = float(data.get("postPay") or 0)
  st.session_state.upwiz_paid_shipment_recipient = bool(data.get("paidByRecipient"))
  st.session_state.upwiz_paid_shipment_who = (
    "Одержувач" if data.get("paidByRecipient") else "Відправник"
  )
  st.session_state.upwiz_paid_postpay_recipient = bool(
    data.get("postPayPaidByRecipient", True)
  )
  st.session_state.upwiz_paid_postpay_who = (
    "Одержувач" if data.get("postPayPaidByRecipient", True) else "Відправник"
  )
  st.session_state.upwiz_transfer_postpay_iban = bool(
    data.get("transferPostPayToBankAccount")
  )
  st.session_state.upwiz_sms = bool(data.get("sms"))
  st.session_state.upwiz_check_delivery = bool(data.get("checkOnDelivery", True))
  fail = str(data.get("onFailReceiveType") or "RETURN").upper()
  st.session_state.upwiz_fail_main = (
    "не повертати" if fail == "PROCESS_AS_REFUSAL" else "повернути"
  )
  rid = _up_recipient_uuid_from_shipment(data)
  st.session_state.upwiz_edit_recipient_uuid = rid
  st.session_state.upwiz_recipient_uuid_manual = rid
  st.session_state.upwiz_edit_shipment_uuid = suuid
  first_p = _up_first_parcel_from_response(data)
  st.session_state.upwiz_edit_parcel_uuid = str(first_p.get("uuid") or "").strip()
  st.session_state.upwiz_edit_barcode = _up_barcode_from_create_response(data) or ""
  st.session_state.upwiz_edit_seeded_uuid = suuid
  st.session_state.upwiz_edit_mode = True
  return True


def _up_sync_wizard_to_edit_state() -> None:
  """Поля майстра → ключі збереження PUT /shipments."""
  st.session_state.up_edit_shipment_uuid = str(
    st.session_state.get("upwiz_edit_shipment_uuid", "")
  )
  st.session_state.up_edit_parcel_uuid = str(
    st.session_state.get("upwiz_edit_parcel_uuid", "")
  )
  st.session_state.up_edit_barcode = str(st.session_state.get("upwiz_edit_barcode", ""))
  st.session_state.up_edit_recipient_uuid = str(
    st.session_state.get("upwiz_recipient_uuid", "")
  ).strip()
  for k in ("lastname", "firstname", "middlename"):
    st.session_state[f"up_edit_{k}"] = str(st.session_state.get(f"upwiz_{k}", ""))
  st.session_state.up_edit_phone = _up_phone_for_input(
    st.session_state.get("upwiz_phone", "")
  )
  for k in ("postcode", "region", "district", "city", "street", "house", "apartment"):
    st.session_state[f"up_edit_{k}"] = str(st.session_state.get(f"upwiz_{k}", ""))
    st.session_state[f"up_edit_saved_{k}"] = str(
      st.session_state.get(f"upwiz_saved_{k}", "")
    )
  svc = st.session_state.get("upwiz_service", "Базовий")
  st.session_state.up_edit_shipment_type = _UP_SERVICE_API.get(svc, "STANDARD")
  st.session_state.up_edit_delivery_label_pick = st.session_state.get(
    "upwiz_delivery_label", "склад – двері"
  )
  st.session_state.up_edit_description = _up_capture_wizard_description()
  plist = _upwiz_parcels_from_form()
  if plist:
    p0 = plist[0]
    st.session_state.up_edit_weight_g = int(p0.get("weight") or 500)
    st.session_state.up_edit_length_cm = int(p0.get("length") or 30)
    st.session_state.up_edit_width_cm = int(p0.get("width") or 0)
    st.session_state.up_edit_height_cm = int(p0.get("height") or 0)
    st.session_state.up_edit_declared_uah = float(p0.get("declaredPrice") or 0)
  st.session_state.up_edit_postpay_uah = _up_num_float(
    st.session_state.get("upwiz_postpay_uah", 0)
  )
  st.session_state.up_edit_paid_shipment_recipient = bool(
    st.session_state.get("upwiz_paid_shipment_recipient")
  )
  st.session_state.up_edit_paid_postpay_recipient = bool(
    st.session_state.get("upwiz_paid_postpay_recipient", True)
  )
  st.session_state.up_edit_transfer_postpay_iban = bool(
    st.session_state.get("upwiz_transfer_postpay_iban")
  )
  st.session_state.up_edit_sms = bool(st.session_state.get("upwiz_sms"))
  st.session_state.up_edit_check_delivery = bool(
    st.session_state.get("upwiz_check_delivery", True)
  )
  st.session_state.up_edit_fail_main = st.session_state.get(
    "upwiz_fail_main", "повернути"
  )


def _up_wizard_commit_saved_snapshot() -> None:
    """Після успішного збереження — нова база для порівняння змін."""
    for k in ("postcode", "region", "district", "city", "street", "house", "apartment"):
        st.session_state[f"upwiz_saved_{k}"] = str(st.session_state.get(f"upwiz_{k}", ""))


def _up_recipient_uuid_from_shipment(data: dict) -> str:
    """UUID клієнта-отримувача з відповіді GET /shipments."""
    if not isinstance(data, dict):
        return ""
    rec = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    for src in (rec, data):
        uid = str(src.get("uuid") or src.get("clientUuid") or src.get("clientUUID") or "").strip()
        if uid and _up_is_valid_uuid(uid):
            return uid
    return ""


def _up_recipient_uuid_for_edit() -> str:
    manual = str(st.session_state.get("upwiz_recipient_uuid_manual", "")).strip()
    if manual and _up_is_valid_uuid(manual):
        return manual
    return str(st.session_state.get("upwiz_edit_recipient_uuid", "")).strip()


def _up_sync_wizard_paid_flags() -> None:
    st.session_state.upwiz_paid_shipment_recipient = (
        st.session_state.get("upwiz_paid_shipment_who") == "Одержувач"
    )
    st.session_state.upwiz_paid_postpay_recipient = (
        st.session_state.get("upwiz_paid_postpay_who") == "Одержувач"
    )


def _up_wizard_address_changed() -> bool:
    for f in ("postcode", "region", "district", "city", "street", "house", "apartment"):
        if str(st.session_state.get(f"upwiz_{f}", "")).strip() != str(
            st.session_state.get(f"upwiz_saved_{f}", "")
        ).strip():
            return True
    return False


def _up_post_address_from_wizard_form():
    """POST /addresses з полів upwiz_*."""
    postcode = str(st.session_state.get("upwiz_postcode", "")).strip()
    region = str(st.session_state.get("upwiz_region", "")).strip()
    district = str(st.session_state.get("upwiz_district", "")).strip()
    city = str(st.session_state.get("upwiz_city", "")).strip()
    street = str(st.session_state.get("upwiz_street", "")).strip()
    house = str(st.session_state.get("upwiz_house", "")).strip()
    apartment = str(st.session_state.get("upwiz_apartment", "")).strip()
    if not postcode or not region or not city:
        return None, "Заповни індекс, область і населений пункт."
    body = {
        "country": "UA",
        "postcode": postcode[:5],
        "region": region[:45],
        "city": city[:45],
    }
    if district:
        body["district"] = district[:45]
    if street:
        body["street"] = street[:255]
    if house:
        body["houseNumber"] = house[:15]
    if apartment:
        body["apartmentNumber"] = apartment[:15]
    data, err = up_ecom_request("POST", "/addresses", body, token_required=False)
    if err:
        return None, f"Адреса: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу не створено: {data}"
    return addr_id, ""


def _up_apply_recipient_updates_from_wizard(rid: str) -> tuple[dict | None, str]:
    """PUT /clients — ПІБ, телефон, нова адреса (з полів форми створення)."""
    if not rid:
        return {}, ""
    last = str(st.session_state.get("upwiz_lastname", "")).strip()
    first = str(st.session_state.get("upwiz_firstname", "")).strip()
    middle = str(st.session_state.get("upwiz_middlename", "")).strip()
    phone = utils.clean_phone(_up_phone_for_input(st.session_state.get("upwiz_phone", "")))
    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    body_client = {}
    if postpay >= 1:
        body_client["lastName"] = last[:250]
        body_client["firstName"] = first[:250]
        body_client["middleName"] = middle[:250]
    else:
        if last:
            body_client["lastName"] = last[:250]
        if first:
            body_client["firstName"] = first[:250]
        if middle:
            body_client["middleName"] = middle[:250]
    if phone and len(phone) >= 10:
        body_client["phoneNumber"] = phone if phone.startswith("+") else f"+{phone}"
    new_addr_id = None
    if _up_wizard_address_changed():
        new_addr_id, err = _up_post_address_from_wizard_form()
        if err:
            return None, err
        body_client["addressId"] = str(new_addr_id)
    if body_client:
        _, err = up_ecom_request("PUT", f"/clients/{rid}", body_client)
        if err:
            return None, f"Отримувач: {err}"
    extra = {}
    if new_addr_id:
        try:
            extra["recipientAddressId"] = int(new_addr_id)
        except ValueError:
            extra["recipientAddressId"] = new_addr_id
    return extra, ""


def _up_build_shipment_update_body_from_wizard(
    extra: dict | None = None, description: str | None = None
) -> dict:
    """PUT /shipments — тіло з полів upwiz_* (без проміжного up_edit_*)."""
    label = st.session_state.get("upwiz_delivery_label", "склад – двері")
    delivery = _UP_DELIVERY_LABELS.get(label, "W2D")
    plist = _upwiz_parcels_from_form()
    p0 = plist[0] if plist else {}
    w, ln, wid, hgt = _up_normalize_parcel_dims(
        p0.get("weight"), p0.get("length"), p0.get("width"), p0.get("height")
    )
    parcel = {"weight": w, "length": ln, "width": wid, "height": hgt}
    puid = str(st.session_state.get("upwiz_edit_parcel_uuid", "")).strip()
    if puid:
        parcel["uuid"] = puid
    declared = float(p0.get("declaredPrice") or 0)
    parcel["declaredPrice"] = max(0.0, declared)
    desc = (
        str(description).strip()[:_UP_SHIPMENT_DESC_MAX]
        if description is not None
        else _up_capture_wizard_description()
    )
    fail_main = st.session_state.get("upwiz_fail_main", "повернути")
    on_fail = "PROCESS_AS_REFUSAL" if fail_main == "не повертати" else "RETURN"
    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    svc = st.session_state.get("upwiz_service", "Базовий")
    ship_type = _UP_SERVICE_API.get(svc, "STANDARD")
    body = {
        "type": ship_type,
        "deliveryType": delivery,
        "description": desc,
        "parcels": [parcel],
        "postPay": postpay,
        "paidByRecipient": bool(st.session_state.get("upwiz_paid_shipment_recipient")),
        "postPayPaidByRecipient": bool(
            st.session_state.get("upwiz_paid_postpay_recipient", True)
        ),
        "transferPostPayToBankAccount": bool(
            st.session_state.get("upwiz_transfer_postpay_iban")
        ),
        "sms": bool(st.session_state.get("upwiz_sms")),
        "checkOnDelivery": bool(st.session_state.get("upwiz_check_delivery", True)),
        "onFailReceiveType": on_fail,
    }
    phone = utils.clean_phone(_up_phone_for_input(st.session_state.get("upwiz_phone", "")))
    if phone and len(phone) >= 10:
        body["recipientPhone"] = phone if phone.startswith("+") else f"+{phone}"
    if extra:
        body.update(extra)
    return body


def _up_save_wizard_edit(suuid: str, description: str) -> tuple[dict | None, str]:
    """Зберегти редагування: спочатку отримувач (clients), потім відправлення (shipments)."""
    desc = str(description or "").strip()[:_UP_SHIPMENT_DESC_MAX]
    st.session_state._upwiz_last_saved_description = desc
    st.session_state.upwiz_description_stored = desc
    _up_sync_wizard_paid_flags()
    rid = _up_recipient_uuid_for_edit()
    extra, err = _up_apply_recipient_updates_from_wizard(rid)
    if err:
        return None, err
    body = _up_build_shipment_update_body_from_wizard(extra, description=desc)
    data, err = up_put_shipment_update(suuid, body)
    if err:
        return None, err
    if desc:
        _up_clear_parcel_descriptions_on_shipment(suuid, data if isinstance(data, dict) else None)
    st.session_state.pop("_upwiz_last_desc_put_warn", None)
    if desc and isinstance(data, dict):
        got = _up_description_from_shipment_response(data)
        if got != desc:
            puid = str(st.session_state.get("upwiz_edit_parcel_uuid", "")).strip()
            _, patch_err = up_put_shipment_update(suuid, {"description": desc})
            used_parcel_only = False
            if patch_err and puid:
                _, patch_err = up_put_shipment_update(
                    suuid, {"parcels": [{"uuid": puid, "description": desc}]}
                )
                used_parcel_only = not patch_err
            if patch_err:
                st.session_state._upwiz_last_desc_put_warn = str(patch_err)[:300]
            elif not used_parcel_only:
                _up_clear_parcel_descriptions_on_shipment(suuid, data)
    return data if isinstance(data, dict) else {}, ""


def _up_journal_row_patch_from_wizard(row: dict) -> dict:
    """Підставити з форми ПІБ, телефон, опис (поки API не оновив відповідь)."""
    import json as _json

    last = str(st.session_state.get("upwiz_lastname", "")).strip()
    first = str(st.session_state.get("upwiz_firstname", "")).strip()
    middle = str(st.session_state.get("upwiz_middlename", "")).strip()
    parts = [p for p in (last, first, middle) if p]
    if parts:
        row["Отримувач"] = " ".join(parts)[:120]
    ph = _up_phone_for_journal(st.session_state.get("upwiz_phone", ""))
    if ph:
        row["Телефон"] = ph
    desc = str(
        st.session_state.get("_upwiz_last_saved_description", _up_wizard_description())
    ).strip()[:500]
    row["Дод. інфо"] = desc
    snap = str(row.get("JSON", "") or "").strip()
    if snap:
        try:
            j = _json.loads(snap)
            if isinstance(j, dict):
                j["description"] = desc[:_UP_SHIPMENT_DESC_MAX]
                parcels = j.get("parcels")
                if isinstance(parcels, list):
                    for i, p in enumerate(parcels):
                        if isinstance(p, dict) and "description" in p:
                            p2 = dict(p)
                            p2.pop("description", None)
                            parcels[i] = p2
                row["JSON"] = _json.dumps(j, ensure_ascii=False)[:45000]
        except Exception:
            pass
    plist = _upwiz_parcels_from_form()
    if plist:
        declared = float(plist[0].get("declaredPrice") or 0)
        row["Вартість"] = _up_fmt_journal_amount(max(0.0, declared))
    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    row["Післяплата"] = _up_fmt_journal_amount(postpay) if postpay >= 1 else ""
    svc = st.session_state.get("upwiz_service", "Базовий")
    row["Тариф"] = "Пріоритетний" if svc == "Пріоритетний" else "Базовий"
    label = st.session_state.get("upwiz_delivery_label", "")
    if label:
        row["Доставка"] = str(_UP_DELIVERY_LABELS.get(label, label))
    return row


def _up_barcode_from_create_response(data):
    if not isinstance(data, dict):
        return None
    for key in ("barcode", "barCode", "shipmentNumber"):
        v = data.get(key)
        if v and str(v).strip():
            return _up_normalize_bc(str(v).strip())
    parcels = data.get("parcels")
    if isinstance(parcels, list):
        for p in parcels:
            if isinstance(p, dict) and p.get("barcode"):
                return _up_normalize_bc(str(p["barcode"]))
    return None


_UP_EDIT_KEEP_KEYS = frozenset(
    {
        "up_edit_seeded_uuid",
        "up_edit_shipment_uuid",
        "up_edit_parcel_uuid",
        "up_edit_barcode",
        "up_edit_delivery_type",
        "up_edit_lifecycle_status",
        "up_edit_recipient_uuid",
        "up_edit_panel_open",
    }
)


def _up_clear_edit_widgets():
    """Скинути віджети форми редагування (інакше Streamlit лишає старі значення)."""
    for key in list(st.session_state.keys()):
        if key.startswith("up_edit_") and key not in _UP_EDIT_KEEP_KEYS:
            del st.session_state[key]


def _up_recipient_address_from_shipment(data: dict) -> dict:
    """Адреса отримувача з відповіді GET /shipments."""
    out = {
        "postcode": "",
        "region": "",
        "district": "",
        "city": "",
        "street": "",
        "house": "",
        "apartment": "",
    }
    if not isinstance(data, dict):
        return out
    rec = data.get("recipient")
    addr = None
    if isinstance(rec, dict):
        addrs = rec.get("addresses")
        if isinstance(addrs, list) and addrs:
            first = addrs[0]
            if isinstance(first, dict):
                addr = first.get("address") if isinstance(first.get("address"), dict) else first
        elif isinstance(rec.get("address"), dict):
            addr = rec.get("address")
    if not isinstance(addr, dict):
        ra = data.get("recipientAddress")
        if isinstance(ra, dict):
            addr = ra
    if isinstance(addr, dict):
        out["postcode"] = str(addr.get("postcode") or "")
        out["region"] = str(addr.get("region") or "")
        out["district"] = str(addr.get("district") or "")
        out["city"] = str(addr.get("city") or "")
        out["street"] = str(addr.get("street") or "")
        out["house"] = str(addr.get("houseNumber") or "")
        out["apartment"] = str(addr.get("apartmentNumber") or "")
    return out


def _up_shipment_uuid_from_response(data: dict):
    if not isinstance(data, dict):
        return ""
    return str(data.get("uuid") or data.get("shipmentUuid") or "").strip()


def _up_lifecycle_status(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    lc = data.get("lifecycle")
    if isinstance(lc, dict):
        return str(lc.get("status") or "").strip()
    return ""


def _up_parcels_list_from_response(data: dict) -> list:
    if not isinstance(data, dict):
        return []
    parcels = data.get("parcels")
    if isinstance(parcels, list):
        return [p for p in parcels if isinstance(p, dict)]
    return []


def _up_clear_parcel_descriptions_on_shipment(suuid: str, data: dict | None = None) -> None:
    """УП на ярлику зʼєднує shipment.description і parcels[].description — прибираємо з місця."""
    if not suuid:
        return
    parcels_patch = []
    for p in _up_parcels_list_from_response(data or {}):
        pu = str(p.get("uuid") or "").strip()
        if pu and str(p.get("description") or "").strip():
            parcels_patch.append({"uuid": pu, "description": ""})
    if not parcels_patch:
        puid = str(st.session_state.get("upwiz_edit_parcel_uuid", "") or "").strip()
        if not puid:
            puid = str(st.session_state.get("up_edit_parcel_uuid", "") or "").strip()
        if puid:
            parcels_patch = [{"uuid": puid, "description": ""}]
    if parcels_patch:
        up_put_shipment_update(suuid, {"parcels": parcels_patch})


def _up_first_parcel_from_response(data: dict) -> dict:
    parcels = _up_parcels_list_from_response(data)
    return parcels[0] if parcels else {}


def _up_fmt_journal_amount(val) -> str:
    if val is None:
        return ""
    try:
        f = float(val)
        if f == int(f):
            return str(int(f))
        return str(f).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        s = str(val).strip()
        return "" if s.lower() == "nan" else s


def _up_postpay_from_response(resp: dict) -> float:
    if not isinstance(resp, dict):
        return 0.0
    v = _up_num_float(resp.get("postPay"), 0)
    return v if v >= 1 else 0.0


def _up_journal_postpay_from_row(row) -> str:
    """Післяплата з колонки журналу або з JSON відповіді API."""
    col = str(_up_journal_row_value(row, "Післяплата") or "").strip()
    if col and col not in ("—", "0", "0.0"):
        return _up_fmt_journal_amount(col)
    snap = str(_up_journal_row_value(row, "JSON") or "").strip()
    if snap:
        import json as _json

        try:
            j = _json.loads(snap)
            if isinstance(j, dict):
                pp = _up_postpay_from_response(j)
                if pp >= 1:
                    return _up_fmt_journal_amount(pp)
        except Exception:
            pass
    return ""


def _up_declared_price_from_response(resp: dict):
    if not isinstance(resp, dict):
        return None
    parcel = _up_first_parcel_from_response(resp)
    if isinstance(parcel, dict) and parcel.get("declaredPrice") is not None:
        return parcel.get("declaredPrice")
    if resp.get("declaredPrice") is not None:
        return resp.get("declaredPrice")
    return None


def _up_description_from_journal_bc(bc: str) -> str:
    """Опис з колонки «Дод. інфо» журналу (найнадійніше при повторному відкритті)."""
    bc_norm = _up_normalize_bc(bc)
    if not bc_norm:
        return ""
    try:
        jdf = sheets.read_up_shipments()
        if jdf is None or jdf.empty or "ШКІ" not in jdf.columns:
            return ""
        for _, row in jdf.iterrows():
            if _up_normalize_bc(row.get("ШКІ", "")) != bc_norm:
                continue
            d = str(row.get("Дод. інфо", "") or "").strip()
            if d and d.lower() != "nan":
                return d[:_UP_SHIPMENT_DESC_MAX]
    except Exception:
        pass
    return ""


def _up_description_for_edit(bc: str, api_data: dict | None) -> str:
    """Опис для форми редагування: спочатку журнал, потім API."""
    from_journal = _up_description_from_journal_bc(bc)
    if from_journal:
        return from_journal
    if isinstance(api_data, dict):
        from_api = _up_description_from_shipment_response(api_data)
        if from_api:
            return from_api
    return ""


def _up_description_from_shipment_response(data: dict) -> str:
    """Опис відправлення з відповіді API (лише рівень shipment; parcel — запасний варіант)."""
    if not isinstance(data, dict):
        return ""
    d = str(data.get("description") or "").strip()
    if not d:
        for parcel in _up_parcels_list_from_response(data):
            pd = str(parcel.get("description") or "").strip()
            if pd:
                d = pd
                break
    if not d:
        return ""
    # УП інколи повертає дубль «текст; текст» після подвійного запису в API
    if "; " in d:
        parts = [p.strip() for p in d.split(";") if p.strip()]
        if len(parts) >= 2 and len(set(parts)) == 1:
            d = parts[0]
    return d[:_UP_SHIPMENT_DESC_MAX]


def _up_journal_row_value(row, col: str) -> str:
    """Безпечно прочитати комірку рядка журналу (pandas Series)."""
    try:
        if hasattr(row, "index") and col in row.index:
            v = row[col]
        elif hasattr(row, "get"):
            v = row.get(col, "")
        else:
            v = ""
    except Exception:
        v = ""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _up_set_wizard_description(value: str) -> None:
    """Зберегти опис у не-віджетний ключ (безпечно викликати до/після rerun)."""
    desc = str(value or "").strip()[:_UP_SHIPMENT_DESC_MAX]
    st.session_state.upwiz_description_stored = desc
    st.session_state.upwiz_desc_widget = desc


def _up_capture_wizard_description() -> str:
    """Актуальний опис з віджета (ключ upwiz_desc_widget) або збереженого значення."""
    if "upwiz_desc_widget" in st.session_state:
        return str(st.session_state.upwiz_desc_widget or "").strip()[:_UP_SHIPMENT_DESC_MAX]
    return str(st.session_state.get("upwiz_description_stored", "") or "").strip()[
        :_UP_SHIPMENT_DESC_MAX
    ]


def _up_wizard_description() -> str:
    return _up_capture_wizard_description()


def _up_on_desc_widget_change() -> None:
    st.session_state.upwiz_description_stored = str(
        st.session_state.get("upwiz_desc_widget", "")
    ).strip()[:_UP_SHIPMENT_DESC_MAX]


def _up_sync_wizard_description_from_widget() -> None:
    if "upwiz_desc_widget" in st.session_state:
        st.session_state.upwiz_description_stored = _up_capture_wizard_description()


def _up_render_wizard_description_field() -> None:
    """Додаткова інформація — під оголошеною вартістю та післяплатою."""
    st.text_area(
        "Додаткова інформація",
        key="upwiz_desc_widget",
        placeholder=f"Додаткова інформація (до {_UP_SHIPMENT_DESC_MAX} символів)",
        height=80,
        max_chars=_UP_SHIPMENT_DESC_MAX,
        on_change=_up_on_desc_widget_change,
    )
    _up_sync_wizard_description_from_widget()


def _up_journal_declared_from_row(row) -> str:
    import json as _json

    v = str(row.get("Вартість", "") or row.get("Вартість доставки", "") or "").strip()
    if v and v.lower() != "nan":
        return v
    snap = str(row.get("JSON", "") or "").strip()
    if snap:
        try:
            declared = _up_declared_price_from_response(_json.loads(snap))
            if declared is not None:
                return _up_fmt_journal_amount(declared)
        except Exception:
            pass
    return ""


def up_fetch_shipment(barcode_or_uuid: str):
    """GET відправлення за ШКІ або uuid."""
    ident = str(barcode_or_uuid or "").strip()
    if not ident:
        return None, "Вкажи ШКІ або uuid відправлення."
    if _up_is_valid_uuid(ident):
        path = f"/shipments/{ident}"
    else:
        bc = ident
        if len(bc) == 12 and bc.isdigit():
            bc = "0" + bc
        path = f"/shipments/barcode/{bc}"
    return up_ecom_request("GET", path)


def up_put_shipment_update(shipment_uuid: str, body: dict):
    """PUT /shipments/{uuid} — зміна відправлення (опис, доставка, parcels)."""
    suuid = str(shipment_uuid or "").strip()
    if not suuid:
        return None, "Немає uuid відправлення для оновлення."
    path = f"/shipments/{suuid}"
    return up_ecom_request("PUT", path, body)


def _up_client_type_label(client_type: str) -> str:
    labels = {
        "INDIVIDUAL": "фізична особа",
        "PRIVATE_ENTREPRENEUR": "ФОП",
        "COMPANY": "юридична особа",
    }
    return labels.get(str(client_type or "").strip(), str(client_type or "—"))


def _up_expect_fop_sender() -> bool:
    """Чи очікується відправник типу ФОП (PRIVATE_ENTREPRENEUR)."""
    t = str(getattr(config, "UP_SENDER_TYPE", "") or "").strip().upper()
    if t in ("INDIVIDUAL", "FO", "ФО", "PHYSICAL"):
        return False
    if t in ("FOP", "PRIVATE_ENTREPRENEUR", "ПЕ", "ФОП", "PE"):
        return True
    tin = re.sub(r"\D", "", str(getattr(config, "UP_SENDER_TIN", "") or ""))
    if len(tin) == 10:
        return True
    name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip()
    return bool(re.match(r"(?i)^фоп[\s.]", name))


def up_delete_shipment(shipment_uuid: str):
    """DELETE /shipments/{uuid} — лише поки відправлення не прийняте (статус CREATED)."""
    suuid = str(shipment_uuid or "").strip()
    if not suuid:
        return False, "Немає uuid відправлення."
    _, err = up_ecom_request("DELETE", f"/shipments/{suuid}")
    if err:
        return False, err
    return True, ""


def up_delete_shipment_by_barcode(barcode: str):
    """Видалити відправлення в eCom за ШКІ."""
    data, err = up_fetch_shipment(barcode)
    if err:
        return False, err
    if not isinstance(data, dict):
        return False, "Не вдалося завантажити відправлення."
    suuid = _up_shipment_uuid_from_response(data)
    if not suuid:
        return False, "У відповіді API немає uuid відправлення."
    status = _up_lifecycle_status(data)
    if status and status not in ("CREATED",):
        return (
            False,
            f"Укрпошта дозволяє видалити лише в статусі **CREATED** (зараз: {status}). "
            "Скасуй у кабінеті ok.ukrposhta, якщо вже передано на пошту.",
        )
    return up_delete_shipment(suuid)


def _up_seed_edit_form_from_shipment(data: dict, force: bool = False):
    """Заповнити поля форми редагування з відповіді API."""
    suuid = _up_shipment_uuid_from_response(data)
    if not suuid:
        return
    if not force and st.session_state.get("up_edit_seeded_uuid") == suuid:
        return
    _up_clear_edit_widgets()
    parcel = _up_first_parcel_from_response(data)
    bc = _up_barcode_from_create_response(data) or ""
    api_delivery = str(data.get("deliveryType") or "W2D").strip()
    inv = {v: k for k, v in _UP_DELIVERY_LABELS.items()}
    rec = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    addr = _up_recipient_address_from_shipment(data)

    st.session_state.up_edit_shipment_uuid = suuid
    st.session_state.up_edit_parcel_uuid = str(parcel.get("uuid") or "").strip()
    st.session_state.up_edit_barcode = bc
    st.session_state.up_edit_load_barcode = bc
    st.session_state.up_edit_delivery_type = api_delivery
    st.session_state.up_edit_delivery_label_pick = inv.get(api_delivery, "склад – двері")
    st.session_state.up_edit_description = str(data.get("description") or "")
    st.session_state.up_edit_weight_g = int(parcel.get("weight") or data.get("weight") or 500)
    st.session_state.up_edit_length_cm = int(parcel.get("length") or data.get("length") or 30)
    st.session_state.up_edit_width_cm = int(parcel.get("width") or data.get("width") or 0)
    st.session_state.up_edit_height_cm = int(parcel.get("height") or data.get("height") or 0)
    st.session_state.up_edit_declared_uah = float(
        parcel.get("declaredPrice") or data.get("declaredPrice") or 0
    )
    st.session_state.up_edit_postpay_uah = float(data.get("postPay") or 0)
    st.session_state.up_edit_lifecycle_status = _up_lifecycle_status(data)
    st.session_state.up_edit_recipient_uuid = str(rec.get("uuid") or "").strip()
    _up_fill_edit_recipient_name_fields(rec)
    phone = utils.clean_phone(
        str(data.get("recipientPhone") or rec.get("phoneNumber") or "")
    )
    st.session_state.up_edit_phone = _up_phone_for_input(phone)
    for k, v in addr.items():
        st.session_state[f"up_edit_{k}"] = v
    st.session_state.up_edit_paid_shipment_recipient = bool(data.get("paidByRecipient"))
    st.session_state.up_edit_paid_postpay_recipient = bool(
        data.get("postPayPaidByRecipient", True)
    )
    st.session_state.up_edit_transfer_postpay_iban = bool(
        data.get("transferPostPayToBankAccount")
    )
    st.session_state.up_edit_sms = bool(data.get("sms"))
    st.session_state.up_edit_check_delivery = bool(data.get("checkOnDelivery", True))
    fail = str(data.get("onFailReceiveType") or "RETURN").upper()
    st.session_state.up_edit_fail_main = (
        "не повертати" if fail == "PROCESS_AS_REFUSAL" else "повернути"
    )
    st.session_state.up_edit_seeded_uuid = suuid
    st.session_state.up_edit_panel_open = True
    _up_sync_edit_saved_address_snapshot()


def _up_fill_edit_recipient_name_fields(rec: dict):
    """ПІБ отримувача в поля редагування (з API або з поля name)."""
    last = str(rec.get("lastName") or "").strip()
    first = str(rec.get("firstName") or "").strip()
    middle = str(rec.get("middleName") or "").strip()
    if not last and not first:
        name = str(rec.get("name") or "").strip()
        if name:
            parts = name.split()
            if len(parts) >= 1:
                last = parts[0]
            if len(parts) >= 2:
                first = parts[1]
            if len(parts) >= 3:
                middle = " ".join(parts[2:])
    st.session_state.up_edit_lastname = last
    st.session_state.up_edit_firstname = first
    st.session_state.up_edit_middlename = middle


def _up_validate_edit_form() -> str:
    """Перевірка форми редагування перед збереженням."""
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
    if postpay >= 1:
        if not str(st.session_state.get("up_edit_lastname", "")).strip():
            return "Для післяплати потрібне прізвище отримувача."
        if not str(st.session_state.get("up_edit_firstname", "")).strip():
            return "Для післяплати потрібне імʼя отримувача."
        if not str(st.session_state.get("up_edit_middlename", "")).strip():
            return "Для післяплати потрібне по батькові отримувача (вимога Укрпошти)."
    return ""


def _up_post_address_from_edit_form():
    """POST /addresses для нової адреси отримувача при редагуванні."""
    postcode = str(st.session_state.get("up_edit_postcode", "")).strip()
    region = str(st.session_state.get("up_edit_region", "")).strip()
    district = str(st.session_state.get("up_edit_district", "")).strip()
    city = str(st.session_state.get("up_edit_city", "")).strip()
    street = str(st.session_state.get("up_edit_street", "")).strip()
    house = str(st.session_state.get("up_edit_house", "")).strip()
    apartment = str(st.session_state.get("up_edit_apartment", "")).strip()
    if not postcode or not region or not city:
        return None, "Заповни індекс, область і населений пункт."
    body = {
        "country": "UA",
        "postcode": postcode[:5],
        "region": region[:45],
        "city": city[:45],
    }
    if district:
        body["district"] = district[:45]
    if street:
        body["street"] = street[:255]
    if house:
        body["houseNumber"] = house[:15]
    if apartment:
        body["apartmentNumber"] = apartment[:15]
    data, err = up_ecom_request("POST", "/addresses", body, token_required=False)
    if err:
        return None, f"Адреса: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу не створено: {data}"
    return addr_id, ""


def _up_edit_address_changed() -> bool:
    fields = ("postcode", "region", "district", "city", "street", "house", "apartment")
    for f in fields:
        if str(st.session_state.get(f"up_edit_{f}", "")).strip() != str(
            st.session_state.get(f"up_edit_saved_{f}", "")
        ).strip():
            return True
    return False


def _up_sync_edit_saved_address_snapshot():
    for f in ("postcode", "region", "district", "city", "street", "house", "apartment"):
        st.session_state[f"up_edit_saved_{f}"] = str(st.session_state.get(f"up_edit_{f}", ""))


def _up_apply_recipient_updates() -> tuple[dict | None, str]:
    """Оновити клієнта-отримувача (адреса, ПІБ, телефон) перед PUT відправлення."""
    v_err = _up_validate_edit_form()
    if v_err:
        return None, v_err
    rid = str(st.session_state.get("up_edit_recipient_uuid", "")).strip()
    if not rid:
        postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
        if postpay >= 1:
            return None, "Немає uuid отримувача — спочатку натисни «Завантажити» за ШКІ."
        return {}, ""
    body_client = {}
    last = str(st.session_state.get("up_edit_lastname", "")).strip()
    first = str(st.session_state.get("up_edit_firstname", "")).strip()
    middle = str(st.session_state.get("up_edit_middlename", "")).strip()
    st.session_state.up_edit_phone = _up_phone_for_input(st.session_state.get("up_edit_phone", ""))
    phone = utils.clean_phone(str(st.session_state.get("up_edit_phone", "")).strip())
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
    if postpay >= 1:
        body_client["lastName"] = last[:250]
        body_client["firstName"] = first[:250]
        body_client["middleName"] = middle[:250]
    else:
        if last:
            body_client["lastName"] = last[:250]
        if first:
            body_client["firstName"] = first[:250]
        if middle:
            body_client["middleName"] = middle[:250]
    if phone and len(phone) >= 10:
        body_client["phoneNumber"] = phone if phone.startswith("+") else f"+{phone}"

    new_addr_id = None
    if _up_edit_address_changed():
        new_addr_id, err = _up_post_address_from_edit_form()
        if err:
            return None, err
        body_client["addressId"] = str(new_addr_id)

    if body_client:
        _, err = up_ecom_request("PUT", f"/clients/{rid}", body_client)
        if err:
            return None, f"Отримувач: {err}"

    extra = {}
    if new_addr_id:
        try:
            extra["recipientAddressId"] = int(new_addr_id)
        except ValueError:
            extra["recipientAddressId"] = new_addr_id
    return extra, ""


def _up_build_shipment_update_body(extra: dict | None = None) -> dict:
    """Тіло PUT /shipments за полями форми редагування."""
    label = st.session_state.get("up_edit_delivery_label_pick", "склад – двері")
    delivery = _UP_DELIVERY_LABELS.get(label, st.session_state.get("up_edit_delivery_type", "W2D"))
    w, ln, wid, hgt = _up_normalize_parcel_dims(
        st.session_state.get("up_edit_weight_g"),
        st.session_state.get("up_edit_length_cm"),
        st.session_state.get("up_edit_width_cm"),
        st.session_state.get("up_edit_height_cm"),
    )
    parcel = {"weight": w, "length": ln, "width": wid, "height": hgt}
    puid = str(st.session_state.get("up_edit_parcel_uuid", "")).strip()
    if puid:
        parcel["uuid"] = puid
    declared = _up_num_float(st.session_state.get("up_edit_declared_uah", 0))
    if declared > 0:
        parcel["declaredPrice"] = declared

    fail_main = st.session_state.get("up_edit_fail_main", "повернути")
    on_fail = "PROCESS_AS_REFUSAL" if fail_main == "не повертати" else "RETURN"
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))

    ship_type = str(
        st.session_state.get("up_edit_shipment_type")
        or _UP_SERVICE_API.get(
            st.session_state.get("upwiz_service", "Базовий"), "STANDARD"
        )
    )
    body = {
        "type": ship_type,
        "deliveryType": delivery,
        "description": str(st.session_state.get("up_edit_description", "")).strip()[
            :_UP_SHIPMENT_DESC_MAX
        ],
        "parcels": [parcel],
        "postPay": postpay,
        "paidByRecipient": bool(st.session_state.get("up_edit_paid_shipment_recipient")),
        "postPayPaidByRecipient": bool(
            st.session_state.get("up_edit_paid_postpay_recipient", True)
        ),
        "transferPostPayToBankAccount": bool(
            st.session_state.get("up_edit_transfer_postpay_iban")
        ),
        "sms": bool(st.session_state.get("up_edit_sms")),
        "checkOnDelivery": bool(st.session_state.get("up_edit_check_delivery", True)),
        "onFailReceiveType": on_fail,
    }
    st.session_state.up_edit_phone = _up_phone_for_input(st.session_state.get("up_edit_phone", ""))
    phone = utils.clean_phone(str(st.session_state.get("up_edit_phone", "")).strip())
    if phone and len(phone) >= 10:
        body["recipientPhone"] = phone if phone.startswith("+") else f"+{phone}"
    if extra:
        body.update(extra)
    return body


def _up_save_shipment_edit(suuid: str):
    extra, err = _up_apply_recipient_updates()
    if err:
        return None, err
    body = _up_build_shipment_update_body(extra)
    data, err = up_put_shipment_update(suuid, body)
    if err:
        return None, err
    desc = str(body.get("description") or "").strip()
    if desc:
        _up_clear_parcel_descriptions_on_shipment(suuid, data if isinstance(data, dict) else None)
    return data if isinstance(data, dict) else {}, ""


def _up_journal_row_from_response(resp: dict, user: str = "") -> dict:
    import json as _json

    bc = _up_barcode_from_create_response(resp) or ""
    suuid = _up_shipment_uuid_from_response(resp)
    st_up = _up_lifecycle_status(resp)
    recipient = ""
    phone = ""
    rec = resp.get("recipient")
    if isinstance(rec, dict):
        recipient = str(rec.get("name") or "").strip()
        if not recipient:
            parts = [rec.get("lastName"), rec.get("firstName"), rec.get("middleName")]
            recipient = " ".join(str(p).strip() for p in parts if p)
        phone = utils.clean_phone(
            str(resp.get("recipientPhone") or rec.get("phoneNumber") or "")
        )
    if not phone:
        phone = utils.clean_phone(str(resp.get("recipientPhone") or ""))
    phone = _up_phone_for_journal(phone)
    ship_type = str(resp.get("type") or "STANDARD").upper()
    tariff = "Пріоритетний" if ship_type == "EXPRESS" else "Базовий"
    ts = (
        str(resp.get("registrationDate") or resp.get("created") or "")
        or utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S")
    )
    if "T" in ts:
        ts = ts.replace("T", " ")[:19]
    declared = _up_declared_price_from_response(resp)
    price_s = _up_fmt_journal_amount(declared)
    postpay_s = _up_fmt_journal_amount(_up_postpay_from_response(resp))
    desc = _up_description_from_shipment_response(resp)[:500]
    try:
        snap = _json.dumps(resp, ensure_ascii=False)[:45000]
    except Exception:
        snap = ""
    u = user or str(st.session_state.get("auth_user", "") or "?")
    return {
        "Час": ts[:19],
        "Користувач": u[:80],
        "ШКІ": _up_format_bc_display(bc),
        "UUID": suuid,
        "Статус УП": st_up,
        "Отримувач": recipient[:120],
        "Телефон": phone,
        "Тариф": tariff,
        "Доставка": str(resp.get("deliveryType") or ""),
        "Вартість": price_s,
        "Післяплата": postpay_s if postpay_s else "",
        "Дод. інфо": desc,
        "JSON": snap,
    }


def up_journal_save_response(
    resp: dict,
    user: str = "",
    patch_from_wizard: bool = False,
    description_override: str | None = None,
):
    if not isinstance(resp, dict):
        return False
    row = _up_journal_row_from_response(resp, user)
    if patch_from_wizard:
        row = _up_journal_row_patch_from_wizard(row)
    if description_override is not None:
        import json as _json

        desc = str(description_override).strip()[:500]
        row["Дод. інфо"] = desc
        snap = str(row.get("JSON", "") or "").strip()
        if snap:
            try:
                j = _json.loads(snap)
                if isinstance(j, dict):
                    j["description"] = desc[:_UP_SHIPMENT_DESC_MAX]
                    row["JSON"] = _json.dumps(j, ensure_ascii=False)[:45000]
            except Exception:
                pass
    if not row.get("ШКІ"):
        return False
    ok = sheets.append_up_shipment_record(row)
    if ok:
        _cached_up_shipments_df.clear()
    return ok


def up_fetch_shipments_list(days: int = 14):
    """Список відправлень з eCom API за останні N днів."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return [], "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets."
    if not config.UP_BEARER_TOKEN:
        return [], "Немає UP_BEARER_TOKEN у Secrets."
    d_from = (utils.now_kyiv_naive() - timedelta(days=max(1, int(days)))).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    url = f"{UP_ECOM_BASE}/shipments"
    params = {"token": ecom_token, "lastModifiedFrom": d_from}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token,
    )
    try:
        r = utils.make_request("GET", url, headers=headers, params=params, timeout=60)
        if not r:
            hint = utils.get_last_request_error()
            return [], hint or "Немає відповіді від eCom API."
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}: {(r.text or '')[:300]}"
        data = r.json()
    except Exception as e:
        return [], str(e)[:400]
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        return data.get("shipments") or data.get("items") or [], ""
    return [], ""


def up_sync_journal_from_api(days: int = 14) -> tuple[int, str]:
    """Спроба підтягнути список усіх відправлень за період (eCom більше не підтримує — 410)."""
    items, err = up_fetch_shipments_list(days)
    if err:
        return 0, err
    user = str(st.session_state.get("auth_user", "") or "?")
    n = 0
    for item in items:
        if isinstance(item, dict) and up_journal_save_response(item, user):
            n += 1
    return n, ""


def _up_tracking_minimal_row(barcode: str) -> dict | None:
    """Мінімальний рядок журналу з трекінг-API (без даних контрагента)."""
    if not config.UP_TRACKING_TOKEN:
        return None
    try:
        r = utils.make_request(
            "GET",
            f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}",
            headers={
                "Authorization": f"Bearer {config.UP_TRACKING_TOKEN}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        if not r or r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    last = data[-1] if isinstance(data[-1], dict) else {}
    status = str(last.get("eventName") or last.get("name") or "").strip()
    date_raw = last.get("date") or last.get("eventDate") or ""
    return {
        "Час": utils.normalize_date(date_raw)
        or utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
        "Користувач": str(st.session_state.get("auth_user", "") or "?"),
        "ШКІ": barcode,
        "UUID": "",
        "Статус УП": status,
        "Отримувач": "",
        "Телефон": "",
        "Тариф": "",
        "Доставка": "",
        "Вартість": "",
        "Післяплата": "",
        "Дод. інфо": "Імпорт із трекінгу (повний доступ обмежено контрагентом-власником ТТН).",
        "JSON": "",
    }


def _friendly_up_sync_error(bc: str, err: str) -> str:
    """Коротке повідомлення для типових помилок API УП."""
    e = str(err or "")
    low = e.lower()
    if "upe05001" in low or "counterparty mismatch" in low or "http 401" in low:
        return (
            f"{bc}: ТТН належить іншому контрагенту (UPE05001) — "
            "повна інформація недоступна; підтягую дані з трекінгу"
        )
    if "http 404" in low or "not found" in low:
        return f"{bc}: ТТН не знайдено в Укрпошті"
    if "http 410" in low:
        return f"{bc}: ендпоінт API більше не підтримується (410)"
    return f"{bc}: {e[:180]}"


def up_sync_journal_by_barcodes(barcodes) -> tuple[int, int, list[str]]:
    """Підтягнути ТТН з eCom API за списком ШКІ → дописати/оновити в журналі.

    Повертає (повних_OK, мін_з_трекінгу, [короткі_повідомлення_про_помилки])."""
    user = str(st.session_state.get("auth_user", "") or "?")
    ok_full = 0
    ok_tracking = 0
    errs: list[str] = []
    seen: set[str] = set()
    for raw in barcodes or []:
        src = str(raw or "").strip()
        if not src:
            continue
        bc = _up_normalize_sticker_ident(src)
        if not bc or not bc.isdigit() or len(bc) != 13:
            errs.append(f"{src}: некоректний ШКІ (треба 13 цифр)")
            continue
        if bc in seen:
            continue
        seen.add(bc)
        resp, ferr = up_fetch_shipment(bc)
        if not ferr and isinstance(resp, dict):
            if up_journal_save_response(resp, user):
                ok_full += 1
            else:
                errs.append(f"{bc}: не вдалося зберегти у журналі")
            continue
        low = str(ferr or "").lower()
        is_foreign = (
            "upe05001" in low
            or "counterparty mismatch" in low
            or "http 401" in low
        )
        if is_foreign:
            tr_row = _up_tracking_minimal_row(bc)
            if tr_row and sheets.append_up_shipment_record(tr_row):
                ok_tracking += 1
                errs.append(_friendly_up_sync_error(bc, ferr or ""))
                continue
        errs.append(_friendly_up_sync_error(bc, ferr or "порожня відповідь"))
    return ok_full, ok_tracking, errs


def _up_normalize_sticker_ident(barcode_or_uuid: str) -> str:
    ident = str(barcode_or_uuid or "").strip()
    if len(ident) == 12 and ident.isdigit():
        ident = "0" + ident
    return ident


def _up_sticker_query_string(hide_delivery_price: bool = False, size: str = "SIZE_10X10") -> str:
    import urllib.parse

    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    params = {"token": ecom_token}
    if size:
        params["size"] = size
    if hide_delivery_price:
        params["hideDeliveryPrice"] = "1"
    return urllib.parse.urlencode(params)


def _up_sticker_get_urls(ident: str, hide_delivery_price: bool = False, size: str = "SIZE_10X10"):
    """URL ярлика: forms API (документація УП) і запасний eCom."""
    qs = _up_sticker_query_string(hide_delivery_price, size)
    form_base = "https://www.ukrposhta.ua/forms/ecom/0.0.1"
    ecom_base = "https://www.ukrposhta.ua/ecom/0.0.1"
    paths = [
        f"{form_base}/shipments/{ident}/sticker?{qs}",
        f"{ecom_base}/shipments/{ident}/sticker?{qs}",
    ]
    if size:
        qs_plain = _up_sticker_query_string(hide_delivery_price, size="")
        paths.append(f"{form_base}/shipments/{ident}/sticker?{qs_plain}")
        paths.append(f"{ecom_base}/shipments/{ident}/sticker?{qs_plain}")
    return paths


def up_sticker_pdf_url(barcode: str, hide_delivery_price: bool = False) -> str:
    ident = _up_normalize_sticker_ident(barcode)
    return _up_sticker_get_urls(ident, hide_delivery_price)[0]


def _up_sticker_ident(barcode: str, shipment_uuid: str = "") -> str:
    """Ідентифікатор для ярлика: uuid відправлення надійніший після редагування."""
    suuid = str(shipment_uuid or "").strip()
    if _up_is_valid_uuid(suuid):
        return suuid
    return _up_normalize_sticker_ident(barcode)


def _up_clear_sticker_pdf_cache(bc: str = "") -> None:
    """Скинути закешовані PDF (після змін у ТТН — щоб не друкувався старий ярлик)."""
    st.session_state.pop("up_edit_sticker_pdf", None)
    bc_norm = _up_format_bc_display(bc)
    for key in list(st.session_state.keys()):
        if not isinstance(key, str):
            continue
        if "jpdf" not in key and "jprint" not in key and "sticker" not in key:
            continue
        if bc_norm and bc_norm not in key:
            continue
        st.session_state.pop(key, None)


def _up_journal_open_pdf_in_browser(pdf: bytes) -> None:
    """Відкрити PDF у новій вкладці для перегляду / друку (без download_button у рядку)."""
    import base64
    import json as _json

    import streamlit.components.v1 as components

    b64 = base64.b64encode(pdf).decode("ascii")
    components.html(
        f"""<!DOCTYPE html><html><body><script>
        (function() {{
            const b64 = {_json.dumps(b64)};
            const raw = atob(b64);
            const arr = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
            const blob = new Blob([arr], {{type: 'application/pdf'}});
            const url = URL.createObjectURL(blob);
            const w = window.open(url, '_blank');
            if (!w) {{
                const a = document.createElement('a');
                a.href = url;
                a.target = '_blank';
                a.rel = 'noopener';
                a.click();
            }}
        }})();
        </script></body></html>""",
        height=0,
    )


def _up_journal_print_controls(
    bc: str, hide_pr: bool, key_suffix: str, shipment_uuid: str = ""
) -> None:
    """Перегляд / друк: свіжий PDF з API, відкриття у браузері."""
    if st.button(
        "🖨️",
        key=f"up_jprint_{key_suffix}",
        help="Перегляд / друк PDF",
        type="secondary",
    ):
        _up_clear_sticker_pdf_cache(bc)
        with st.spinner("PDF…"):
            pdf, perr = up_fetch_sticker_pdf_bytes(
                bc, hide_delivery_price=hide_pr, shipment_uuid=shipment_uuid
            )
        if pdf:
            _up_journal_open_pdf_in_browser(pdf)
        elif perr:
            st.toast(str(perr)[:160], icon="⚠️")


def up_fetch_stickers_pdf_bytes_multi(
    idents: list,
    hide_delivery_price: bool = False,
    size: str = "SIZE_10X10",
):
    """Один PDF з ярликами для кількох відправлень (ендпоінт stickers-by-barcodes)."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN."
    cleaned = []
    seen = set()
    for raw in idents or []:
        s = str(raw or "").strip()
        if not s:
            continue
        if _up_is_valid_uuid(s):
            v = s
        else:
            v = _up_normalize_sticker_ident(s)
        if v and v not in seen:
            seen.add(v)
            cleaned.append(v)
    if not cleaned:
        return None, "Немає ідентифікаторів для друку."
    qs = _up_sticker_query_string(hide_delivery_price, size=size)
    post_url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/stickers-by-barcodes?{qs}"
    extra = {"hideDeliveryPrice": "1"} if hide_delivery_price else {}
    post_body = {ident: dict(extra) for ident in cleaned}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        counterparty_token=ecom_token,
        include_content_type=True,
    )
    try:
        r = utils.make_request(
            "POST", post_url, headers=headers, json=post_body, timeout=120
        )
        if r and r.status_code == 200 and r.content.startswith(b"%PDF"):
            return r.content, ""
        if r:
            return None, f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        return None, "Немає відповіді від Укрпошти."
    except Exception as e:
        return None, str(e)[:300]


def up_fetch_sticker_pdf_bytes(
    barcode: str, hide_delivery_price: bool = False, shipment_uuid: str = ""
):
    import urllib.error
    import urllib.parse
    import urllib.request

    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN."
    ident = _up_sticker_ident(barcode, shipment_uuid)
    if not ident:
        return None, "Немає ШКІ або UUID відправлення."
    last_err = ""

    # 1) POST stickers-by-barcodes — актуальні дані з eCom (док. УП)
    qs = _up_sticker_query_string(hide_delivery_price, size="SIZE_10X10")
    post_url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/stickers-by-barcodes?{qs}"
    extra = {}
    if hide_delivery_price:
        extra["hideDeliveryPrice"] = "1"
    post_body = {ident: extra}
    post_headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        counterparty_token=ecom_token,
        include_content_type=True,
    )
    try:
        r = utils.make_request("POST", post_url, headers=post_headers, json=post_body, timeout=60)
        if r and r.status_code == 200 and r.content.startswith(b"%PDF"):
            return r.content, ""
        if r:
            last_err = f"POST HTTP {r.status_code}: {(r.text or '')[:200]}"
    except Exception as e:
        last_err = str(e)[:300]

    # 2) Запасний GET (лише eCom, один URL — без дублювання forms+eCom)
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        counterparty_token=ecom_token,
        include_content_type=False,
    )
    get_url = f"{UP_ECOM_BASE}/shipments/{ident}/sticker?{_up_sticker_query_string(hide_delivery_price)}"
    req = urllib.request.Request(get_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60, context=utils._ssl_context()) as resp:
            raw = resp.read()
            if resp.status == 200 and raw.startswith(b"%PDF"):
                return raw, ""
            last_err = last_err or f"GET HTTP {resp.status}: не PDF"
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        last_err = last_err or f"GET HTTP {e.code}: {body}"
    except Exception as e:
        last_err = last_err or str(e)[:300]

    return None, last_err or "Не вдалося отримати PDF ярлик."


def _up_journal_description_from_row(row) -> str:
    import json as _json

    d = _up_journal_row_value(row, "Дод. інфо")
    if d:
        return d[:_UP_SHIPMENT_DESC_MAX]
    snap = _up_journal_row_value(row, "JSON")
    if snap:
        try:
            j = _json.loads(snap)
            return _up_description_from_shipment_response(j)
        except Exception:
            pass
    return ""


def _up_journal_set_desc_cache(bc: str, desc: str) -> None:
    """Запамʼятати актуальний опис для списку (після створення / редагування)."""
    bc_norm = _up_format_bc_display(bc)
    if not bc_norm:
        return
    cache = st.session_state.setdefault("_up_journal_desc_cache", {})
    cache[bc_norm] = str(desc or "").strip()[:_UP_SHIPMENT_DESC_MAX]
    pending = st.session_state.setdefault("_up_journal_pending_desc", {})
    pending[bc_norm] = cache[bc_norm]


def _up_journal_prefetch_descriptions(day_entries: list, *, force_api: bool = False) -> bool:
    """Підтягнути опис з УП для рядків без «Дод. інфо» в таблиці; записати в журнал."""
    cache = st.session_state.setdefault("_up_journal_desc_cache", {})
    pending = st.session_state.setdefault("_up_journal_pending_desc", {})
    patched = False
    for ent in day_entries:
        bc = ent.get("bc", "")
        row = ent.get("row")
        if not bc or row is None:
            ent["display_desc"] = ""
            continue
        local = _up_journal_description_from_row(row)
        if bc in pending:
            want = pending[bc]
            ent["display_desc"] = want
            cache[bc] = want
            if local == want:
                pending.pop(bc, None)
            continue
        if local:
            ent["display_desc"] = local
            cache[bc] = local
            continue
        if not force_api and bc in cache:
            ent["display_desc"] = cache[bc]
            continue
        data, err = up_fetch_shipment(bc)
        desc = ""
        if not err and isinstance(data, dict):
            desc = _up_description_from_shipment_response(data)
        cache[bc] = desc
        ent["display_desc"] = desc
        if desc and sheets.patch_up_shipment_description(bc, desc):
            patched = True
    if patched:
        _cached_up_shipments_df.clear()
    return patched


def _up_journal_parcel_dims_from_row(row) -> dict:
    """Вага та габарити з JSON журналу або UUID відправлення."""
    import json as _json

    out = {
        "suuid": str(_up_journal_row_value(row, "UUID") or "").strip(),
        "puid": "",
        "weight": 500,
        "length": 30,
        "width": 0,
        "height": 0,
    }
    snap = str(_up_journal_row_value(row, "JSON") or "").strip()
    if not snap:
        return out
    try:
        j = _json.loads(snap)
        if not isinstance(j, dict):
            return out
        if not out["suuid"]:
            out["suuid"] = str(_up_shipment_uuid_from_response(j) or "").strip()
        p = _up_first_parcel_from_response(j)
        if isinstance(p, dict):
            out["puid"] = str(p.get("uuid") or "").strip()
            out["weight"] = max(1, int(p.get("weight") or 500))
            out["length"] = max(1, int(p.get("length") or 30))
            out["width"] = max(0, int(p.get("width") or 0))
            out["height"] = max(0, int(p.get("height") or 0))
    except Exception:
        pass
    return out


def _up_journal_close_quick_edit() -> None:
    for key in (
        "up_journal_quick_row_key",
        "up_journal_quick_bc",
        "up_qe_suuid",
        "up_qe_puid",
        "up_qe_weight",
        "up_qe_len",
        "up_qe_wid",
        "up_qe_h",
    ):
        st.session_state.pop(key, None)


def _up_journal_open_quick_edit(bc: str, row_key: str, row) -> None:
    """Відкрити швидке редагування ваги/габаритів для рядка журналу."""
    bc = _up_format_bc_display(bc)
    if not bc:
        return
    if st.session_state.get("up_journal_quick_row_key") == row_key:
        _up_journal_close_quick_edit()
        return
    dims = _up_journal_parcel_dims_from_row(row)
    if not dims.get("suuid"):
        data, err = up_fetch_shipment(bc)
        if err:
            st.toast(str(err)[:160], icon="⚠️")
            return
        if isinstance(data, dict):
            p = _up_first_parcel_from_response(data)
            dims["suuid"] = str(_up_shipment_uuid_from_response(data) or "").strip()
            dims["puid"] = str(p.get("uuid") or "").strip()
            dims["weight"] = max(1, int(p.get("weight") or 500))
            dims["length"] = max(1, int(p.get("length") or 30))
            dims["width"] = max(0, int(p.get("width") or 0))
            dims["height"] = max(0, int(p.get("height") or 0))
    if not dims.get("suuid"):
        st.toast("Немає UUID відправлення для збереження.", icon="⚠️")
        return
    st.session_state.up_journal_quick_row_key = row_key
    st.session_state.up_journal_quick_bc = bc
    st.session_state.up_qe_suuid = dims["suuid"]
    st.session_state.up_qe_puid = dims.get("puid") or ""
    st.session_state.up_qe_weight = dims["weight"]
    st.session_state.up_qe_len = dims["length"]
    st.session_state.up_qe_wid = dims["width"]
    st.session_state.up_qe_h = dims["height"]


def _up_journal_save_quick_edit(bc: str) -> tuple[bool, str]:
    suuid = str(st.session_state.get("up_qe_suuid", "") or "").strip()
    if not suuid:
        return False, "Немає UUID відправлення."
    puid = str(st.session_state.get("up_qe_puid", "") or "").strip()
    w, ln, wid, hgt = _up_normalize_parcel_dims(
        st.session_state.get("up_qe_weight"),
        st.session_state.get("up_qe_len"),
        st.session_state.get("up_qe_wid"),
        st.session_state.get("up_qe_h"),
    )
    parcel = {"weight": w, "length": ln, "width": wid, "height": hgt}
    if puid:
        parcel["uuid"] = puid
    data, err = up_put_shipment_update(suuid, {"parcels": [parcel]})
    if err:
        return False, err
    bc = _up_format_bc_display(bc)
    if bc:
        _up_clear_sticker_pdf_cache(bc)
    if isinstance(data, dict):
        up_journal_save_response(data)
        _cached_up_shipments_df.clear()
    return True, ""


def _up_journal_render_quick_edit_panel(bc: str) -> None:
    with st.container(border=True):
        st.markdown(
            f"**Швидке редагування** · `{bc}` — вага та габарити (см)",
        )
        q1, q2, q3, q4 = st.columns(4)
        with q1:
            st.number_input("Вага, г", min_value=1, step=50, key="up_qe_weight")
        with q2:
            st.number_input("Довжина, см", min_value=1, step=1, key="up_qe_len")
        with q3:
            st.number_input("Ширина, см", min_value=0, step=1, key="up_qe_wid")
        with q4:
            st.number_input("Висота, см", min_value=0, step=1, key="up_qe_h")
        sb, sc = st.columns([1, 2])
        with sb:
            if st.button("Зберегти", type="primary", key="up_qe_save_btn", use_container_width=True):
                ok, err = _up_journal_save_quick_edit(bc)
                if err:
                    st.error(err)
                elif ok:
                    st.toast("Збережено в Укрпошті", icon="✅")
                    _up_journal_close_quick_edit()
                    st.rerun()
        with sc:
            if st.button("Скасувати", key="up_qe_cancel_btn"):
                _up_journal_close_quick_edit()
                st.rerun()


def _up_journal_request_edit(bc_sel: str) -> None:
    """Поставити редагування в чергу (заповнення форми — на наступному rerun до віджетів)."""
    bc = _up_format_bc_display(bc_sel)
    if not bc:
        return
    _up_journal_close_quick_edit()
    st.session_state.upwiz_pending_edit_bc = bc
    st.session_state.upwiz_form_open = True
    st.session_state.up_journal_edit_bc = ""
    st.session_state.up_edit_panel_open = False


def _up_process_pending_wizard_edit() -> None:
    """Завантажити ТТН з API і заповнити upwiz_* до малювання віджетів."""
    bc = st.session_state.pop("upwiz_pending_edit_bc", None)
    if not bc:
        return
    bc = _up_format_bc_display(bc)
    if not bc:
        return
    data, err = up_fetch_shipment(bc)
    if err:
        st.session_state.upwiz_form_open = False
        st.session_state.upwiz_edit_mode = False
        st.error(err)
        return
    if isinstance(data, dict):
        merged_desc = _up_description_for_edit(bc, data)
        if merged_desc:
            data = dict(data)
            data["description"] = merged_desc
    if not _up_seed_wizard_from_shipment(data, force=True):
        st.session_state.upwiz_form_open = False
        st.session_state.upwiz_edit_mode = False
        st.error("Не вдалося підготувати форму редагування.")
        return
    st.session_state.up_last_create_response = data
    st.session_state.up_journal_active_bc = bc


def _up_journal_on_select_all():
    """Обрати / зняти всі рядки поточного дня."""
    entries = st.session_state.get("_up_journal_day_entries", [])
    flag = bool(st.session_state.get("up_journal_chk_all", False))
    for ent in entries:
        st.session_state[f"up_jc_{ent['key']}"] = flag


def _up_journal_checked_barcodes() -> list:
    entries = st.session_state.get("_up_journal_day_entries", [])
    return [
        ent["bc"]
        for ent in entries
        if ent.get("bc") and st.session_state.get(f"up_jc_{ent['key']}", False)
    ]


def _up_journal_checked_entries() -> list:
    entries = st.session_state.get("_up_journal_day_entries", [])
    return [
        ent
        for ent in entries
        if st.session_state.get(f"up_jc_{ent['key']}", False)
    ]


def _up_journal_delete_bc(bc: str, local_only: bool = False) -> bool:
    bc = _up_format_bc_display(bc)
    if not bc:
        return False
    if not local_only:
        ok, derr = up_delete_shipment_by_barcode(bc)
        if not ok:
            st.error(derr)
            return False
    if sheets.delete_up_shipment_record(bc):
        _cached_up_shipments_df.clear()
        if _up_normalize_bc(st.session_state.get("up_journal_edit_bc", "")) == _up_normalize_bc(bc):
            st.session_state.up_last_create_response = None
            st.session_state.up_journal_edit_bc = ""
            st.session_state.up_journal_active_bc = ""
            st.session_state.up_edit_panel_open = False
        st.session_state.pop(f"up_jc_{bc}", None)
        return True
    st.warning("Запис у журналі не знайдено.")
    return False


def _up_journal_hdr(label: str, *, hint: str = "", compact: bool = False) -> None:
    title = html.escape(hint or label)
    text = html.escape(label)
    extra = " up-journal-hdr-fit" if compact else ""
    st.markdown(
        f'<p class="up-journal-hdr{extra}" title="{title}">{text}</p>',
        unsafe_allow_html=True,
    )


def _up_journal_actions_css():
    st.markdown(
        """
<style>
.up-journal-cell {
  margin: 0;
  padding: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.86rem;
  line-height: 1.3rem;
  color: var(--journal-cell, #E5E7EB) !important;
}
.up-journal-multiline {
  white-space: normal !important;
  overflow: hidden;
  text-overflow: clip;
  line-height: 1.2rem !important;
  font-size: 0.82rem !important;
  color: var(--journal-cell-muted, #D1D5DB) !important;
}
.up-journal-bc {
  font-size: 0.98rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.03em;
  font-variant-numeric: tabular-nums;
  color: var(--journal-bc, #F9FAFB) !important;
}
.up-journal-hdr {
  margin: 0 0 0.35rem 0;
  padding: 0.4rem 0.2rem 0.3rem;
  font-size: 0.82rem;
  font-weight: 700;
  line-height: 1.2rem;
  color: var(--journal-hdr-fg, #F3F4F6) !important;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-bottom: 2px solid var(--journal-hdr-accent, #4ADE80);
  background: var(--journal-hdr-bg, #374151);
  border-radius: 10px 10px 0 0;
}
.up-journal-hdr-fit {
  overflow: visible;
  text-overflow: clip;
  font-size: 0.74rem;
  padding-left: 0.05rem;
  padding-right: 0.05rem;
}
.up-journal-cell-narrow {
  font-size: 0.8rem !important;
}
.up-journal-postpay {
  font-weight: 700 !important;
  color: var(--journal-postpay, #4ADE80) !important;
}
.up-journal-row-draft {
  border-left: 3px solid #f59e0b;
  padding-left: 0.35rem;
  margin-bottom: 0.15rem;
  opacity: 0.95;
}
.up-journal-row-active {
  background: var(--journal-row-active-bg, rgba(55, 65, 81, 0.55));
  border: 1px solid var(--journal-row-active-border, #6B7280);
  border-radius: 12px;
  padding: 0.25rem 0.4rem;
  margin: 0.2rem 0;
}
div:has(> .up-journal-bc-click) + div button {
  font-size: 0.98rem !important;
  font-weight: 600 !important;
  letter-spacing: 0.03em;
  padding: 0.15rem 0.25rem !important;
  min-height: auto !important;
  height: auto !important;
  border: none !important;
  background: transparent !important;
  color: var(--journal-link, #93C5FD) !important;
  text-decoration: underline;
  box-shadow: none !important;
}
div:has(> .up-journal-bc-click) + div button:hover {
  color: var(--journal-link-hover, #BFDBFE) !important;
  background: rgba(59, 130, 246, 0.15) !important;
}
div:has(> .up-journal-bc-click) + div button p,
div:has(> .up-journal-bc-click) + div button span {
  color: var(--journal-link, #93C5FD) !important;
}
button[aria-label="Редагувати"],
button[aria-label="Перегляд / друк PDF"],
button[aria-label="Видалити"] {
  padding: 0 !important;
  margin: 0 auto !important;
  min-width: 2rem !important;
  max-width: 2rem !important;
  width: 2rem !important;
  min-height: 2rem !important;
  max-height: 2rem !important;
  height: 2rem !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  font-size: 1.15rem !important;
}
button[aria-label="Редагувати"] > div,
button[aria-label="Перегляд / друк PDF"] > div,
button[aria-label="Видалити"] > div,
button[aria-label="Редагувати"] [data-testid="stMarkdownContainer"],
button[aria-label="Перегляд / друк PDF"] [data-testid="stMarkdownContainer"],
button[aria-label="Видалити"] [data-testid="stMarkdownContainer"] {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: 100% !important;
  padding: 0 !important;
  margin: 0 !important;
}
button[aria-label="Редагувати"] p,
button[aria-label="Перегляд / друк PDF"] p,
button[aria-label="Видалити"] p {
  margin: 0 auto !important;
  padding: 0 !important;
  font-size: 1.15rem !important;
  line-height: 1 !important;
  text-align: center !important;
  width: auto !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _up_journal_sync_bar() -> None:
    """Підтягнути ТТН з Укрпошти за списком ШКІ (наприклад, створені на Rozetka)."""
    import re as _re

    with st.expander("🔄 Підтягнути ТТН з Укрпошти за ШКІ", expanded=False):
        st.caption(
            "Вкажи штрих-коди (ШКІ) відправлень, створених напряму на сайті Укрпошти "
            "або через Rozetka — по одному на рядок або через пробіл / кому. "
            "Журнал поповниться повними даними з API."
        )
        st.info(
            "ℹ️ **Якщо ТТН створено через Rozetka** — найімовірніше eCom-API "
            "поверне `UPE05001 Counterparty mismatch`. Це **не помилка твоїх токенів**: "
            "у термінах УП eCom *власником* ТТН є той, хто зробив `POST /shipments`. "
            "Розетка робить його зі **своїм** Bearer-токеном, навіть якщо `sender` — твій. "
            "Тому повна ТТН недоступна, але я підтягну її з трекінг-API (статус, дата) "
            "і додам у журнал з міткою «з трекінгу»."
        )
        st.text_area(
            "ШКІ Укрпошти",
            key="up_journal_sync_bcs",
            placeholder="0500000000001\n0500000000002\nабо 0500000000001, 0500000000002",
            height=90,
            label_visibility="collapsed",
        )
        col_btn, col_pad = st.columns([1.6, 6.4])
        with col_btn:
            do_sync = st.button(
                "🔄 Підтягнути",
                key="up_journal_sync_btn",
                use_container_width=True,
                type="primary",
                help="GET /shipments/barcode/{ШКІ} → запис у журнал",
            )
        if do_sync:
            raw_input = str(st.session_state.get("up_journal_sync_bcs", "") or "")
            tokens = [t for t in _re.split(r"[\s,;]+", raw_input) if t.strip()]
            if not tokens:
                st.warning("Введи хоча б один ШКІ (13 цифр).")
            else:
                with st.spinner(f"Запитую {len(tokens)} ТТН в Укрпошти…"):
                    ok_full, ok_tracking, errs = up_sync_journal_by_barcodes(tokens)
                total_ok = ok_full + ok_tracking
                if total_ok:
                    _cached_up_shipments_df.clear()
                    st.session_state.pop("_up_journal_desc_cache", None)
                    parts = []
                    if ok_full:
                        parts.append(f"повні дані: **{ok_full}**")
                    if ok_tracking:
                        parts.append(f"з трекінгу: **{ok_tracking}**")
                    st.success("Дописано / оновлено — " + " · ".join(parts))
                if errs:
                    st.warning("Деталі / попередження:\n• " + "\n• ".join(errs[:15]))
                if total_ok and not errs:
                    st.session_state["up_journal_sync_bcs"] = ""
                if total_ok:
                    st.rerun()


def _render_up_shipments_journal():
    """Журнал створених ТТН: дата зі стрілками, список за день, редагування."""
    _up_journal_actions_css()
    _up_journal_sync_bar()

    df = _cached_up_shipments_df()
    draft_items = rozetka_api.draft_journal_entries()
    if (df is None or df.empty) and not draft_items:
        st.info("Поки немає ТТН. Натисни **🔄 Синхронізувати** зверху або **Створити**.")
        return

    if df is None or df.empty:
        df = pd.DataFrame(columns=sheets.UP_SHIPMENTS_HEADERS)
    else:
        df = df.copy()

    df = df.copy()
    if "ШКІ" in df.columns:
        def _fmt_journal_bc(v):
            s = str(v or "").strip()
            if rozetka_api.is_draft_journal_code(s):
                return ""
            return _up_format_bc_display(v)

        df["ШКІ"] = df["ШКІ"].apply(_fmt_journal_bc)
    if "Дод. інфо" not in df.columns:
        df["Дод. інфо"] = ""
    if "Післяплата" not in df.columns:
        df["Післяплата"] = ""
    df["_dt"] = pd.to_datetime(df["Час"], errors="coerce")
    df["_day"] = df["_dt"].dt.date
    days_sorted = sorted({d for d in df["_day"].dropna().unique()}, reverse=True)
    today = utils.today_kyiv()

    selected = st.session_state.get("up_journal_selected_day")
    if selected is not None and not hasattr(selected, "strftime"):
        try:
            selected = pd.to_datetime(selected).date()
        except Exception:
            selected = None
    if selected not in days_sorted:
        selected = today if today in days_sorted else days_sorted[0]
    st.session_state.up_journal_selected_day = selected
    try:
        day_idx = days_sorted.index(selected)
    except ValueError:
        day_idx = 0

    chunk = df[df["_day"] == selected].sort_values("_dt", ascending=False)
    day_label = selected.strftime("%d.%m.%Y") + (" · сьогодні" if selected == today else "")

    day_entries: list = []
    for item in draft_items:
        row = item.get("row") if isinstance(item.get("row"), dict) else {}
        row_dt = pd.to_datetime(row.get("Час"), errors="coerce")
        if pd.isna(row_dt) or row_dt.date() != selected:
            continue
        oid = str(item.get("oid") or "")
        day_entries.append(
            {
                "key": f"draft_{oid}",
                "bc": "",
                "bc_label": rozetka_api.draft_row_label(oid) if oid.isdigit() else "Rozetka",
                "row": row,
                "is_draft": True,
                "draft_ent": item,
            }
        )

    for row_i, (_, row) in enumerate(chunk.iterrows()):
        raw_bc = str(row.get("ШКІ", "") or "").strip()
        if rozetka_api.is_draft_journal_code(raw_bc):
            continue
        bc = _up_format_bc_display(raw_bc)
        if not bc:
            continue
        row_key = f"j{row_i}"
        day_entries.append(
            {
                "key": row_key,
                "bc": bc,
                "bc_label": bc,
                "row": row,
                "is_draft": False,
                "draft_ent": None,
            }
        )

    if not day_entries:
        st.info(f"За {selected.strftime('%d.%m.%Y')} відправлень немає.")
        return

    nav_l, nav_c, nav_r, nav_rf = st.columns([0.7, 7.3, 0.7, 0.55])
    with nav_l:
        if st.button(
            "◀",
            key="up_journal_day_older",
            use_container_width=True,
            disabled=day_idx >= len(days_sorted) - 1,
        ):
            st.session_state.up_journal_selected_day = archive_shift_day(
                days_sorted, selected, 1
            )
            st.rerun()
    with nav_c:
        st.markdown(
            f"<p style='margin:0;text-align:center;font-size:1.05rem;font-weight:600'>"
            f"{day_label} · <span style='font-weight:400'>{len(day_entries)} шт.</span></p>",
            unsafe_allow_html=True,
        )
    with nav_r:
        if st.button(
            "▶",
            key="up_journal_day_newer",
            use_container_width=True,
            disabled=day_idx <= 0,
        ):
            st.session_state.up_journal_selected_day = archive_shift_day(
                days_sorted, selected, -1
            )
            st.rerun()
    with nav_rf:
        if st.button("↻", key="up_journal_refresh_btn", help="Оновити список"):
            _cached_up_shipments_df.clear()
            st.session_state.pop("_up_journal_desc_cache", None)
            st.rerun()

    st.session_state._up_journal_day_entries = day_entries
    st.session_state._up_journal_day_bcs = [e["bc"] for e in day_entries]
    for ent in day_entries:
        chk_key = f"up_jc_{ent['key']}"
        if chk_key not in st.session_state:
            st.session_state[chk_key] = False

    force_desc = bool(st.session_state.pop("_up_journal_force_desc_fetch", False))
    _up_journal_prefetch_descriptions(day_entries, force_api=force_desc)

    all_selected = bool(day_entries) and all(
        st.session_state.get(f"up_jc_{e['key']}", False) for e in day_entries
    )

    col_weights = [0.31, 0.62, 1.12, 1.2, 0.56, 0.44, 0.48, 0.5, 0.76, 1.06]
    hdr = st.columns(col_weights)
    hdr_specs = [
        ("chk", ""),
        ("hdr", "Час", "", False),
        ("hdr", "ШКІ", "Штрих-код відправлення", False),
        ("hdr", "Одержувач", "ПІБ та телефон", False),
        ("hdr", "Статус", "Статус Укрпошти", True),
        ("hdr", "Тариф", "", True),
        ("hdr", "Вартість", "Оголошена вартість", True),
        ("hdr", "Післяпл.", "Післяплата, грн", True),
        ("hdr", "Дод. інфо", "Додаткова інформація", False),
        ("act", "", False),
    ]
    for col, spec in zip(hdr, hdr_specs):
        with col:
            kind = spec[0]
            if kind == "chk":
                st.checkbox(
                    "Всі",
                    value=all_selected,
                    key="up_journal_chk_all",
                    on_change=_up_journal_on_select_all,
                    label_visibility="collapsed",
                )
            elif kind == "hdr":
                _up_journal_hdr(
                    spec[1],
                    hint=spec[2] if len(spec) > 2 else "",
                    compact=bool(spec[3]) if len(spec) > 3 else False,
                )
            else:
                _up_journal_hdr("Дії", hint="Редагувати · Друк · Видалити", compact=True)

    st.caption(
        "У колонці **ШКІ** — офіційний штрих-код Укрпошти (13 цифр). "
        "Рядок **Rozetka #…** — чернетка до натискання **Створити**."
    )

    for ent in day_entries:
        row_key = ent["key"]
        bc = ent["bc"]
        bc_label = str(ent.get("bc_label") or bc or "—")
        row = ent["row"]
        is_draft = bool(ent.get("is_draft"))
        draft_ent = ent.get("draft_ent") if is_draft else None
        desc = str(ent.get("display_desc") or _up_journal_description_from_row(row) or "").strip()
        desc_short = (desc[:40] + "…") if len(desc) > 40 else (desc or "—")
        row_active = st.session_state.get("up_journal_quick_row_key") == row_key
        if row_active:
            st.markdown('<div class="up-journal-row-active">', unsafe_allow_html=True)
        if is_draft:
            st.markdown('<div class="up-journal-row-draft">', unsafe_allow_html=True)
        rcols = st.columns(col_weights)
        with rcols[0]:
            st.checkbox(
                "·",
                key=f"up_jc_{row_key}",
                label_visibility="collapsed",
            )
        with rcols[1]:
            _up_journal_cell("", lines=_up_journal_time_lines(row.get("Час", "")))
        with rcols[2]:
            st.markdown('<div class="up-journal-bc-click"></div>', unsafe_allow_html=True)
            if st.button(
                bc_label,
                key=f"up_jqb_{row_key}",
                type="tertiary",
                help=(
                    "ШКІ з’явиться після «Створити» в Укрпошті"
                    if is_draft
                    else "Швидке редагування ваги та габаритів"
                ),
                use_container_width=True,
            ):
                if is_draft and isinstance(draft_ent, dict):
                    rozetka_api.apply_up_wizard_prefill(draft_ent.get("prefill") or {})
                    st.rerun()
                else:
                    _up_journal_open_quick_edit(bc, row_key, row)
                    st.rerun()
        with rcols[3]:
            _up_journal_cell(
                "",
                lines=_up_journal_recipient_lines(
                    row.get("Отримувач", ""),
                    row.get("Телефон", ""),
                ),
            )
        with rcols[4]:
            _up_journal_cell(
                _up_status_journal_label(row.get("Статус УП", "")),
                cell_class="up-journal-cell-narrow",
            )
        with rcols[5]:
            _up_journal_cell(
                _up_tariff_journal_label(row.get("Тариф", "")),
                cell_class="up-journal-cell-narrow",
            )
        with rcols[6]:
            cost_cell = _up_journal_declared_from_row(row)
            _up_journal_cell(
                cost_cell if cost_cell else "—",
                cell_class="up-journal-cell-narrow",
            )
        with rcols[7]:
            postpay_cell = _up_journal_postpay_from_row(row)
            _up_journal_cell(
                postpay_cell if postpay_cell else "—",
                cell_class="up-journal-cell-narrow up-journal-postpay",
            )
        with rcols[8]:
            _up_journal_cell(desc_short)
        with rcols[9]:
            hide_pr = bool(st.session_state.get("up_journal_hide_price"))
            ic1, ic2, ic3 = st.columns(3, gap="small")
            with ic1:
                if st.button(
                    "✏️",
                    key=f"up_je_{row_key}",
                    help="Продовжити оформлення" if is_draft else "Редагувати",
                    type="secondary",
                ):
                    if is_draft and isinstance(draft_ent, dict):
                        rozetka_api.apply_up_wizard_prefill(draft_ent.get("prefill") or {})
                    else:
                        _up_journal_request_edit(bc)
                    st.rerun()
            with ic2:
                if is_draft:
                    st.caption("—")
                else:
                    _up_journal_print_controls(
                        bc,
                        hide_pr,
                        key_suffix=row_key,
                        shipment_uuid=str(row.get("UUID", "") or ""),
                    )
            with ic3:
                if st.button(
                    "🗑️",
                    key=f"up_jd_{row_key}",
                    help="Прибрати чернетку" if is_draft else "Видалити",
                    type="secondary",
                ):
                    if is_draft and isinstance(draft_ent, dict):
                        rozetka_api.clear_up_journal_draft(draft_ent.get("oid"))
                        st.toast("Чернетку прибрано", icon="🗑")
                        st.rerun()
                    else:
                        local_only = bool(st.session_state.get("up_journal_delete_local_only", False))
                        if _up_journal_delete_bc(bc, local_only=local_only):
                            st.toast("Видалено", icon="🗑")
                            st.rerun()

        if row_active and not is_draft:
            _up_journal_render_quick_edit_panel(bc)
        if row_active or is_draft:
            st.markdown("</div>", unsafe_allow_html=True)

    checked_entries = _up_journal_checked_entries()
    if checked_entries:
        printable_entries = [
            e for e in checked_entries if not e.get("is_draft") and e.get("bc")
        ]
        st.caption(
            f"Обрано: **{len(checked_entries)}**"
            + (f" · до друку: **{len(printable_entries)}**" if printable_entries else "")
        )
        b1, b2, b3, b4 = st.columns([1, 1.1, 1.2, 1.4])
        with b1:
            only_local = st.checkbox(
                "Лише з журналу",
                key="up_journal_delete_local_only",
            )
        with b2:
            if st.button(
                f"🗑 Видалити ({len(checked_entries)})",
                type="secondary",
                use_container_width=True,
            ):
                ok_n = 0
                for ent in _up_journal_checked_entries():
                    if ent.get("is_draft"):
                        dent = ent.get("draft_ent") or {}
                        rozetka_api.clear_up_journal_draft(dent.get("oid"))
                        ok_n += 1
                    elif _up_journal_delete_bc(ent.get("bc", ""), local_only=only_local):
                        ok_n += 1
                if ok_n:
                    st.success(f"Видалено: {ok_n}")
                    st.rerun()
        with b3:
            if st.button(
                f"🖨 Друкувати ({len(printable_entries)})",
                type="primary",
                use_container_width=True,
                disabled=not printable_entries,
                help="Один PDF із усіма обраними ярликами",
            ):
                hide_pr = bool(st.session_state.get("up_journal_hide_price"))
                idents = []
                for ent in printable_entries:
                    suuid = str(ent["row"].get("UUID", "") or "")
                    bc_v = str(ent.get("bc", "") or "")
                    ident = _up_sticker_ident(bc_v, suuid)
                    if ident:
                        idents.append(ident)
                if not idents:
                    st.warning("У обраних немає ШКІ / UUID для друку.")
                else:
                    with st.spinner(
                        f"Готую PDF на {len(idents)} ярлик(ів)…"
                    ):
                        pdf, perr = up_fetch_stickers_pdf_bytes_multi(
                            idents, hide_delivery_price=hide_pr
                        )
                    if pdf:
                        _up_journal_open_pdf_in_browser(pdf)
                        st.toast(
                            f"Відкрито PDF на {len(idents)} ярлик(ів)", icon="🖨️"
                        )
                    else:
                        st.error(perr or "Не вдалося отримати PDF.")
        with b4:
            st.checkbox("PDF без варт. дост.", key="up_journal_hide_price")


def _render_up_shipment_edit_section(source: dict | None):
    """Форма редагування останнього (або завантаженого) відправлення УП."""
    if not source or not isinstance(source, dict):
        return
    suuid = _up_shipment_uuid_from_response(source)
    if not suuid:
        st.caption("У відповіді API немає `uuid` відправлення — редагування недоступне.")
        return

    _up_seed_edit_form_from_shipment(source)
    status = str(st.session_state.get("up_edit_lifecycle_status", "") or _up_lifecycle_status(source))
    bc = str(st.session_state.get("up_edit_barcode", "") or "")
    expanded = bool(st.session_state.get("up_edit_panel_open")) or status in ("", "CREATED")

    with st.expander("Редагувати відправлення в Укрпошті", expanded=expanded):
        st.caption(f"UUID: `{suuid}`" + (f" · ШКІ: `{bc}`" if bc else "") + (f" · статус: **{status}**" if status else ""))
        if not str(st.session_state.get("up_edit_parcel_uuid", "")).strip():
            st.info(
                "Немає uuid місця (parcel) у відповіді — натисни **Завантажити** за ШКІ після створення ТТН."
            )
        if status and status != "CREATED":
            st.warning(
                "Зміни через API зазвичай можливі лише в статусі **CREATED** (до прийому на пошті). "
                "Якщо збереження не вдасться — редагуй у кабінеті ok.ukrposhta."
            )

        bc_ro = _up_format_bc_display(
            st.session_state.get("up_edit_barcode")
            or st.session_state.get("up_edit_load_barcode", "")
        )
        if bc_ro:
            st.session_state.up_edit_load_barcode = bc_ro
            st.markdown(f"**ШКІ:** `{bc_ro}`")
            if st.button("Оновити з API", key="up_edit_reload_btn"):
                data, err = up_fetch_shipment(bc_ro)
                if err:
                    st.error(err)
                elif data:
                    st.session_state.up_last_create_response = data
                    st.session_state.up_edit_seeded_uuid = ""
                    _up_seed_edit_form_from_shipment(data, force=True)
                    st.rerun()
        else:
            st.info("ШКІ не визначено — відкрийте відправлення з журналу.")

        st.markdown("**Адреса отримувача**")
        if st.button("Підставити індекс з УП", key="up_edit_lookup_postcode"):
            pc = str(st.session_state.get("up_edit_postcode", "")).strip()
            res, err = up_lookup_by_postcode(pc)
            if err:
                st.error(err)
            elif res:
                st.session_state.up_edit_region = res.get("region", "")
                st.session_state.up_edit_district = res.get("district", "")
                st.session_state.up_edit_city = res.get("city", "")
                st.rerun()
        a1, a2 = st.columns(2)
        with a1:
            st.text_input("Індекс *", key="up_edit_postcode", max_chars=5)
            st.text_input("Район", key="up_edit_district")
        with a2:
            st.text_input("Область *", key="up_edit_region")
            st.text_input("Населений пункт *", key="up_edit_city")
        a3, a4, a5 = st.columns(3)
        with a3:
            st.text_input("Вулиця", key="up_edit_street")
        with a4:
            st.text_input("Будинок", key="up_edit_house")
        with a5:
            st.text_input("Квартира", key="up_edit_apartment")
        r1, r2, r3 = st.columns(3)
        with r1:
            st.text_input("Прізвище", key="up_edit_lastname")
        with r2:
            st.text_input("Імʼя", key="up_edit_firstname")
        with r3:
            _pp = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
            st.text_input(
                "По батькові" + (" *" if _pp >= 1 else ""),
                key="up_edit_middlename",
                help="Обовʼязково для післяплати (Укрпошта UPE01002).",
            )
        st.text_input(
            "Телефон отримувача",
            key="up_edit_phone",
            placeholder="+380XXXXXXXXX",
            on_change=_up_on_phone_input_change,
            args=("up_edit_phone",),
        )
        if _up_num_float(st.session_state.get("up_edit_postpay_uah", 0)) >= 1:
            st.caption("При післяплаті Укрпошта вимагає повне ПІБ отримувача.")

        st.markdown("**Відправлення**")
        labels = list(_UP_DELIVERY_LABELS.keys())
        st.selectbox("Тип доставки", labels, key="up_edit_delivery_label_pick")
        st.text_area("Опис відправлення", key="up_edit_description", height=72)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.number_input("Вага, г", min_value=1, max_value=30000, step=50, key="up_edit_weight_g")
        with m2:
            st.number_input("Довжина, см", min_value=1, max_value=200, step=1, key="up_edit_length_cm")
        with m3:
            st.number_input("Ширина, см", min_value=0, max_value=200, step=1, key="up_edit_width_cm")
        with m4:
            st.number_input("Висота, см", min_value=0, max_value=200, step=1, key="up_edit_height_cm")
        e1, e2 = st.columns(2)
        with e1:
            st.number_input("Оголошена вартість, грн", min_value=0.0, step=1.0, key="up_edit_declared_uah")
        with e2:
            st.number_input("Післяплата, грн", min_value=0.0, step=1.0, key="up_edit_postpay_uah")
        st.checkbox("Зараховувати післяплату на IBAN", key="up_edit_transfer_postpay_iban")
        p1, p2 = st.columns(2)
        with p1:
            st.checkbox("Доставку сплачує одержувач", key="up_edit_paid_shipment_recipient")
        with p2:
            st.checkbox("Пересилання післяплати сплачує одержувач", key="up_edit_paid_postpay_recipient")
        st.checkbox("СМС", key="up_edit_sms")
        st.checkbox("Огляд при врученні", key="up_edit_check_delivery")
        st.radio(
            "У разі невручення",
            ["повернути", "не повертати"],
            key="up_edit_fail_main",
            horizontal=True,
        )

        if st.button("Зберегти зміни в Укрпошті", type="primary", key="up_edit_save_btn"):
            v_err = _up_validate_edit_form()
            if v_err:
                st.error(v_err)
            else:
                data, err = _up_save_shipment_edit(suuid)
                if err:
                    st.error(f"Редагування: {err}")
                else:
                    st.session_state.up_last_create_response = data
                    st.session_state.up_edit_seeded_uuid = ""
                    _up_seed_edit_form_from_shipment(data, force=True)
                    new_bc = _up_barcode_from_create_response(data)
                    st.success(
                        f"Зміни збережено."
                        + (f" ШКІ: `{new_bc}`" if new_bc else "")
                        + (
                            f" Вартість доставки: {data.get('deliveryPrice')} грн"
                            if isinstance(data, dict) and data.get("deliveryPrice") is not None
                            else ""
                        )
                    )
                    st.toast("Укрпошта: відправлення оновлено", icon="✅")
                    up_journal_save_response(data)
                    _up_clear_sticker_pdf_cache(bc or new_bc)

        if bc:
            suuid_ed = str(st.session_state.get("up_edit_shipment_uuid", "") or suuid)
            if st.button("PDF ярлик", key="up_edit_fetch_sticker", use_container_width=True):
                _up_clear_sticker_pdf_cache(bc)
                with st.spinner("PDF…"):
                    pdf, perr = up_fetch_sticker_pdf_bytes(
                        bc, shipment_uuid=suuid_ed
                    )
                if pdf:
                    st.download_button(
                        "Зберегти / друкувати PDF",
                        data=pdf,
                        file_name=f"up_sticker_{bc}.pdf",
                        mime="application/pdf",
                        key=f"up_edit_dl_sticker_{int(time.time())}",
                        use_container_width=True,
                    )
                else:
                    st.error(perr or "Не вдалося отримати PDF")


UP_ECOM_BASE = "https://www.ukrposhta.ua/ecom/0.0.1"
UP_CLASSIFIER_BASES = (
    "https://www.ukrposhta.ua/address-classifier-ws",
    "https://ukrposhta.ua/address-classifier-ws",
)
_UP_DELIVERY_LABELS = {
    "склад – склад": "W2W",
    "двері – двері": "D2D",
    "склад – двері": "W2D",
    "двері – склад": "D2W",
}
_UP_SERVICE_API = {
    "Базовий": "STANDARD",
    "Пріоритетний": "EXPRESS",
}
_UP_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _up_is_valid_uuid(val: str) -> bool:
    return bool(_UP_UUID_RE.match(str(val or "").strip()))


def _up_ecom_token() -> str:
    """PROD counterparty token для ?token= (лист менеджера УП)."""
    load_secrets_to_config()
    return (
        str(getattr(config, "UP_COUNTERPARTY_TOKEN", "") or "").strip()
        or str(getattr(config, "UP_USER_TOKEN", "") or "").strip()
    )


def _up_format_ecom_error(err: str) -> str:
    if not err:
        return err
    s = str(err)
    if "UPE05001" in s or "Counterparty mismatch" in s:
        tok = _up_ecom_token()
        uuid = str(getattr(config, "UP_UUID", "") or "").strip()
        sender = str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
        return (
            "Контрагент не збігається (UPE05001): **UP_BEARER_TOKEN**, **UP_UUID**, "
            "**UP_COUNTERPARTY_TOKEN** / **UP_USER_TOKEN** і **UP_SENDER_UUID** "
            "мають бути з **одного** PRODUCTION-набору (лист від менеджера Укрпошти).\n\n"
            f"Токен …{tok[-12:] if len(tok) > 12 else tok or '—'}, "
            f"UP_UUID …{uuid[-12:] if len(uuid) > 12 else uuid or '—'}, "
            f"відправник …{sender[-12:] if len(sender) > 12 else sender or '—'}.\n\n"
            "**UP_SENDER_UUID** — UUID **клієнта-відправника** в eCom (не плутати з UP_UUID контрагента). "
            "Його видно в кабінеті ok.ukrposhta або через «Перевірити відправника» у діагностиці.\n\n"
            f"Відповідь API: {s}"
        )
    return s


def _up_verify_sender_uuid(sender_uuid: str = "") -> str:
    """Порожній рядок = OK; інакше текст помилки."""
    load_secrets_to_config()
    sender = (sender_uuid or str(getattr(config, "UP_SENDER_UUID", "") or "")).strip()
    err = _up_uuid_error(sender, "UUID відправника (UP_SENDER_UUID)")
    if err:
        return err
    data, err = up_ecom_request("GET", f"/clients/{sender}")
    if err:
        if "UPE05001" in err or "Counterparty mismatch" in err:
            return (
                f"UP_SENDER_UUID …{sender[-12:]} **чужий** — не від вашого контрагента "
                f"({str(getattr(config, 'UP_UUID', '') or '')[-12:]}). "
                "Видали рядок UP_SENDER_UUID з Secrets (залиш ключі з листа менеджера) — "
                "додаток створить відправника сам, якщо є UP_SENDER_NAME, UP_SENDER_BRANCH_INDEX "
                "та UP_SENDER_PHONE. Або вкажи правильний UUID з ok.ukrposhta → eCom."
            )
        if "UPE02001" in err or "not found" in err.lower():
            return (
                f"Відправника {sender} не знайдено для вашого токена eCom. "
                "Вкажи правильний UP_SENDER_UUID з кабінету ok.ukrposhta (клієнт-відправник)."
            )
        return _up_format_ecom_error(err)
    cp = str((data or {}).get("counterpartyUuid", "")).strip()
    expected = str(getattr(config, "UP_UUID", "") or "").strip()
    if expected and cp and cp.lower() != expected.lower():
        return (
            f"UP_SENDER_UUID належить контрагенту {cp}, а UP_UUID у Secrets — {expected}. "
            "Усі ключі мають бути з одного листа PRODUCTION."
        )
    ctype = str((data or {}).get("type") or "").strip()
    if _up_expect_fop_sender() and ctype and ctype != "PRIVATE_ENTREPRENEUR":
        return (
            f"UP_SENDER_UUID — це **{_up_client_type_label(ctype)}**, а не ФОП. "
            "Видали рядок **UP_SENDER_UUID** з Secrets, додай **UP_SENDER_TIN** (ІПН) — "
            "додаток створить клієнта типу ФОП автоматично."
        )
    return ""


def _up_uuid_error(val: str, label: str) -> str:
    """Порожній рядок = OK; інакше текст помилки."""
    s = str(val or "").strip()
    if not s:
        return f"Немає {label}."
    low = s.lower()
    if "твій-uuid" in low or "xxxxxxxx-xxxx" in low or low.startswith("твій "):
        return (
            f"{label} — це приклад із інструкції, не справжній UUID. "
            f"Візьми UUID відправника з кабінету eCom Укрпошти (ok.ukrposhta) і вкажи в Secrets як UP_SENDER_UUID."
        )
    if not _up_is_valid_uuid(s):
        return (
            f"{label} некоректний: «{s[:40]}…». "
            "Потрібен UUID у форматі 8-4-4-4-12 (36 символів, латиниця та цифри)."
        )
    return ""


def _up_num_float(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val).replace(",", ".").strip() or default)
    except Exception:
        return default


def _up_num_int(val, default=0):
    try:
        return int(round(_up_num_float(val, default)))
    except Exception:
        return default


def _up_section_title(text: str):
    st.markdown(
        f'<p class="up-section-title">{html.escape(text)}</p>',
        unsafe_allow_html=True,
    )


def _up_inject_form_css():
    st.markdown(
        """
<style>
.up-section-title {
  color: #0057b7;
  font-weight: 700;
  border-bottom: 3px solid #ffcc00;
  padding-bottom: 6px;
  margin: 18px 0 12px 0;
  font-size: 1.05rem;
}
.up-sender-box {
  background: #f7f7f7;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 8px;
  line-height: 1.5;
  font-size: 0.95rem;
}
.up-parcel-box {
  background: #f3f3f3;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 12px 14px 4px 14px;
  margin: 8px 0 12px 0;
}
.up-parcel-sub {
  color: #0057b7;
  font-weight: 600;
  margin: 0 0 10px 0;
}
div[data-testid="stHorizontalBlock"] .up-action-cancel button {
  background: #c0392b !important;
  color: #fff !important;
  border: none !important;
}
div[data-testid="stHorizontalBlock"] .up-action-calc button {
  background: #f1c40f !important;
  color: #222 !important;
  border: none !important;
}
div[data-testid="stHorizontalBlock"] .up-action-create button {
  background: #27ae60 !important;
  color: #fff !important;
  border: none !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _up_classifier_entries(data):
    if not isinstance(data, dict):
        return []
    entries = data.get("Entries") or data.get("entries") or {}
    if not isinstance(entries, dict):
        return []
    entry = entries.get("Entry") or entries.get("entry")
    if entry is None:
        return []
    if isinstance(entry, list):
        return [e for e in entry if isinstance(e, dict)]
    if isinstance(entry, dict):
        return [entry]
    return []


def _up_classifier_pick(entry: dict, *keys: str) -> str:
    for key in keys:
        val = entry.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in ("0", "null", "None"):
            return s
    return ""


def _up_classifier_bearer():
    load_secrets_to_config()
    for key in ("UP_CLASSIFIER_BEARER", "UP_BEARER_TOKEN"):
        val = _read_st_secret(key) or str(getattr(config, key, "") or "").strip()
        if val:
            return val
    return ""


def _up_classifier_xml_to_dict(raw: bytes):
    """Парсить XML-відповідь класифікатора (без Accept: application/json)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw)
    entries = []
    for entry_el in root.iter():
        tag = entry_el.tag.split("}")[-1] if "}" in entry_el.tag else entry_el.tag
        if tag != "Entry":
            continue
        row = {}
        for child in entry_el:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child.text:
                row[ctag] = child.text.strip()
        if row:
            entries.append(row)
    if not entries:
        return None
    return {"Entries": {"Entry": entries if len(entries) > 1 else entries[0]}}


def _up_classifier_fetch_json(path: str, params: dict, bearer: str):
    """GET класифікатора: спочатку urllib (стабільно на Streamlit Cloud), потім requests."""
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request

    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
        "User-Agent": "logistic-manager/1.0",
    }
    qs = urllib.parse.urlencode(params or {})
    last_err = ""

    for base in UP_CLASSIFIER_BASES:
        url = f"{base}{path}"
        full_url = f"{url}?{qs}" if qs else url
        try:
            req = urllib.request.Request(full_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=25, context=utils._ssl_context()) as resp:
                raw = resp.read()
                if resp.status != 200:
                    last_err = f"HTTP {resp.status} ({base})"
                    continue
                text = raw.decode("utf-8", errors="replace").lstrip()
                if text.startswith("<"):
                    parsed = _up_classifier_xml_to_dict(raw)
                    if parsed:
                        return parsed, ""
                try:
                    return _json.loads(text), ""
                except Exception:
                    parsed = _up_classifier_xml_to_dict(raw)
                    if parsed:
                        return parsed, ""
                    return {"raw": text[:800]}, ""
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                body = ""
            last_err = f"HTTP {e.code} ({base}): {body}"
        except Exception as e:
            last_err = f"{base}: {e}"

    try:
        url = f"{UP_CLASSIFIER_BASES[0]}{path}"
        r = utils.std_requests.get(url, headers=headers, params=params, timeout=25)
        if r is not None and r.status_code == 200:
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        if r is not None:
            last_err = f"requests HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        last_err = last_err or str(e)[:300]

    return None, last_err or "немає відповіді"


def up_classifier_get(endpoint: str, params: dict):
    """GET адресного класифікатора Укрпошти. Повертає (data|None, error)."""
    bearer = _up_classifier_bearer()
    if not bearer:
        return None, (
            "Немає UP_BEARER_TOKEN у Secrets (PRODUCTION BEARER eCom). "
            "Додай рядок UP_BEARER_TOKEN = \"…\" у Streamlit → Secrets і зроби Reboot app."
        )
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    data, err = _up_classifier_fetch_json(path, params, bearer)
    if data is None:
        hint = f" ({err})" if err else ""
        return None, f"Немає відповіді від класифікатора адрес.{hint}"
    return data, ""


def _up_parse_classifier_entry(e: dict, pc: str):
    region = _up_classifier_pick(e, "REGION_UA", "REGION_NAME", "region_ua", "region_name")
    district = _up_classifier_pick(
        e,
        "DISTRICT_UA",
        "DISTRICT_NAME",
        "NEW_DISTRICT_UA",
        "NEW_DISTRICT_NAME",
        "district_ua",
    )
    city = _up_classifier_pick(e, "CITY_UA", "CITY_NAME", "city_ua", "CITYNAME_UA")
    citytype = _up_classifier_pick(e, "CITYTYPE_UA", "CITYTYPE_NAME", "SHORTCITYTYPE_UA")
    if citytype and city and not str(city).lower().startswith(str(citytype).lower()):
        city = f"{citytype} {city}".strip()
    elif not city:
        city = " ".join(
            p
            for p in (
                citytype,
                _up_classifier_pick(e, "CITYNAME_UA"),
            )
            if p
        ).strip()
    if region or district or city:
        return {"region": region, "district": district, "city": city, "postcode": pc}
    return None


def _up_postcode_candidates(raw: str) -> list[str]:
    """Варіанти індексу (провідний 0 часто губиться в маркетплейсах: 83371 → 08371)."""
    d = re.sub(r"\D", "", str(raw or ""))
    out: list[str] = []

    def _add(pc: str) -> None:
        pc = pc[:5]
        if len(pc) == 5 and pc not in out:
            out.append(pc)

    if len(d) >= 5:
        _add(d[:5])
    if len(d) == 4:
        _add("0" + d)
    if len(d) >= 5:
        pc = d[:5]
        if pc.startswith("83"):
            _add("08" + pc[2:])
        if pc[0] in "789":
            _add("0" + pc[1:])
    return out


def up_resolve_postcode_for_up(raw: str) -> tuple[str, dict | None, str]:
    """
    Індекс, знайдений класифікатором УП. Повертає (postcode, {region,district,city}, err).
    """
    tried: list[str] = []
    last_err = ""
    for pc in _up_postcode_candidates(raw):
        tried.append(pc)
        loc, err = up_lookup_by_postcode(pc)
        if loc:
            return pc, loc, ""
        last_err = err or last_err
    raw_s = re.sub(r"\D", "", str(raw or ""))[:5]
    msg = (
        f"Укрпошта не знає індекс «{raw_s or raw}»"
        + (f" (перевірено: {', '.join(tried)})" if tried else "")
        + ". Перевірте індекс у замовленні (часто 0 на початку, напр. 08371)."
    )
    if last_err and last_err not in msg:
        msg = f"{msg} ({last_err})"
    return "", None, msg


def up_lookup_by_postcode(postcode: str):
    """Область / район / населений пункт за індексом (режим «Знаю індекс»)."""
    pc = re.sub(r"\D", "", str(postcode or ""))[:5]
    if len(pc) != 5:
        return None, "Індекс має містити 5 цифр."
    last_err = ""
    params = {"postcode": pc, "lang": "UA"}
    for endpoint in ("/get_city_details_by_postcode", "/get_address_by_postcode"):
        data, err = up_classifier_get(endpoint, params)
        if err:
            last_err = err
            continue
        for e in _up_classifier_entries(data):
            parsed = _up_parse_classifier_entry(e, pc)
            if parsed:
                return parsed, ""

    data, err = up_classifier_get("/get_postoffices_by_postindex", {"pi": pc})
    if not err:
        for e in _up_classifier_entries(data):
            parsed = _up_parse_classifier_entry(e, pc)
            if parsed:
                return parsed, ""
        if last_err:
            last_err = f"{last_err} (відділення за індексом теж без адреси)"
    elif not last_err:
        last_err = err

    if last_err:
        return None, last_err
    return None, f"За індексом {pc} нічого не знайдено."


def _up_postcode_on_change():
    """Після вводу/вставки індексу — одразу підтягнути область, район, місто."""
    _up_on_postcode_lookup(force=True)


def _up_postcode_lookup_click():
    _up_on_postcode_lookup(force=True)


def _up_on_postcode_lookup(force: bool = False):
    """Callback: підтягнути область/район/місто за індексом."""
    if st.session_state.get("upwiz_index_mode") != "Знаю індекс":
        return
    pc = re.sub(r"\D", "", str(st.session_state.get("upwiz_postcode", "")).strip())[:5]
    if len(pc) != 5:
        st.session_state.upwiz_lookup_error = "Введи 5 цифр індексу."
        st.session_state.upwiz_postcode_lookup_ok = False
        return
    if not force and st.session_state.get("upwiz_postcode_lookup_last") == pc:
        return
    result, err = up_lookup_by_postcode(pc)
    st.session_state.upwiz_postcode_lookup_last = pc
    if err:
        st.session_state.upwiz_lookup_error = err
        st.session_state.upwiz_postcode_lookup_ok = False
        return
    st.session_state.upwiz_lookup_error = ""
    st.session_state.upwiz_postcode_lookup_ok = True
    # Не змінюємо upwiz_postcode — це key віджета; лише область/район/місто (віджети нижче).
    st.session_state.upwiz_region = result.get("region", "")
    st.session_state.upwiz_district = result.get("district", "")
    st.session_state.upwiz_city = result.get("city", "")


def up_ecom_request(method: str, path: str, body=None, token_required=True):
    """Універсальний запит до eCom API. Повертає (data|None, error)."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if token_required and not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets (PROD token eCom)."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN у Secrets."
    if not str(getattr(config, "UP_UUID", "") or "").strip():
        return None, "Немає UP_UUID у Secrets (обовʼязковий для eCom API)."
    url = f"{UP_ECOM_BASE}{path}"
    params = {"token": ecom_token} if token_required else None
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token or None,
        include_content_type=True,
    )
    try:
        timeout = (
            60
            if method.upper() in ("POST", "PUT") and "/shipments" in path
            else 30
        )
        r = utils.make_request(
            method, url, headers=headers, params=params, json=body, timeout=timeout
        )
        if not r:
            hint = utils.get_last_request_error()
            msg = "Немає відповіді від сервера Укрпошти (eCom)."
            if hint:
                msg += f" ({hint})"
            return None, msg
        if r.status_code in (200, 201, 204):
            if method.upper() == "DELETE" or not (r.text or "").strip():
                return {}, ""
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        try:
            err_js = r.json()
        except Exception:
            err_js = {"text": r.text[:800]}
        return None, _up_format_ecom_error(f"HTTP {r.status_code}: {err_js}")
    except Exception as e:
        return None, str(e)[:500]


def up_post_address_from_form():
    """POST /addresses — адреса отримувача з полів форми."""
    raw_pc = str(st.session_state.get("upwiz_postcode", "")).strip()
    region = str(st.session_state.get("upwiz_region", "")).strip()
    district = str(st.session_state.get("upwiz_district", "")).strip()
    city = str(st.session_state.get("upwiz_city", "")).strip()
    if st.session_state.get("upwiz_index_mode") == "Знаю індекс":
        street = house = apartment = ""
    else:
        street = str(st.session_state.get("upwiz_street", "")).strip()
        house = str(st.session_state.get("upwiz_house", "")).strip()
        apartment = str(st.session_state.get("upwiz_apartment", "")).strip()
    if not raw_pc:
        return None, "Заповни індекс."
    resolved_pc, loc, pc_err = up_resolve_postcode_for_up(raw_pc)
    if pc_err:
        return None, pc_err
    postcode = resolved_pc
    if loc:
        region = str(loc.get("region") or region or "").strip()
        district = str(loc.get("district") or district or "").strip()
        city = str(loc.get("city") or city or "").strip()
    if not region or not city:
        return None, "Заповни область і населений пункт (або коректний індекс)."
    body = {
        "country": "UA",
        "postcode": postcode,
        "region": region[:45],
        "city": city[:45],
    }
    if district:
        body["district"] = district[:45]
    if street:
        body["street"] = street[:255]
    if house:
        body["houseNumber"] = house[:15]
    if apartment:
        body["apartmentNumber"] = apartment[:15]
    # foreignStreetHouseApartment — лише для країн ≠ UA; для України API UPE01002 забороняє це поле.
    if not street and not house:
        desc = str(st.session_state.get("upwiz_address_note", "") or "").strip()
        if desc:
            body["description"] = desc[:255]
    data, err = up_ecom_request("POST", "/addresses", body, token_required=False)
    if err:
        return None, f"Адреса отримувача: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу не створено: {data}"
    return addr_id, ""


def up_post_client_from_form(address_id):
    """POST /clients — фізособа-отримувач."""
    last = str(st.session_state.get("upwiz_lastname", "")).strip()
    first = str(st.session_state.get("upwiz_firstname", "")).strip()
    middle = str(st.session_state.get("upwiz_middlename", "")).strip()
    phone = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
    if not last or not first:
        return None, "Заповни прізвище та імʼя отримувача."
    if not phone or len(phone) < 10:
        return None, "Заповни коректний телефон отримувача."
    body = {
        "type": "INDIVIDUAL",
        "lastName": last,
        "firstName": first,
        "phoneNumber": phone if phone.startswith("+") else f"+{phone}",
        "addressId": str(address_id),
    }
    if middle:
        body["middleName"] = middle
    data, err = up_ecom_request("POST", "/clients", body)
    if err:
        return None, f"Клієнт отримувача: {err}"
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if not uuid:
        return None, f"Клієнта не створено: {data}"
    return str(uuid).strip(), ""


def _up_get_recipient_uuid() -> str:
    """UUID отримувача: вручну з поля або збережений після створення через API."""
    manual = str(st.session_state.get("upwiz_recipient_uuid_manual", "")).strip()
    if not manual:
        manual = str(st.session_state.get("upwiz_recipient_uuid", "")).strip()
    if manual:
        return manual
    return str(st.session_state.get("upwiz_recipient_uuid_created", "")).strip()


def up_create_sender_client_from_secrets():
    """Створити клієнта-відправника в eCom за даними з Secrets."""
    load_secrets_to_config()
    name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip()
    if not name:
        return None, "Додай UP_SENDER_NAME у Secrets (ПІБ або «ФОП Прізвище Імʼя»)."
    phone = utils.clean_phone(str(getattr(config, "UP_SENDER_PHONE", "") or "").strip())
    if not phone or len(phone) < 10:
        return None, "Додай UP_SENDER_PHONE у Secrets (телефон відправника, 380…)."
    postcode = re.sub(
        r"\D",
        "",
        str(
            getattr(config, "UP_SENDER_BRANCH_INDEX", "")
            or getattr(config, "UP_SENDER_POSTCODE", "")
            or ""
        ),
    )[:5]
    if len(postcode) != 5:
        return None, "Вкажи UP_SENDER_BRANCH_INDEX або UP_SENDER_POSTCODE (5 цифр) у Secrets."

    loc, loc_err = up_lookup_by_postcode(postcode)
    if not loc:
        return None, f"Індекс відправника {postcode}: {loc_err or 'не знайдено в класифікаторі'}."

    body_addr = {
        "country": "UA",
        "postcode": postcode,
        "region": str(loc.get("region", ""))[:45],
        "city": str(loc.get("city", ""))[:45],
    }
    if loc.get("district"):
        body_addr["district"] = str(loc.get("district", ""))[:45]
    addr_text = str(getattr(config, "UP_SENDER_ADDRESS", "") or "").strip()
    if addr_text:
        body_addr["street"] = addr_text[:255]
    else:
        body_addr["street"] = "вул."

    data, err = up_ecom_request("POST", "/addresses", body_addr, token_required=False)
    if err:
        return None, f"Адреса відправника: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу відправника не створено: {data}"

    phone_fmt = phone if phone.startswith("+") else f"+{phone}"

    if _up_expect_fop_sender():
        tin = re.sub(r"\D", "", str(getattr(config, "UP_SENDER_TIN", "") or ""))[:10]
        if len(tin) != 10:
            return None, (
                "Для відправника **ФОП** додай **UP_SENDER_TIN** (ІПН, 10 цифр) у Secrets. "
                "Або вкажи UP_SENDER_TYPE = INDIVIDUAL, якщо це фізособа без ФОП."
            )
        display_name = name if re.match(r"(?i)^фоп", name) else f"ФОП {name}"
        body_client = {
            "type": "PRIVATE_ENTREPRENEUR",
            "name": display_name[:60],
            "phoneNumber": phone_fmt,
            "addressId": str(addr_id),
            "tin": tin,
        }
        bank = str(getattr(config, "UP_SENDER_BANK_ACCOUNT", "") or "").strip()
        if bank:
            body_client["bankAccount"] = bank[:34]
    else:
        clean_name = re.sub(r"(?i)^фоп\s+", "", name).strip()
        parts = clean_name.split()
        if len(parts) >= 2:
            last, first = parts[0], parts[1]
            middle = " ".join(parts[2:]) if len(parts) > 2 else ""
        else:
            last, first, middle = clean_name, clean_name, ""
        body_client = {
            "type": "INDIVIDUAL",
            "lastName": last[:250],
            "firstName": first[:250],
            "phoneNumber": phone_fmt,
            "addressId": str(addr_id),
        }
        if middle:
            body_client["middleName"] = middle[:250]

    data, err = up_ecom_request("POST", "/clients", body_client)
    if err:
        return None, f"Клієнт-відправник: {err}"
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if not uuid:
        return None, f"Відправника не створено: {data}"
    return str(uuid).strip(), ""


def _up_ensure_sender_uuid():
    """UUID відправника: з Secrets, кешу або автостворення; verify раз за сесію."""
    load_secrets_to_config()
    cached = str(st.session_state.get("upwiz_sender_uuid_created", "")).strip()
    if cached:
        if st.session_state.get(f"_up_sender_verified::{cached}"):
            return cached, ""
        if not _up_verify_sender_uuid(cached):
            st.session_state[f"_up_sender_verified::{cached}"] = True
            return cached, ""

    configured = str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
    if configured:
        if st.session_state.get(f"_up_sender_verified::{configured}"):
            return configured, ""
        err = _up_verify_sender_uuid(configured)
        if not err:
            st.session_state[f"_up_sender_verified::{configured}"] = True
            return configured, ""
        uid, cerr = up_create_sender_client_from_secrets()
        if uid:
            st.session_state.upwiz_sender_uuid_created = uid
            st.session_state[f"_up_sender_verified::{uid}"] = True
            return uid, ""
        return None, f"{err}\n\nАвтостворення: {cerr}"

    uid, cerr = up_create_sender_client_from_secrets()
    if cerr:
        return None, cerr
    st.session_state.upwiz_sender_uuid_created = uid
    st.session_state[f"_up_sender_verified::{uid}"] = True
    return uid, ""


def _up_ensure_recipient_uuid():
    """UUID отримувача: з поля або створення через API."""
    uid = _up_get_recipient_uuid()
    if uid:
        return uid, ""
    addr_id, err = up_post_address_from_form()
    if err:
        return None, err
    uid, err = up_post_client_from_form(addr_id)
    if err:
        return None, err
    # Не писати в upwiz_recipient_uuid — це key text_input; лише окремий ключ.
    st.session_state.upwiz_recipient_uuid_created = uid
    return uid, ""


def _upwiz_parcel_count() -> int:
    try:
        return max(1, int(st.session_state.get("upwiz_n_parcels", 1) or 1))
    except Exception:
        return 1


def _upwiz_parcel_key(idx: int, field: str) -> str:
    return f"upwiz_{field}_{idx}"


def _upwiz_clear_parcel_widget_keys():
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("upwiz_") and any(
            key.startswith(f"upwiz_{f}_") for f in ("w", "len", "wid", "h", "decl")
        ):
            del st.session_state[key]


def _upwiz_parcels_from_form() -> list:
    """Список parcels для API з полів форми (кілька місць)."""
    out = []
    for i in range(_upwiz_parcel_count()):
        w, ln, wid, hgt = _up_normalize_parcel_dims(
            st.session_state.get(_upwiz_parcel_key(i, "w")),
            st.session_state.get(_upwiz_parcel_key(i, "len")),
            st.session_state.get(_upwiz_parcel_key(i, "wid")),
            st.session_state.get(_upwiz_parcel_key(i, "h")),
        )
        parcel = {"weight": w, "length": ln, "width": wid, "height": hgt}
        declared = _up_num_float(st.session_state.get(_upwiz_parcel_key(i, "decl")))
        if declared > 0:
            parcel["declaredPrice"] = declared
        out.append(parcel)
    return out


def _render_upwiz_parcels_section():
    """Місця відправлення: порожні поля за замовчуванням, можна додати кілька."""
    if "upwiz_n_parcels" not in st.session_state:
        st.session_state.upwiz_n_parcels = 1

    n = _upwiz_parcel_count()
    for i in range(n):
        st.markdown(
            f'<div class="up-parcel-box"><p class="up-parcel-sub">Інформація про місце №{i + 1}</p></div>',
            unsafe_allow_html=True,
        )
        p1, p2 = st.columns(2)
        with p1:
            st.number_input(
                "Вага, г: *",
                min_value=1,
                max_value=30000,
                value=None,
                step=50,
                key=_upwiz_parcel_key(i, "w"),
            )
            st.number_input(
                "Ширина, см: *",
                min_value=0,
                max_value=200,
                value=None,
                step=1,
                key=_upwiz_parcel_key(i, "wid"),
            )
            st.number_input(
                "Оголошена цінність, грн",
                min_value=0.0,
                value=None,
                step=1.0,
                key=_upwiz_parcel_key(i, "decl"),
            )
        with p2:
            st.number_input(
                "Найбільша сторона (довжина), см: *",
                min_value=1,
                max_value=200,
                value=None,
                step=1,
                key=_upwiz_parcel_key(i, "len"),
            )
            st.number_input(
                "Висота, см: *",
                min_value=0,
                max_value=200,
                value=None,
                step=1,
                key=_upwiz_parcel_key(i, "h"),
            )
    add_c, rm_c = st.columns([1, 1])
    with add_c:
        if st.button("➕ Додати місце", key="upwiz_add_parcel", use_container_width=True):
            st.session_state.upwiz_n_parcels = n + 1
            st.rerun()
    with rm_c:
        if n > 1 and st.button("➖ Прибрати останнє", key="upwiz_rm_last_parcel", use_container_width=True):
            idx = n - 1
            for field in ("w", "len", "wid", "h", "decl"):
                st.session_state.pop(_upwiz_parcel_key(idx, field), None)
            st.session_state.upwiz_n_parcels = n - 1
            st.rerun()

    st.number_input(
        "Післяплата, грн",
        min_value=0.0,
        value=None,
        step=1.0,
        key="upwiz_postpay_uah",
    )


def _up_clear_wizard_edit_state() -> None:
    """Скинути режим редагування (нова ТТН після редагування)."""
    st.session_state.upwiz_edit_mode = False
    st.session_state.upwiz_edit_seeded_uuid = ""
    for k in (
        "upwiz_edit_shipment_uuid",
        "upwiz_edit_barcode",
        "upwiz_edit_parcel_uuid",
        "upwiz_edit_recipient_uuid",
    ):
        st.session_state.pop(k, None)


def up_create_shipment_from_wizard_state() -> tuple[dict | None, str]:
    """Створити ТТН УП за поточними upwiz_* (після apply_up_wizard_prefill)."""
    load_secrets_to_config()
    desc_saved = str(st.session_state.get("upwiz_description_stored", "") or "").strip()[
        :_UP_SHIPMENT_DESC_MAX
    ]
    v_err = _up_validate_wizard_form()
    if v_err:
        hint = ""
        pf = st.session_state.get("rozetka_last_prefill")
        if isinstance(pf, dict) and len(_up_wizard_postcode_normalized()) != 5:
            pn = str(pf.get("place_number") or "").strip()
            city = str(pf.get("city") or "").strip()
            hint = f" У замовленні: місто «{city or '—'}», відділення «{pn or '—'}»."
        return None, f"{v_err}{hint}"
    sid, s_err = _up_ensure_sender_uuid()
    if s_err:
        return None, s_err
    rid, r_err = _up_ensure_recipient_uuid()
    if r_err:
        return None, r_err
    body, b_err = _up_build_shipment_dict_from_wizard(rid, sender_uuid=sid)
    if b_err:
        return None, b_err
    data, err = up_post_shipment_create(body)
    if err:
        return None, f"Створення ТТН: {err}"
    suuid_new = _up_shipment_uuid_from_response(data) if isinstance(data, dict) else ""
    st.session_state.up_last_create_response = data
    response_for_journal = data
    if isinstance(data, dict) and desc_saved:
        response_for_journal = dict(data)
        response_for_journal["description"] = desc_saved
    bc_new = _up_barcode_from_create_response(data) if isinstance(data, dict) else ""
    if bc_new:
        st.session_state.up_journal_active_bc = bc_new
        _up_journal_set_desc_cache(bc_new, desc_saved)
        _up_clear_sticker_pdf_cache(bc_new)
    _rz_oid = st.session_state.get("rozetka_linked_order_id")
    if _rz_oid is not None:
        rozetka_api.clear_up_journal_draft(_rz_oid)
    _cached_up_shipments_df.clear()
    st.session_state.up_journal_selected_day = utils.today_kyiv()

    def _bg_post_create():
        """Уточнення parcel.description у УП і запис у журнал Google — не блокують UI."""
        try:
            if suuid_new and desc_saved:
                _up_clear_parcel_descriptions_on_shipment(suuid_new, data)
        except Exception:
            pass
        try:
            up_journal_save_response(
                response_for_journal,
                description_override=desc_saved,
            )
        except Exception:
            pass

    threading.Thread(target=_bg_post_create, daemon=True).start()

    return response_for_journal if isinstance(response_for_journal, dict) else {}, ""


def _up_wizard_postcode_normalized() -> str:
    return re.sub(r"\D", "", str(st.session_state.get("upwiz_postcode", "")).strip())[:5]


def execute_rozetka_up_create(prefill: dict) -> dict:
    """
    Створити ТТН УП за замовленням Rozetka (виклик з вкладки Rozetka).
    Повертає {ok, err, bc, oid}.
    """
    oid = prefill.get("rozetka_order_id")
    if not rozetka_api.is_ukrposhta_prefill(prefill):
        svc = str(prefill.get("delivery_service") or "невідома служба").strip()
        return {
            "ok": False,
            "err": f"Замовлення #{oid}: доставка «{svc}» — не Укрпошта. Створіть ТТН у кабінеті цієї служби.",
            "bc": "",
            "oid": oid,
        }
    load_secrets_to_config()
    rozetka_api.apply_up_wizard_prefill(prefill, register_draft=False)
    pc = _up_wizard_postcode_normalized()
    if len(pc) != 5:
        pc = rozetka_api.normalize_postcode(prefill.get("postcode"))
        if pc:
            st.session_state.upwiz_postcode = pc
    if not _up_classifier_bearer():
        rozetka_api.register_up_journal_draft(prefill)
        st.session_state.upwiz_form_open = True
        return {
            "ok": False,
            "err": "Немає UP_BEARER_TOKEN у Secrets (перевірте після Save → Reboot app).",
            "bc": "",
            "oid": oid,
        }
    lookup_err = _up_enrich_wizard_address_from_postcode()
    if lookup_err:
        rozetka_api.register_up_journal_draft(prefill)
        st.session_state.upwiz_form_open = True
        return {"ok": False, "err": f"Індекс: {lookup_err}", "bc": "", "oid": oid}
    data, cerr = up_create_shipment_from_wizard_state()
    if cerr:
        rozetka_api.register_up_journal_draft(prefill)
        st.session_state.upwiz_form_open = True
        return {"ok": False, "err": cerr, "bc": "", "oid": oid}
    bc = _up_format_bc_display(_up_barcode_from_create_response(data))
    if not bc:
        return {
            "ok": False,
            "err": "УП прийняла запит, але в відповіді немає ШКІ — перевірте кабінет ok.ukrposhta.",
            "bc": "",
            "oid": oid,
        }
    st.session_state.upwiz_form_open = False
    _up_clear_wizard_edit_state()
    return {"ok": True, "err": "", "bc": bc, "oid": oid}


def _flush_rozetka_pending_up_create() -> None:
    """Створення ТТН УП до рендеру віджетів upwiz_* (інакше Streamlit блокує session_state)."""
    pending = st.session_state.pop("rozetka_pending_create", None)
    if not isinstance(pending, dict) or not pending:
        return
    result = execute_rozetka_up_create(pending)
    st.session_state.rozetka_last_up_result = result
    ttn_key = st.session_state.pop("rozetka_pending_ttn_key", None)
    if result.get("ok") and result.get("bc"):
        bc = str(result["bc"])
        if ttn_key:
            st.session_state[ttn_key] = bc
        st.session_state.pop("rozetka_orders_cache", None)
        st.toast(f"УП: {bc}", icon="✅")
    elif result.get("err"):
        st.toast(str(result["err"])[:120], icon="⚠️")


def _up_enrich_wizard_address_from_postcode() -> str:
    """Підтягнути область/місто за індексом (для автостворення з Rozetka)."""
    raw_pc = str(st.session_state.get("upwiz_postcode", "")).strip()
    if not raw_pc:
        return "У замовленні немає індексу — заповніть вручну на вкладці УП ТТН."
    resolved_pc, loc, err = up_resolve_postcode_for_up(raw_pc)
    if err:
        return err
    st.session_state.upwiz_postcode = resolved_pc
    if loc:
        st.session_state.upwiz_region = str(loc.get("region") or "")
        st.session_state.upwiz_district = str(loc.get("district") or "")
        st.session_state.upwiz_city = str(loc.get("city") or "")
    st.session_state.upwiz_postcode_lookup_ok = True
    st.session_state.upwiz_postcode_lookup_last = resolved_pc
    return ""


def _up_validate_wizard_form():
    """Перевірка обовʼязкових полів форми."""
    missing = []
    if not str(st.session_state.get("upwiz_lastname", "")).strip():
        missing.append("прізвище")
    if not str(st.session_state.get("upwiz_firstname", "")).strip():
        missing.append("імʼя")
    if not utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip()):
        missing.append("телефон")
    if len(_up_wizard_postcode_normalized()) != 5:
        missing.append("індекс (5 цифр)")
    if not str(st.session_state.get("upwiz_region", "")).strip():
        missing.append("область")
    if not str(st.session_state.get("upwiz_city", "")).strip():
        missing.append("населений пункт")
    for i in range(_upwiz_parcel_count()):
        if _up_num_int(st.session_state.get(_upwiz_parcel_key(i, "w"))) < 1:
            missing.append(f"вага місця {i + 1}")
        if _up_num_int(st.session_state.get(_upwiz_parcel_key(i, "len"))) < 1:
            missing.append(f"довжина місця {i + 1}")
    if missing:
        return f"Заповни обовʼязкові поля: {', '.join(missing)}."
    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    if postpay >= 1 and not str(st.session_state.get("upwiz_middlename", "")).strip():
        return "Для післяплати потрібне по батькові отримувача."
    return ""


def _up_build_shipment_dict_from_wizard(recipient_uuid=None, sender_uuid=None):
    """Збір тіла POST /shipments з полів форми (кабінет ok.ukrposhta)."""
    sender = (
        sender_uuid
        or str(st.session_state.get("upwiz_sender_uuid_created", "")).strip()
        or str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
    )
    recipient = recipient_uuid or _up_get_recipient_uuid()
    err = _up_uuid_error(sender, "UUID відправника")
    if err:
        return None, err
    err = _up_uuid_error(recipient, "UUID отримувача")
    if err:
        return None, err

    service_label = st.session_state.get("upwiz_service", "Базовий")
    ship_type = _UP_SERVICE_API.get(service_label, "STANDARD")
    delivery_label = st.session_state.get("upwiz_delivery_label", "склад – двері")
    delivery = _UP_DELIVERY_LABELS.get(delivery_label, "W2D")

    parcels = _upwiz_parcels_from_form()

    fail_main = st.session_state.get("upwiz_fail_main", "повернути")
    on_fail = "PROCESS_AS_REFUSAL" if fail_main == "не повертати" else "RETURN"

    body = {
        "type": ship_type,
        "sender": {"uuid": sender},
        "recipient": {"uuid": recipient},
        "deliveryType": delivery,
        "paidByRecipient": bool(st.session_state.get("upwiz_paid_shipment_recipient", False)),
        "postPayPaidByRecipient": bool(st.session_state.get("upwiz_paid_postpay_recipient", True)),
        "onFailReceiveType": on_fail,
        "nonCashPayment": False,
        "parcels": parcels,
        "sms": bool(st.session_state.get("upwiz_sms", False)),
        "checkOnDelivery": bool(st.session_state.get("upwiz_check_delivery", True)),
    }

    sender_addr = str(getattr(config, "UP_SENDER_ADDRESS_ID", "") or "").strip()
    if sender_addr:
        try:
            body["senderAddressId"] = int(sender_addr)
        except ValueError:
            body["senderAddressId"] = sender_addr

    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    if postpay >= 1:
        body["postPay"] = postpay
    if st.session_state.get("upwiz_transfer_postpay_iban"):
        body["transferPostpayToBankAccount"] = True

    desc = _up_wizard_description()
    if desc:
        body["description"] = desc

    phone = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
    if phone:
        body["recipientPhone"] = phone if phone.startswith("+") else f"+{phone}"

    return body, ""


def _up_reset_wizard_form():
    keep = {
        "upwiz_service",
        "upwiz_sender_uuid",
        "upwiz_delivery_label",
        "upwiz_paid_shipment_recipient",
        "upwiz_paid_postpay_recipient",
        "upwiz_fail_main",
        "upwiz_fail_return_service",
        "upwiz_check_delivery",
        "upwiz_form_open",
    }
    _upwiz_clear_parcel_widget_keys()
    if "upwiz_n_parcels" in st.session_state:
        del st.session_state["upwiz_n_parcels"]
    for key in list(st.session_state.keys()):
        if key.startswith("upwiz_") and key not in keep:
            del st.session_state[key]
    _up_clear_wizard_edit_state()


def render_up_shipments_tab():
    """Оформлення ТТН Укрпошти — макет як у кабінеті ok.ukrposhta."""
    import json as _json

    load_secrets_to_config()
    last_rz = st.session_state.pop("rozetka_last_up_result", None)
    if isinstance(last_rz, dict) and last_rz.get("ok") and last_rz.get("bc"):
        st.success(
            f"ТТН **{last_rz['bc']}** у журналі"
            + (
                f" (Rozetka #{last_rz.get('oid')})."
                if last_rz.get("oid")
                else "."
            )
        )
    elif isinstance(last_rz, dict) and last_rz.get("err"):
        st.error(f"Rozetka → УП: {last_rz['err']}")
    prefill = st.session_state.pop("rozetka_up_prefill", None)
    if isinstance(prefill, dict) and prefill:
        rozetka_api.apply_up_wizard_prefill(prefill, register_draft=True)
        st.info("Форму заповнено з Rozetka — перевірте поля та натисніть **Створити**.")
    _up_inject_form_css()
    _up_process_pending_wizard_edit()

    if "upwiz_sender_uuid" not in st.session_state:
        st.session_state.upwiz_sender_uuid = str(getattr(config, "UP_SENDER_UUID", "") or "")
    if "upwiz_service" not in st.session_state:
        st.session_state.upwiz_service = "Базовий"
    if "upwiz_delivery_label" not in st.session_state:
        st.session_state.upwiz_delivery_label = "склад – двері"
    if "upwiz_check_delivery" not in st.session_state:
        st.session_state.upwiz_check_delivery = True
    if "upwiz_fail_main" not in st.session_state:
        st.session_state.upwiz_fail_main = "повернути"
    if "upwiz_fail_return_service" not in st.session_state:
        st.session_state.upwiz_fail_return_service = "Базовий"
    if "upwiz_phone" not in st.session_state:
        st.session_state.upwiz_phone = "+38"
    if "upwiz_index_mode" not in st.session_state:
        st.session_state.upwiz_index_mode = "Знаю індекс"

    st.markdown(
        '<div class="up-section-title" style="border-bottom-width:3px;font-size:1.15rem;">'
        "Укрпошта · ТТН"
        "</div>",
        unsafe_allow_html=True,
    )

    top_tariff, top_create = st.columns([3, 1])
    with top_tariff:
        st.radio(
            "Тариф",
            ["Базовий", "Пріоритетний"],
            horizontal=True,
            key="upwiz_service",
            label_visibility="collapsed",
        )
    with top_create:
        if not st.session_state.get("upwiz_form_open"):
            if st.button("Створити", type="primary", key="upwiz_show_form_btn", use_container_width=True):
                st.session_state.upwiz_form_open = True
                _up_clear_wizard_edit_state()
                st.session_state.pop("upwiz_desc_widget", None)
                _up_set_wizard_description("")
                _upwiz_clear_parcel_widget_keys()
                for old_key in (
                    "upwiz_weight_g",
                    "upwiz_length_cm",
                    "upwiz_width_cm",
                    "upwiz_height_cm",
                    "upwiz_declared_uah",
                ):
                    st.session_state.pop(old_key, None)
                st.session_state.upwiz_n_parcels = 1
                st.rerun()

    if not _up_classifier_bearer():
        st.error(
            "У Secrets не зчитується **UP_BEARER_TOKEN** (додаток бачить лише те, що збережено після **Save**). "
            "Перевір TOML: кожен UUID в один рядок → Save → **Reboot app**."
        )

    _render_up_shipments_journal()

    if st.session_state.get("upwiz_form_open"):
        if st.session_state.get("upwiz_edit_mode"):
            bc_ed = _up_format_bc_display(st.session_state.get("upwiz_edit_barcode", ""))
            st.markdown(f"### Редагування ТТН `{bc_ed}`")
            st.caption("Ті самі поля, що при створенні. Збереження — кнопкою **Зберегти** внизу.")
        else:
            st.markdown("### Нова ТТН")
        sender_name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip() or "Відправник (UP_SENDER_NAME у Secrets)"
        sender_addr = str(getattr(config, "UP_SENDER_ADDRESS", "") or "").strip()
        branch_idx = str(
            getattr(config, "UP_SENDER_BRANCH_INDEX", "") or getattr(config, "UP_SENDER_POSTCODE", "") or ""
        ).strip()

        _up_section_title("Відправник:")
        fop_hint = "ФОП (PRIVATE_ENTREPRENEUR)" if _up_expect_fop_sender() else "фізична особа (INDIVIDUAL)"
        st.markdown(
            f'<div class="up-sender-box"><strong>{html.escape(sender_name)}</strong>'
            + (f"<br/>{html.escape(sender_addr)}" if sender_addr else "")
            + f"<br/><span style='opacity:0.85;font-size:0.9em'>Тип у API: {html.escape(fop_hint)}</span>"
            + "</div>",
            unsafe_allow_html=True,
        )
        if branch_idx and "upwiz_branch_index" not in st.session_state:
            st.session_state.upwiz_branch_index = branch_idx
        st.text_input(
            "Індекс відділення подачі відправлення:",
            disabled=bool(branch_idx),
            key="upwiz_branch_index",
            placeholder="78301",
        )

        _up_section_title("Одержувач:")
        st.radio(
            "Тип одержувача",
            ["Фізична особа", "Юридична особа"],
            horizontal=True,
            key="upwiz_recipient_kind",
            label_visibility="collapsed",
        )
        if st.session_state.get("upwiz_recipient_kind") == "Юридична особа":
            st.warning("Юридична особа через API потребує ЄДРПОУ — поки використовуй фізособу або UUID у «Розширено».")

        r1, r2 = st.columns(2)
        with r1:
            st.text_input("Прізвище: *", key="upwiz_lastname", placeholder="Прізвище")
        with r2:
            st.text_input("Імʼя: *", key="upwiz_firstname", placeholder="Імʼя")
        r3, r4 = st.columns(2)
        with r3:
            st.text_input(
                "По-батькові (обовʼязкове, якщо є післяплата):",
                key="upwiz_middlename",
                placeholder="По-батькові",
            )
        with r4:
            st.text_input(
                "Телефон: *",
                key="upwiz_phone",
                placeholder="+380XXXXXXXXX",
                on_change=_up_on_phone_input_change,
                args=("upwiz_phone",),
            )

        _up_section_title("Спосіб відправки:")
        st.selectbox(
            "Спосіб відправки",
            list(_UP_DELIVERY_LABELS.keys()),
            key="upwiz_delivery_label",
            label_visibility="collapsed",
        )

        _up_section_title("Адреса одержувача")
        st.radio(
            "Режим адреси",
            ["Знаю індекс", "Знайти індекс"],
            horizontal=True,
            key="upwiz_index_mode",
            label_visibility="collapsed",
        )
        know_index = st.session_state.get("upwiz_index_mode") == "Знаю індекс"
        if not know_index and st.session_state.get("upwiz_postcode_lookup_last"):
            st.session_state.upwiz_postcode_lookup_last = ""
            st.session_state.upwiz_postcode_lookup_ok = False
            st.session_state.upwiz_lookup_error = ""

        if know_index:
            st.text_input(
                "Індекс: *",
                key="upwiz_postcode",
                placeholder="Індекс (5 цифр)",
                max_chars=5,
                on_change=_up_postcode_on_change,
            )
            pc = re.sub(r"\D", "", str(st.session_state.get("upwiz_postcode", "")).strip())[:5]
            if len(pc) == 5:
                _up_on_postcode_lookup(force=False)
            lookup_err = str(st.session_state.get("upwiz_lookup_error", "")).strip()
            if lookup_err:
                st.warning(lookup_err)
            elif st.session_state.get("upwiz_postcode_lookup_ok"):
                st.caption("Область, район і населений пункт заповнено за індексом Укрпошти.")
            elif len(pc) < 5 and pc:
                st.caption("Введіть 5 цифр — адреса підставиться автоматично.")
            loc1, loc2, loc3 = st.columns(3)
            with loc1:
                st.text_input("Область *", key="upwiz_region", placeholder="Область")
            with loc2:
                st.text_input("Район", key="upwiz_district", placeholder="Район")
            with loc3:
                st.text_input("Місто *", key="upwiz_city", placeholder="Населений пункт")
        else:
            a1, a2 = st.columns(2)
            with a1:
                st.text_input("Індекс: *", key="upwiz_postcode", placeholder="Індекс", max_chars=5)
                st.text_input("Район:", key="upwiz_district", placeholder="Район")
            with a2:
                st.text_input("Область: *", key="upwiz_region", placeholder="Область")
                st.text_input("Населений пункт: *", key="upwiz_city", placeholder="Населений пункт")
            a3, a4, a5 = st.columns(3)
            with a3:
                st.text_input("Вулиця", key="upwiz_street", placeholder="Вулиця")
            with a4:
                st.text_input("Будинок", key="upwiz_house", placeholder="Буд.")
            with a5:
                st.text_input("Квартира", key="upwiz_apartment", placeholder="Кв.")

        _up_section_title("Інформація про відправлення")
        _render_upwiz_parcels_section()

        _wiz_edit = bool(st.session_state.get("upwiz_edit_mode"))
        _wiz_btn_label = "Зберегти" if _wiz_edit else "Створити"

        if st.button("Скасувати", key="upwiz_btn_cancel", use_container_width=True):
            st.session_state.upwiz_form_open = False
            _up_reset_wizard_form()
            st.rerun()

        calc_clicked = False
        save_clicked = False
        preview_json = False

        _up_render_wizard_description_field()

        _up_section_title("У разі невручення:")
        f1, f2 = st.columns(2)
        with f1:
            st.radio(
                "Дія",
                ["повернути", "не повертати"],
                key="upwiz_fail_main",
                label_visibility="collapsed",
            )
        with f2:
            st.radio(
                "Послуга повернення",
                ["Базовий", "Пріоритетний"],
                key="upwiz_fail_return_service",
                label_visibility="collapsed",
                disabled=st.session_state.get("upwiz_fail_main") == "не повертати",
            )

        _up_section_title("Додаткові послуги:")
        s1, s2 = st.columns(2)
        with s1:
            st.checkbox("СМС-повідомлення", key="upwiz_sms")
            st.checkbox("Email-повідомлення", key="upwiz_email_notify")
            st.checkbox("Повідомлення про вручення ф. 119", key="upwiz_form119")
            st.checkbox("Опис вкладення", key="upwiz_contents_desc")
        with s2:
            st.checkbox("Зараховувати післяплату на IBAN", key="upwiz_transfer_postpay_iban")
            st.checkbox("Огляд під час вручення", key="upwiz_check_delivery")

        pay1, pay2 = st.columns(2)
        with pay1:
            st.radio(
                "Сплачує плату за відправлення:",
                ["Відправник", "Одержувач"],
                horizontal=True,
                key="upwiz_paid_shipment_who",
                index=0,
            )
        with pay2:
            st.radio(
                "Сплачує плату за пересилання післяплати:",
                ["Одержувач", "Відправник"],
                horizontal=True,
                key="upwiz_paid_postpay_who",
                index=0,
            )
        st.session_state.upwiz_paid_shipment_recipient = (
            st.session_state.get("upwiz_paid_shipment_who") == "Одержувач"
        )
        st.session_state.upwiz_paid_postpay_recipient = (
            st.session_state.get("upwiz_paid_postpay_who") == "Одержувач"
        )

        with st.expander("Розширено: UUID отримувача / JSON"):
            _rid_show = _up_recipient_uuid_for_edit()
            if _rid_show:
                st.caption(f"UUID отримувача: `{_rid_show}`")
            st.text_input(
                "UUID отримувача (якщо потрібно вказати вручну)",
                key="upwiz_recipient_uuid_manual",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            )
            _created_rid = str(st.session_state.get("upwiz_recipient_uuid_created", "")).strip()
            if _created_rid:
                st.caption(f"UUID створено через API (для цієї форми): `{_created_rid}`")
            if st.button("Показати JSON запиту", key="upwiz_preview_json"):
                preview_json = True

        st.divider()
        _post_title = (
            "**Після збереження** — додати рядок у Google-таблицю:"
            if _wiz_edit
            else "**Після створення ТТН** — додати рядок у Google-таблицю:"
        )
        st.markdown(_post_title)
        cph, cco = st.columns(2)
        with cph:
            st.text_input("Телефон у таблицю", key="tab_up_new_phone", placeholder="380…")
        with cco:
            st.text_input("Вартість у таблицю", key="tab_up_new_cost", placeholder="0")

        b_calc, b_create = st.columns(2)
        with b_calc:
            calc_clicked = st.button(
                "Розрахувати", key="upwiz_btn_calc", use_container_width=True
            )
        with b_create:
            save_clicked = st.button(
                _wiz_btn_label,
                key="upwiz_btn_submit",
                type="primary",
                use_container_width=True,
            )

        if preview_json:
            v_err = _up_validate_wizard_form()
            if v_err:
                st.warning(v_err)
            else:
                rid, r_err = _up_ensure_recipient_uuid()
                if r_err:
                    st.error(r_err)
                else:
                    body, b_err = _up_build_shipment_dict_from_wizard(rid)
                    if b_err:
                        st.error(b_err)
                    else:
                        st.code(
                            _json.dumps(body, indent=2, ensure_ascii=False),
                            language="json",
                        )

        if calc_clicked:
            _up_sync_wizard_description_from_widget()
            v_err = _up_validate_wizard_form()
            if v_err:
                st.error(v_err)
            else:
                rid = _up_get_recipient_uuid()
                body, b_err = _up_build_shipment_dict_from_wizard(rid or None)
                if b_err and not rid:
                    st.session_state.up_calc_preview = None
                    st.warning(
                        f"{b_err} Для розрахунку вкажи UUID отримувача або натисни «Створити» внизу."
                    )
                elif b_err:
                    st.error(b_err)
                else:
                    st.session_state.up_calc_preview = body
                    st.info(
                        "JSON зібрано. Точну вартість Укрпошта повертає після «Створити» (поле deliveryPrice)."
                    )

        if save_clicked:
            _up_sync_wizard_description_from_widget()
            desc_saved = _up_capture_wizard_description()
            v_err = _up_validate_wizard_form()
            if v_err:
                st.error(v_err)
            elif _wiz_edit:
                suuid = str(st.session_state.get("upwiz_edit_shipment_uuid", "")).strip()
                bc_save = str(st.session_state.get("upwiz_edit_barcode", "")).strip()
                if not suuid:
                    st.error("Немає uuid відправлення для збереження.")
                else:
                    data, err = _up_save_wizard_edit(suuid, desc_saved)
                    if err:
                        st.error(f"Збереження: {err}")
                    else:
                        if not _up_recipient_uuid_for_edit():
                            st.warning(
                                "UUID отримувача не знайдено — оновлено лише дані відправлення "
                                "(опис, вага, післяплата). ПІБ/адреса в клієнті могли не змінитись."
                            )
                        if bc_save:
                            sheets.patch_up_shipment_description(bc_save, desc_saved)
                        fresh, ferr = up_fetch_shipment(
                            st.session_state.get("upwiz_edit_barcode") or suuid
                        )
                        if not ferr and fresh:
                            data = fresh
                        if isinstance(data, dict):
                            data = dict(data)
                            data["description"] = desc_saved
                        if isinstance(data, dict):
                            st.session_state.up_last_create_response = data
                            up_journal_save_response(
                                data,
                                patch_from_wizard=True,
                                description_override=desc_saved,
                            )
                            sheets.patch_up_shipment_description(
                                _up_barcode_from_create_response(data) or bc_save,
                                desc_saved,
                            )
                            _up_wizard_commit_saved_snapshot()
                        bc_journal = _up_format_bc_display(
                            _up_barcode_from_create_response(data) if isinstance(data, dict) else ""
                            or bc_save
                        )
                        if bc_journal:
                            _up_journal_set_desc_cache(bc_journal, desc_saved)
                            _up_clear_sticker_pdf_cache(bc_journal)
                        _cached_up_shipments_df.clear()
                        _desc_msg = f"«{desc_saved}»" if desc_saved else "(порожньо)"
                        st.success(
                            f"Зміни збережено. Дод. інформація в журналі: {_desc_msg}"
                        )
                        api_warn = str(
                            st.session_state.get("_upwiz_last_desc_put_warn", "")
                        ).strip()
                        if api_warn:
                            st.warning(
                                "Укрпошта могла не прийняти зміну опису через API "
                                f"(статус відправлення). Збережено в журналі. {api_warn[:180]}"
                            )
                        st.toast("Збережено", icon="✅")
                        st.session_state.upwiz_form_open = False
                        _up_clear_wizard_edit_state()
                        st.session_state.up_journal_edit_bc = ""
                        st.session_state.up_edit_panel_open = False
                        st.rerun()
            else:
                data, err = up_create_shipment_from_wizard_state()
                if err:
                    st.error(err)
                else:
                    price = (
                        data.get("deliveryPrice") if isinstance(data, dict) else None
                    )
                    if price is not None:
                        st.success(
                            f"Відправлення створено. Вартість доставки: {price} грн"
                        )
                    else:
                        st.success("Відправлення створено.")
                    st.toast("Укрпошта: ТТН створено", icon="✅")
                    st.session_state.upwiz_form_open = False
                    _up_clear_wizard_edit_state()
                    st.session_state.up_journal_edit_bc = ""
                    st.session_state.up_edit_panel_open = False
                    st.rerun()

        preview = st.session_state.get("up_calc_preview")
        if preview:
            with st.expander("Попередній JSON (розрахунок)", expanded=False):
                st.json(preview)

        resp = st.session_state.get("up_last_create_response")
        if resp is not None:
            with st.expander("Остання відповідь API", expanded=False):
                st.json(resp)
            bc = _up_barcode_from_create_response(resp)
            if bc:
                if len(bc) == 12 and bc.isdigit():
                    bc = "0" + bc
                st.markdown(f"**ТТН:** `{bc}`")
            st.caption("Редагування та друк — у списку нижче.")

        if st.button("Додати ТТН у таблицю Orders", key="tab_up_add_row_btn"):
            resp = st.session_state.get("up_last_create_response")
            if not resp:
                st.warning("Спочатку успішно створи відправлення.")
            else:
                bc = _up_barcode_from_create_response(resp)
                if not bc:
                    st.error("У відповіді немає barcode — додай ТТН вручну у «Таблиця».")
                else:
                    if len(bc) == 12 and bc.isdigit():
                        bc = "0" + bc
                    existing = st.session_state.df["ТТН"].astype(str).str.strip().tolist()
                    if bc in existing:
                        st.warning("Такий ТТН уже є в таблиці.")
                    else:
                        phone_w = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
                        phone_t = utils.clean_phone(str(st.session_state.get("tab_up_new_phone", "")).strip())
                        phone = phone_t or phone_w
                        c_w = _up_num_float(st.session_state.get("upwiz_declared_uah", 0))
                        try:
                            c_t = float(
                                str(st.session_state.get("tab_up_new_cost", "")).replace(",", ".").strip() or -1
                            )
                        except Exception:
                            c_t = -1.0
                        cost_v = c_t if c_t >= 0 else c_w
                        postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
                        if postpay >= 1 and cost_v <= 0:
                            cost_v = postpay
                        st.session_state.df.loc[len(st.session_state.df)] = {
                            "ТТН": bc,
                            "Служба": "УП",
                            "Статус": "Нове",
                            "Дата": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
                            "Телефон": phone,
                            "Вартість": cost_v,
                            "Номер накладної": "",
                            "Чек": "",
                            "Повідомлення": "",
                            "Статус СМС": "",
                            "Статус Нагадування": "",
                            "Дія": False,
                        }
                        st.session_state.df = ensure_messages_exist(st.session_state.df)
                        if sheets.save_manual(st.session_state.df):
                            audit_log("уп_нова_ттн", bc[:40], _json.dumps(resp, ensure_ascii=False)[:200])
                            st.toast("Рядок додано в Google Sheet", icon="✅")
                        else:
                            st.error("Не вдалося зберегти таблицю.")

    diag = _up_secrets_diag()
    with st.expander("Діагностика підключення УП", expanded=not _up_classifier_bearer()):
        st.caption(f"Усі ключі у Secrets: {diag.get('_sections', '—')}")
        st.caption(f"Ключі UP_* у файлі: **{diag.get('_up_keys_in_file', '—')}**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write(f"UP_BEARER_TOKEN: **{diag.get('UP_BEARER_TOKEN', '—')}**")
            st.write(f"UP_USER_TOKEN: **{diag.get('UP_USER_TOKEN', '—')}**")
        with c2:
            st.write(f"UP_COUNTERPARTY: **{diag.get('UP_COUNTERPARTY_TOKEN', '—')}**")
            st.write(f"UP_UUID: **{diag.get('UP_UUID', '—')}**")
        with c3:
            st.write(f"UP_SENDER_UUID: **{diag.get('UP_SENDER_UUID', '—')}**")
            st.write(f"UP_TRACKING: **{diag.get('UP_TRACKING_TOKEN', '—')}**")
        missing = diag.get("_missing") or []
        if missing:
            st.warning(
                "Не знайдено в Secrets: **"
                + ", ".join(missing)
                + "**. Якщо ти їх уже вписав — натисни **Save** у вікні Secrets "
                "(без помилки знизу), потім **Manage app → Reboot**."
            )
            if diag.get("UP_TRACKING_TOKEN", "—") != "—" and diag.get("UP_BEARER_TOKEN", "—") == "—":
                st.error(
                    "Є лише **UP_TRACKING_TOKEN**, а **UP_BEARER_TOKEN** немає в збереженому файлі. "
                    "Часто це через **перенос рядка всередині лапок** UUID — кожне значення має бути "
                    "в **одному рядку** між `\"` і `\"`."
                )
        if diag.get("_tracking_source"):
            st.caption(f"UP_TRACKING_TOKEN зчитано з: {diag['_tracking_source']}")
        with st.expander("Як виправити Secrets (обери один варіант)"):
            st.markdown(
                "**Варіант A** — додай **один** ключ `UP_INLINE_SECRETS` (найпростіше, якщо окремі рядки не зберігаються):"
            )
            st.code(
                '''UP_INLINE_SECRETS = """
UP_BEARER_TOKEN = "afa51d96-ac05-3fe8-8654-68956e5f1b06"
UP_UUID = "b15a87ed-036d-4a3c-8a0c-f8f894480cd2"
UP_USER_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_COUNTERPARTY_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_SENDER_NAME = "ФОП Прізвище Імʼя"
UP_SENDER_TIN = "1234567890"
UP_SENDER_PHONE = "380501234567"
UP_SENDER_BRANCH_INDEX = "78301"
UP_SENDER_ADDRESS = "вул. …, буд. …"
# UP_SENDER_BANK_ACCOUNT = "UA…"  # опційно, для післяплати на рахунок
# UP_SENDER_UUID — не обовʼязково; якщо чужий або не ФОП — видали, створиться ФОП автоматично
"""''',
                language="toml",
            )
            st.markdown("**Варіант B** — секція `[ukrposhta]`:")
            st.code(
                """[ukrposhta]
UP_BEARER_TOKEN = "afa51d96-ac05-3fe8-8654-68956e5f1b06"
UP_UUID = "b15a87ed-036d-4a3c-8a0c-f8f894480cd2"
UP_USER_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_SENDER_UUID = "uuid-відправника-з-кабінету-eCom"
""",
                language="toml",
            )
            st.caption(
                "UP_SENDER_UUID — не приклад «твій-uuid…», а реальний UUID з кабінету ok.ukrposhta → eCom → ваш відправник."
            )
            st.markdown(
                "**Варіант C** — окремі рядки в корені (кожен UUID **в один рядок**, потім **Save** → **Reboot**). "
                "Після Save у списку ключів зверху має з’явитись **UP_BEARER_TOKEN**, не лише UP_TRACKING_TOKEN."
            )
        ctest1, ctest2 = st.columns(2)
        with ctest1:
            if st.button("Тест індексу 78301", key="upwiz_test_index_btn"):
                load_secrets_to_config()
                res, err = up_lookup_by_postcode("78301")
                if err:
                    st.error(err)
                else:
                    st.success(
                        f"{res.get('region', '')}, {res.get('district', '')}, {res.get('city', '')}"
                    )
        with ctest2:
            if st.button("Перевірити відправника", key="upwiz_test_sender_btn"):
                load_secrets_to_config()
                sid, err = _up_ensure_sender_uuid()
                if err:
                    st.error(err)
                else:
                    cdata, _ = up_ecom_request("GET", f"/clients/{sid}")
                    ctype = str((cdata or {}).get("type") or "")
                    cname = str((cdata or {}).get("name") or "")
                    st.success(
                        f"Відправник OK: `{sid}` · **{_up_client_type_label(ctype)}**"
                        + (f" · {cname}" if cname else "")
                    )
                    if _up_expect_fop_sender() and ctype != "PRIVATE_ENTREPRENEUR":
                        st.warning(
                            "Очікується **ФОП**, але цей UUID — інший тип. "
                            "Видали UP_SENDER_UUID і додай UP_SENDER_TIN."
                        )
            if st.button("Тест eCom (адреса)", key="upwiz_test_ecom_btn"):
                load_secrets_to_config()
                if not config.UP_BEARER_TOKEN or not config.UP_UUID:
                    st.error("Потрібні UP_BEARER_TOKEN та UP_UUID у Secrets.")
                else:
                    probe = {
                        "country": "UA",
                        "postcode": "78301",
                        "region": "Закарпатська",
                        "city": "Ужгород",
                        "street": "test",
                        "houseNumber": "1",
                    }
                    data, err = up_ecom_request("POST", "/addresses", probe, token_required=False)
                    if err:
                        st.error(err)
                    else:
                        st.success(f"eCom OK, address id={data.get('id', '?')}")

# --- MEEST: публічний get.php (як на сайті) ---
MEEST_API_BASE = "https://api.meest.com/v3.0"
MEEST_PUBLIC_BASE = "https://meestposhta.com.ua/parcel-track"
_MEEST_SALT_CACHE = {"salt": "", "ts": 0.0}
_MEEST_SALT_TTL_SEC = 3600

_MEEST_STATUS_FIELD_KEYS = (
    "statusDescrUA",
    "statusDescr",
    "statusDescrEN",
    "eventDescrUA",
    "eventDescr",
    "eventName",
    "detailMessage",
    "statusName",
    "statusDescription",
    "lastEvent",
    "currentStatus",
    "descrUA",
    "statusText",
)
_MEEST_DATE_FIELD_KEYS = (
    "eventDate",
    "statusDate",
    "date",
    "lastUpdate",
    "lastModified",
    "dateTime",
)


def _meest_is_final_delivered(low: str) -> bool:
    """Чи це саме вручення (не «до відділення», не «очікує отримання»)."""
    if "не отриман" in low or "очікує отриман" in low:
        return False
    if "до відділення" in low and "отриман" not in low:
        return False
    if "готов" in low and "видач" in low:
        return False
    return any(
        x in low
        for x in ("отриман", "вручен", "доручен", "доставлено", "delivered")
    )


def _meest_normalize_status_label(status_result: str) -> str:
    """Зберігаємо формулювання Meest як є; лише фінал → «Отримано» для стоп-трекінгу."""
    s = str(status_result or "").strip()
    if not s or s == "Не знайдено":
        return s
    if _meest_is_final_delivered(s.lower()):
        return "Отримано"
    return s[:60]


def _meest_status_ok_to_save(s: str) -> bool:
    """Чи варто записувати статус у таблицю (не помилка API / «не знайдено»)."""
    if not s or str(s).startswith("Error"):
        return False
    low = str(s).strip().lower()
    if low in ("не знайдено", "невідомо", ""):
        return False
    if "не знайдено" in low and ("відправлен" in low or "номер" in low):
        return False
    return True


def _meest_pick_field(obj, keys: tuple) -> str:
    if isinstance(obj, dict):
        for key in keys:
            val = obj.get(key)
            if val is None:
                continue
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                nested = _meest_pick_field(val, keys)
                if nested:
                    return nested
    return ""


def _meest_status_from_api_result(result) -> tuple[str, str]:
    """Витягнути (статус, дата) з поля result відповіді Meest API."""
    if result is None:
        return "", ""
    if isinstance(result, str):
        return result.strip(), ""

    if isinstance(result, dict):
        for top_key in ("currentStatus", "lastStatus", "statusDescrUA", "statusDescr"):
            top_val = result.get(top_key)
            if isinstance(top_val, str) and top_val.strip():
                return top_val.strip(), _meest_pick_field(result, _MEEST_DATE_FIELD_KEYS)
        nested = result.get("events") or result.get("history") or result.get("trackingHistory")
        if isinstance(nested, list):
            result = nested
        else:
            candidates = [result]
            last = result
            status = _meest_pick_field(last, _MEEST_STATUS_FIELD_KEYS)
            date_val = _meest_pick_field(last, _MEEST_DATE_FIELD_KEYS)
            return status, date_val

    candidates: list = []
    if isinstance(result, list):
        candidates = [x for x in result if isinstance(x, dict)]

    if not candidates:
        return "", ""

    def _event_dt(ev: dict) -> str:
        return _meest_pick_field(ev, _MEEST_DATE_FIELD_KEYS) or ""

    candidates.sort(key=_event_dt)
    last = candidates[-1]
    status = _meest_pick_field(last, _MEEST_STATUS_FIELD_KEYS)
    date_val = _meest_pick_field(last, _MEEST_DATE_FIELD_KEYS)
    if not status:
        for ev in reversed(candidates):
            status = _meest_pick_field(ev, _MEEST_STATUS_FIELD_KEYS)
            if status:
                if not date_val:
                    date_val = _meest_pick_field(ev, _MEEST_DATE_FIELD_KEYS)
                break
    return status, date_val


def _meest_normalize_ttn_for_track(ttn: str) -> str:
    """Meest get.php часто вимагає дефіс: 7220802586 → 722-0802586."""
    s = str(ttn or "").strip()
    if not s or "-" in s:
        return s
    if any(c.isalpha() for c in s):
        return s
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:]}"
    return s


def _meest_fetch_salt() -> str:
    """Salt з HTML parcel-track (потрібен для chk= md5)."""
    import re
    import time

    now = time.time()
    cached = _MEEST_SALT_CACHE.get("salt") or ""
    if cached and now - float(_MEEST_SALT_CACHE.get("ts") or 0) < _MEEST_SALT_TTL_SEC:
        return cached

    url = f"{MEEST_PUBLIC_BASE}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "uk-UA,uk;q=0.9",
    }
    try:
        r = utils.make_request("GET", url, headers=headers, timeout=20)
        if not r or r.status_code != 200:
            return cached
        html = r.text or ""
        m = re.search(r"var\s+salt\s*=\s*'([^']+)'", html)
        if m:
            salt = m.group(1).strip()
            _MEEST_SALT_CACHE["salt"] = salt
            _MEEST_SALT_CACHE["ts"] = now
            return salt
    except Exception:
        pass
    return cached


def _meest_chk(number: str, salt: str) -> str:
    import hashlib

    payload = f"{salt}{number}{salt}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _meest_unescape_xml_text(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    return (
        s.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&amp;", "&")
    )


def _meest_parse_tracking_xml(xml_text: str) -> tuple[str, str]:
    """Останній ActionMessages + DateTimeAction з XML get.php."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return "", ""

    status = ""
    date_raw = ""
    for item in root.findall(".//items"):
        action = _meest_unescape_xml_text(item.findtext("ActionMessages") or "")
        if not action:
            action = _meest_unescape_xml_text(item.findtext("ActionMessages_RU") or "")
        if not action:
            action = _meest_unescape_xml_text(item.findtext("ActionMessages_EN") or "")
        if action:
            status = action
        dt = (item.findtext("DateTimeAction") or "").strip()
        if dt:
            date_raw = dt.replace(" 00:00:00", "").replace(" 00:00:01", "")
    return status, date_raw


def get_meest_status_http(ttn: str, ext_track: bool = False):
    """POST /parcel-track/get.php — той самий запит, що meestposhta.com.ua."""
    import urllib.parse

    number = _meest_normalize_ttn_for_track(ttn)
    if not number:
        return "Не знайдено", "", "", 0.0

    salt = _meest_fetch_salt()
    if not salt:
        return None

    ext = "1" if ext_track else ""
    chk = _meest_chk(number, salt)
    qs = (
        f"what=tracking&test&number={urllib.parse.quote(number, safe='')}"
        f"&lang=uk&ext_track={ext}&chk={chk}"
    )
    url = f"{MEEST_PUBLIC_BASE}/get.php?{qs}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"{MEEST_PUBLIC_BASE}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/xml, text/xml, */*; q=0.01",
    }
    try:
        r = utils.make_request("POST", url, headers=headers, data="", timeout=25)
        if not r or r.status_code != 200:
            return None
        status_raw, date_raw = _meest_parse_tracking_xml(r.text or "")
        if not status_raw:
            return "Не знайдено", "", "", 0.0
        label = _meest_normalize_status_label(status_raw)
        date_norm = utils.normalize_date(date_raw.split()[0]) if date_raw else ""
        return label, "", date_norm, 0.0
    except Exception:
        return None


def get_meest_status_api(ttn: str):
    """GET /tracking/{trackNumber} — офіційний API Meest (потрібен MEEST_API_TOKEN у Secrets)."""
    load_secrets_to_config()
    token = str(getattr(config, "MEEST_API_TOKEN", "") or "").strip()
    if not token:
        return None
    ttn = str(ttn or "").strip()
    if not ttn:
        return "Не знайдено", "", "", 0.0

    import urllib.parse

    url = f"{MEEST_API_BASE}/tracking/{urllib.parse.quote(ttn, safe='')}"
    headers = {
        "token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        r = utils.make_request("GET", url, headers=headers, timeout=30)
        if not r:
            return None
        if r.status_code == 404:
            return "Не знайдено", "", "", 0.0
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    if str(data.get("status", "")).upper() == "ERROR":
        return None

    status_raw, date_raw = _meest_status_from_api_result(data.get("result"))
    if not status_raw:
        return "Не знайдено", "", "", 0.0
    label = _meest_normalize_status_label(status_raw)
    date_norm = utils.normalize_date(date_raw) if date_raw else ""
    return label, "", date_norm, 0.0


def get_meest_status(ttn):
    """Статус Meest через meestposhta.com.ua (get.php)."""
    number = _meest_normalize_ttn_for_track(ttn)
    if not number:
        return "Не знайдено", "", "", 0.0

    for ext in (False, True):
        http_res = get_meest_status_http(number, ext_track=ext)
        if http_res is None:
            return "Error: Meest HTTP", "", "", 0.0
        if _meest_status_ok_to_save(http_res[0]):
            return http_res

    return "Не знайдено", "", "", 0.0

def fetch_new_orders_meest(existing_ttns):
    return []

# ==========================================
# 📊 ЛОГІКА ДАНИХ
# ==========================================



def _prepare_orders_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if "Номер ТТН" in df.columns:
        df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
    df = ensure_columns(df)
    df = apply_table_column_order(df, get_table_column_order())
    df["ТТН"] = df["ТТН"].apply(restore_leading_zero)

    text_cols = [
        "ТТН",
        "Служба",
        "Статус",
        "Дата",
        "Телефон",
        "Чек",
        "Повідомлення",
        "Статус СМС",
        "Статус Нагадування",
        "Номер накладної",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", "")

    if "Номер накладної" in df.columns:
        df["Номер накладної"] = df["Номер накладної"].apply(utils.normalize_invoice_number)

    if "Вартість" in df.columns:
        df["Вартість"] = (
            df["Вартість"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace(r"\s+", "", regex=True)
        )
        df["Вартість"] = pd.to_numeric(df["Вартість"], errors="coerce").fillna(0.0)

    if "Дія" in df.columns:
        df["Дія"] = (
            df["Дія"]
            .replace(
                {
                    "True": True,
                    "False": False,
                    "": False,
                    "FALSE": False,
                    "TRUE": True,
                    1: True,
                    0: False,
                }
            )
            .infer_objects(copy=False)
            .fillna(False)
            .astype(bool)
        )
    if "Дата" in df.columns:
        df["Дата"] = df["Дата"].apply(utils.normalize_date)
    return ensure_messages_exist(df)


def load_data(*, force_reload: bool = False):
    if force_reload:
        sheets.reload_orders_from_gsheets()
    if force_reload or "df" not in st.session_state:
        df = sheets.load_data_from_gsheets()
        if df.empty and not force_reload:
            sheets.load_data_from_gsheets.clear()
            df = sheets.load_data_from_gsheets()
        df = _prepare_orders_dataframe(df)
        if utils.apply_no_receipt_auto_sent(df) and not df.empty:
            sheets.save_manual(df)
        st.session_state.df = df
        if df.empty:
            st.session_state["_orders_empty_warned"] = True
    else:
        st.session_state.df = ensure_columns(st.session_state.df)
        if "Номер накладної" in st.session_state.df.columns:
            st.session_state.df["Номер накладної"] = st.session_state.df["Номер накладної"].apply(
                utils.normalize_invoice_number
            )
        if utils.apply_no_receipt_auto_sent(st.session_state.df):
            sheets.save_manual(st.session_state.df)

def run_auto_linking(silent=False):
    """Автопідбір чека з Checkbox: **лише** дві умови — без інших евристик.

    1. Сума чека після округлення до копійки **дорівнює** «Вартість» рядка (так само до копійки).
    2. |Дата відправлення в рядку − дата/час чека| ≤ **120 с** (2 хв).

    Серед допустимих пар вибір за **найменшою** різницею в часі; один URL чека — максимум один рядок.
    """
    # Суворо 2 хвилини; сума — тільки точний збіг у гривнях з копійками (round 2), не «майже».
    max_dt_sec = 2 * 60

    checkbox_df = fetch_checkbox_archive()
    if checkbox_df is None or checkbox_df.empty:
        return 0
    checkbox_df = checkbox_df.copy()
    checkbox_df["dt_obj"] = pd.to_datetime(checkbox_df["Дата"], errors="coerce")
    sums = pd.to_numeric(checkbox_df["Сума"], errors="coerce").round(2)

    df = st.session_state.df.copy()
    for col in df.columns:
        df[col] = df[col].astype(object)

    used_links = set()
    for _, r in df.iterrows():
        lk = str(r.get("Чек", "")).strip()
        if lk and len(lk) > 5 and lk.lower() != "nan":
            used_links.add(lk)

    def _link_row_meta(row):
        try:
            c = float(str(row.get("Вартість", 0)).replace(",", ".").strip())
            ds = str(row.get("Дата", "")).strip()
            if c <= 0 or len(ds) < 10:
                return None
            return round(c, 2), pd.to_datetime(ds)
        except Exception:
            return None

    to_link = []
    for idx, row in df.iterrows():
        cur = str(row.get("Чек", "")).strip()
        if cur and len(cur) > 5 and cur.lower() != "nan":
            continue
        meta = _link_row_meta(row)
        if not meta:
            continue
        cost_kop, np_dt = meta
        to_link.append((idx, np_dt, cost_kop))

    # Усі допустимі пари (рядок, чек): та сама сума до копійки + Δчас ≤ 2 хв; далі — за зростанням Δ
    edges = []
    for idx, np_dt, cost_kop in to_link:
        cand_mask = (sums == cost_kop) & sums.notna()
        for _, check in checkbox_df.loc[cand_mask].iterrows():
            link = str(check.get("Посилання", "")).strip()
            if not link or link in used_links:
                continue
            cdt = check["dt_obj"]
            if pd.isna(cdt):
                continue
            delta_sec = abs((np_dt - cdt).total_seconds())
            if delta_sec > max_dt_sec:
                continue
            edges.append((delta_sec, idx, link))

    edges.sort(key=lambda e: e[0])
    rows_done = set()
    matches = 0
    for delta_sec, idx, link in edges:
        if idx in rows_done:
            continue
        if link in used_links:
            continue
        df.at[idx, "Чек"] = link
        rows_done.add(idx)
        used_links.add(link)
        matches += 1
        try:
            sc_auto = float(
                str(df.at[idx, "Вартість"]).replace(",", ".").strip()
            )
        except Exception:
            sc_auto = None
        rs_auto = None
        try:
            mchk = checkbox_df[
                checkbox_df["Посилання"].astype(str).str.strip() == str(link).strip()
            ]
            if not mchk.empty:
                rs_auto = float(
                    str(mchk.iloc[0].get("Сума", 0)).replace(",", ".").strip() or 0
                )
        except Exception:
            pass
        audit_log(
            "чек_авто",
            str(df.at[idx, "ТТН"]).strip()[:40],
            link[:120],
            ship_cost=sc_auto,
            receipt_sum=rs_auto,
        )

    if matches > 0:
        st.session_state.df = df
        if sheets.save_manual(df):
            if not silent:
                st.success(f"✅ Знайдено {matches} чеків!")
                time.sleep(1.5)
                st.rerun()
    return matches

def process_status_updates(show_ui=True, services=None):
    """Оновлення статусів у таблиці.

    Parameters
    ----------
    show_ui : bool
        Показати progress і підпис поточної ТТН.
    services : None | tuple[str, ...]
        ``None`` — усі служби (НП, УП, Meest). Інакше лише вказані, напр.
        ``("НП", "УП")`` для швидкого режиму без Meest.
    """
    allowed = None if services is None else frozenset(str(s) for s in services)

    work_df = st.session_state.df.copy()
    # Переводимо колонки в object, щоб уникнути TypeError при присвоєнні
    for col in work_df.columns:
        work_df[col] = work_df[col].astype(object)
    count_sms = 0
    progress_bar = st.progress(0) if show_ui else None
    status_text = st.empty() if show_ui else None

    for i, row in work_df.iterrows():
        # Для Meest (721-...) не застосовуємо чистку, щоб не ламати пошук
        raw_ttn = str(work_df.loc[i, 'ТТН']).strip()
        svc = row['Служба']
        if not svc or svc == "Інше": svc = utils.identify_service(raw_ttn)
        
        if svc == "Meest":
            ttn = raw_ttn 
        else:
            ttn = utils.clean_ttn(raw_ttn)
        
        work_df.loc[i, 'ТТН'] = ttn 
        work_df.loc[i, 'Служба'] = svc

    rows_list = list(work_df.iterrows())
    total = len(rows_list)
    # Batch НП checks (лише якщо НП у вибраних службах)
    if allowed is None or "НП" in allowed:
        np_ttns = [
            str(row["ТТН"])
            for _, row in work_df.iterrows()
            if row["Служба"] == "НП" and len(str(row["ТТН"])) > 5
        ]
        np_statuses = get_np_statuses_bulk(np_ttns) if np_ttns else {}
    else:
        np_statuses = {}

    for step, (i, row) in enumerate(rows_list):
        if show_ui:
            progress_bar.progress((step + 1) / max(total, 1))
        ttn = str(work_df.loc[i, 'ТТН'])
        if len(ttn) < 5: continue
        
        svc = work_df.loc[i, 'Служба']
        current = str(work_df.loc[i, 'Статус']).lower()
        
        s, d, cost, phone, extra = "", None, 0.0, "", ""
        
        if (
            svc == "НП"
            and (allowed is None or "НП" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if ttn in np_statuses:
                info = np_statuses[ttn]
                s = info.get('Status', '')
                cost = info.get('Cost', 0.0)
                phone = info.get('Phone', '')
                invoice = info.get('ClientBarcode', '')
                if invoice:
                    work_df.loc[i, 'Номер накладної'] = utils.normalize_invoice_number(invoice)
        
        elif (
            svc == "УП"
            and (allowed is None or "УП" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if show_ui: status_text.text(f"Перевірка УП: {ttn}")
            s, d, cost, phone, extra = get_up_status_smart(ttn)
            if phone and len(str(work_df.loc[i, 'Телефон'])) < 10:
                work_df.loc[i, 'Телефон'] = str(phone)
        
        elif (
            svc == "Meest"
            and (allowed is None or "Meest" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if show_ui: status_text.text(f"Перевірка Meest: {ttn}")
            s, p, d, cost = get_meest_status(ttn)
            
        if _meest_status_ok_to_save(s) if svc == "Meest" else (
            s and not str(s).startswith("Error") and s != "Не знайдено"
        ):
            work_df.loc[i, 'Статус'] = str(s)
        if d: work_df.loc[i, 'Дата'] = str(d)
        try:
            cost_value = float(str(cost).replace(',', '.').strip())
        except Exception:
            cost_value = 0.0
        if cost_value > 0:
            work_df.loc[i, 'Вартість'] = cost_value
        if phone and len(str(work_df.loc[i, 'Телефон'])) < 10:
            work_df.loc[i, 'Телефон'] = str(phone)
        
    utils.apply_no_receipt_auto_sent(work_df)
    work_df = ensure_messages_exist(work_df)
    st.session_state.df = work_df
    saved = sheets.save_manual(st.session_state.df)
    if show_ui: status_text.empty(); progress_bar.empty()
    return count_sms, saved

load_data()
if len(st.session_state.df) == 0 and not st.session_state.get("_gs_reload_on_empty"):
    st.session_state._gs_reload_on_empty = True
    load_data(force_reload=True)

if 'auto_refresh' not in st.session_state: st.session_state.auto_refresh = False
if 'last_status_update' not in st.session_state: st.session_state.last_status_update = 0
if '_deferred_save' not in st.session_state: st.session_state._deferred_save = False
st.sidebar.toggle("🔄 Авто-пошук (ВКЛ/ВИКЛ)", key="auto_refresh")
if st.sidebar.button(
    "📥 Оновити з Google Sheets",
    use_container_width=True,
    help="Перечитати таблицю Orders (якщо дані зникли або застаріли)",
):
    load_data(force_reload=True)
    st.sidebar.success(f"Завантажено: {len(st.session_state.df)} рядків")
    st.rerun()
n_df = len(st.session_state.df) if "df" in st.session_state else 0
st.sidebar.caption(f"Рядків у таблиці: **{n_df}**")
if n_df == 0 and st.session_state.get("_orders_empty_warned"):
    st.sidebar.warning(
        "Таблиця порожня. Перевірте Google Sheets (аркуш Orders) або "
        "історію версій файлу. Якщо дані на аркуші є — натисніть **Оновити з Google Sheets**."
    )
ui_theme.render_theme_selector()
ui_theme.inject_app_theme()
ui_theme.render_app_header()

if st.session_state.auto_refresh:
    with st.spinner("⏳ Авто: Пошук нових..."):
        st.cache_data.clear() 
        existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
        n_np = fetch_new_orders_np(existing)
        n_up = fetch_new_orders_up(existing)
        n_meest = fetch_new_orders_meest(existing)
        all_new = n_np + n_up + n_meest
        if all_new:
            new_df = pd.DataFrame(all_new)
            for c in config.COLS:
                if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
            st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
            sheets.save_manual(st.session_state.df)
            
            # Автопідбір чеків для щойно доданих відправлень
            run_auto_linking(silent=True)

    sms_count = 0
    if time.time() - st.session_state.last_status_update > 300:
        with st.spinner("⏳ Авто: Глибока перевірка статусів..."):
            sms_count, _ = process_status_updates(show_ui=False)
            run_auto_linking(silent=True)
            st.session_state.last_status_update = time.time()
    msg = []
    if all_new: msg.append(f"+{len(all_new)} нових")
    if sms_count > 0: msg.append(f"+{sms_count} SMS")
    if msg:
        st.toast(f"Оновлено: {', '.join(msg)}", icon="🔔")
        ts = int(time.time()); components.html(f"""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3?t={ts}"></audio>""", height=0)
    time.sleep(60); st.rerun()

with st.sidebar:
    st.header("🎮 Пульт")

    with st.expander("➕ Додати ТТН вручну", expanded=True):
        with st.form("manual_add_form", clear_on_submit=True):
            manual_ttn = st.text_input("ТТН *")
            manual_phone = st.text_input("Телефон *")
            manual_cost = st.text_input("Вартість (грн) *")
            manual_invoice = st.text_input("Номер накладної *")
            submitted = st.form_submit_button("Додати")
            if submitted:
                ttn_raw = (manual_ttn or "").strip()
                phone_raw = (manual_phone or "").strip()
                cost_raw = (manual_cost or "").strip()
                invoice_raw = (manual_invoice or "").strip()
                missing = []
                if not ttn_raw:
                    missing.append("ТТН")
                if not phone_raw:
                    missing.append("Телефон")
                if not cost_raw:
                    missing.append("Вартість")
                if not invoice_raw:
                    missing.append("Номер накладної")
                if missing:
                    st.error(f"Заповніть обов'язкові поля: {', '.join(missing)}")
                else:
                    phone_clean = utils.clean_phone(phone_raw)
                    if len(phone_clean) <= 5:
                        st.error("Некоректний телефон.")
                    else:
                        try:
                            cost_value = float(cost_raw.replace(",", "."))
                        except ValueError:
                            st.error("Некоректна вартість — введіть число.")
                        else:
                            invoice_norm = utils.normalize_invoice_number(invoice_raw)
                            if not str(invoice_norm).strip():
                                st.error("Некоректний номер накладної.")
                            else:
                                parts = [p for p in ttn_raw.replace(",", " ").split() if p.strip()]
                                if len(parts) > 1:
                                    st.error("Додавайте лише один ТТН за раз.")
                                else:
                                    t = ttn_raw.strip()
                                    if "721-" in t:
                                        t_clean = t
                                        svc = "Meest"
                                    else:
                                        t_clean = utils.clean_ttn(t)
                                        svc = utils.identify_service(t_clean)
                                    if not t_clean:
                                        st.error("Не вдалось розпізнати ТТН.")
                                    elif t_clean in st.session_state.df["ТТН"].astype(str).str.strip().tolist():
                                        st.warning("Такий ТТН уже є в базі.")
                                    else:
                                        st.session_state.df.loc[len(st.session_state.df)] = {
                                            "ТТН": t_clean,
                                            "Служба": svc,
                                            "Статус": "Нове",
                                            "Дата": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
                                            "Телефон": phone_clean,
                                            "Вартість": cost_value,
                                            "Номер накладної": invoice_norm,
                                            "Чек": "",
                                            "Повідомлення": "",
                                            "Статус СМС": "",
                                            "Статус Нагадування": "",
                                            "Дія": False,
                                        }
                                        if sheets.save_manual(st.session_state.df):
                                            st.success("Додано накладну!")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error("Помилка збереження! Перевір права.")
    if st.button("📥 Завантажити нові", type="primary"):
        with st.status("Завантаження...", expanded=True):
            existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
            n_np = fetch_new_orders_np(existing)
            n_up = fetch_new_orders_up(existing)
            n_meest = fetch_new_orders_meest(existing)
            all_new = n_np + n_up + n_meest
            if all_new:
                new_df = pd.DataFrame(all_new)
                for c in config.COLS:
                    if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
                st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
                sheets.save_manual(st.session_state.df); 
                # Автопідбір чеків після додавання нових відправлень
                run_auto_linking(silent=True)
                st.success(f"✅ Додано {len(all_new)} нових!"); time.sleep(1); st.rerun()
            else: st.info("Нових немає")
    st.divider()
    if st.button(
        "🔄 Оновити НП та УП",
        help="Швидко: пакетна Нова пошта + запити Укрпошти. Meest — окремою кнопкою або автооновленням.",
    ):
        _, saved = process_status_updates(show_ui=True, services=("НП", "УП"))
        if saved:
            st.success("Статуси НП та УП оновлено.")
            time.sleep(0.8)
            st.rerun()
    if st.button(
        "🔄 Оновити Meest",
        help="Відстеження через meestposhta.com.ua (get.php, ~1–2 с на ТТН).",
    ):
        _, saved = process_status_updates(show_ui=True, services=("Meest",))
        if saved:
            st.success("Статуси Meest оновлено.")
            time.sleep(0.8)
            st.rerun()
    with st.expander("🔍 Перевірити одну ТТН Meest", expanded=False):
        meest_test_ttn = st.text_input(
            "ТТН",
            key="meest_test_ttn",
            placeholder="721-… або CV…",
        )
        if st.button("Перевірити", key="meest_test_btn"):
            ttn_test = (meest_test_ttn or "").strip()
            if not ttn_test:
                st.warning("Введіть номер ТТН.")
            else:
                with st.spinner(f"Meest: {ttn_test}…"):
                    test_status, _, test_date, _ = get_meest_status(ttn_test)
                st.markdown(f"**Статус:** {test_status or '—'}")
                if test_date:
                    st.markdown(f"**Дата:** {test_date}")
                import urllib.parse

                site_url = (
                    f"{MEEST_PUBLIC_BASE}?parcel_number="
                    f"{urllib.parse.quote(ttn_test, safe='')}"
                )
                st.caption(f"[Відкрити на сайті Meest]({site_url})")
    if st.button("🗑️ Видалити відправлені", type="secondary"):
        st.session_state.df = _tab1_without_sent_rows(st.session_state.df)
        sheets.save_manual(st.session_state.df)
        st.success("✅ Очищено!")
        time.sleep(1)
        st.rerun()
    if st.button(
        "🔗 Авто-підбір чеків",
        help="Лише якщо сума чека = «Вартість» до копійки і різниця між датою відправлення та датою чека не більше 2 хв. Інших умов немає.",
    ):
        run_auto_linking(silent=False)
    st.divider()
    with st.expander("📂 Імпорт з файлу", expanded=False):
        st.caption(
            "Формат: колонка **A** ТТН, **B** телефон, **C** вартість, **D** накладна. Перший рядок файлу — заголовки."
        )
        uploaded_file = st.file_uploader(
            "Оберіть файл (XLSX/CSV)", type=["xlsx", "csv"], key="import_uploader"
        )
        if uploaded_file:
            if st.button("📥 Завантажити файл"):
                try:
                    df_upload = utils.read_uploaded_table(
                        uploaded_file,
                        min_columns=1,
                        require_non_empty=True,
                        csv_encodings=['utf-8', 'cp1251', 'latin1'],
                        csv_separators=[',', ';', '\t', '|']
                    )
                    if df_upload is None:
                        st.error("❌ Не вдалось прочитати файл імпорту. Перевірте формат CSV/XLSX.")
                        st.info("💡 Спробуйте: \n1. Зберегти файл як UTF-8 \n2. Переконайтесь що роздільник `,` або `;` \n3. Завантажити як XLSX")
                        st.stop()
                    
                    # 1. Фіксований формат імпорту:
                    #    кол.A ТТН, кол.B Телефон, кол.C Вартість, кол.D Номер накладної
                    #    У Excel/CSV: перший рядок файлу = заголовки колонок (pandas не показує його як рядок даних),
                    #    перший рядок даних у файлі = другий візуально рядок → це df.iloc[0].
                    if len(df_upload.columns) < 4:
                        st.error("❌ Для імпорту потрібно мінімум 4 колонки: ТТН, Телефон, Вартість, Номер накладної.")
                        st.stop()

                    import_rows = df_upload.iloc[0:]
                    if import_rows.empty:
                        st.warning("⚠️ У файлі немає рядків із даними після рядка заголовків.")
                        st.stop()

                    # 2. Збір усіх ТТН для перевірки
                    raw_ttns = []
                    rows_map = {}
                    for _, row in import_rows.iterrows():
                        raw_t = str(row.iloc[0]).strip()
                        raw_phone = str(row.iloc[1]).strip()
                        raw_cost = str(row.iloc[2]).strip()
                        raw_invoice = str(row.iloc[3]).strip()

                        try:
                            parsed_cost = float(raw_cost.replace(",", ".")) if raw_cost and raw_cost.lower() != 'nan' else 0.0
                        except Exception:
                            parsed_cost = 0.0

                        # Якщо це Meest-номер із тире, не чистимо його
                        if "721-" in raw_t:
                            clean_t = raw_t.strip()
                        else:
                            clean_t = utils.clean_ttn(raw_t)
                            
                        if len(clean_t) == 12 and clean_t.isdigit(): clean_t = "0" + clean_t
                        if len(clean_t) > 5:
                            raw_ttns.append(clean_t)
                            rows_map[clean_t] = {
                                "phone": raw_phone,
                                "cost": parsed_cost,
                                "invoice": ""
                                if raw_invoice.lower() == "nan"
                                else utils.normalize_invoice_number(raw_invoice),
                            }

                    # 3. МАСОВА ПЕРЕВІРКА СТАТУСІВ (Нова Пошта)
                    st.toast("🕵️ Перевіряємо статуси ТТН...")
                    np_statuses = get_np_statuses_bulk(raw_ttns)

                    # 4. Фільтрація і додавання
                    added_count = 0
                    existing_ttns = [str(x) for x in st.session_state.df['ТТН'].tolist()]
                    
                    for ttn in raw_ttns:
                        if ttn in existing_ttns: continue
                        
                        # Отримуємо дані з API (якщо є)
                        info = np_statuses.get(ttn, {})
                        status = info.get('Status', 'Нове')
                        src = rows_map.get(ttn, {})
                        file_cost = float(src.get("cost", 0.0) or 0.0)
                        cost = info.get('Cost', 0.0) or file_cost
                        
                        # Пропускаємо завершені та відхилені відправлення
                        if utils.status_has_any(status, utils.DELIVERED_STATUS_KEYWORDS + utils.DECLINED_STATUS_KEYWORDS): continue
                        
                        # Визначаємо службу без зміни формату Meest
                        if "721-" in ttn:
                            svc = "Meest"
                        else:
                            svc = utils.identify_service(ttn)
                            
                        ph = utils.clean_phone(src.get("phone", ""))
                        if info.get('Phone'): ph = info['Phone']
                        invoice_num = utils.normalize_invoice_number(src.get("invoice", ""))

                        st.session_state.df.loc[len(st.session_state.df)] = {
                            "ТТН": ttn, "Служба": svc, "Статус": status, 
                            "Дата": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
                            "Телефон": ph, "Вартість": cost, "Номер накладної": invoice_num, "Чек": "", "Повідомлення": "", 
                            "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                        }
                        added_count += 1
                        existing_ttns.append(ttn)
                    
                    if added_count > 0:
                        sheets.save_manual(st.session_state.df)
                        run_auto_linking(silent=True)
                        st.success(f"✅ Імпортовано {added_count} активних посилок!")
                        time.sleep(1.5); st.rerun()
                    else:
                        st.warning("Нових активних посилок не знайдено.")
                        
                except Exception as e:
                    st.error(f"Помилка: {e}")

    with st.expander("📝 Оновити номера накладних з файлу", expanded=False):
        invoice_file = st.file_uploader("Оберіть файл (XLSX/CSV) - 1 колонка: ТТН, 2 колонка: номер накладної", type=['xlsx', 'csv'], key="invoice_uploader")
        if invoice_file:
            try:
                invoice_df = utils.read_uploaded_table(
                    invoice_file,
                    min_columns=2,
                    require_non_empty=True
                )

                if invoice_df is None:
                    st.error("❌ Не вдалось прочитати CSV. Файл може бути пошкоджений або мати неправильний формат.")
                    st.info("💡 Спробуйте: \n1. Зберегти файл як UTF-8 \n2. Переконайтесь що роздільник `,` або `;` \n3. Завантажити як XLSX")
                
                if invoice_df is not None:
                    # Очищуємо пробіли в назвах колонок
                    invoice_df.columns = invoice_df.columns.str.strip()
                    invoice_df = invoice_df.dropna(how='all')  # Видаляємо абсолютно пусті рядки
                    
                    st.info(f"📋 Прочитано {len(invoice_df)} рядків, {len(invoice_df.columns)} колонок")
                    st.write(f"**Колонки:** {list(invoice_df.columns)}")
                    
                    if len(invoice_df.columns) < 2:
                        st.error(f"❌ Файл містить тільки {len(invoice_df.columns)} колонку/колонок. Потрібно мінімум 2!")
                        st.warning("Переконайтесь що файл має правильний формат (ТТН | Накладна)")
                    elif len(invoice_df) == 0:
                        st.error("❌ Файл порожній або не містить даних!")
                    else:
                        with st.expander("👀 Попередній перегляд даних"):
                            st.dataframe(invoice_df.head(5), use_container_width=True)
                        
                        if st.button("🔄 Оновити накладні", key="btn_update_invoices"):
                            # Беремо перший і другий стовпці
                            ttn_col = invoice_df.columns[0]
                            invoice_num_col = invoice_df.columns[1]
                            
                            st.info(f"🔍 Оновлення: **{ttn_col}** → ТТН, **{invoice_num_col}** → Накладна")
                            
                            updated = 0
                            skipped = 0
                            found_count = 0
                            
                            for idx, row in invoice_df.iterrows():
                                ttn_raw = str(row[ttn_col]).strip()
                                invoice_num = utils.normalize_invoice_number(
                                    str(row[invoice_num_col]).strip()
                                )
                                
                                if not ttn_raw or ttn_raw.lower() == 'nan':
                                    skipped += 1
                                    continue
                                
                                if not invoice_num or invoice_num.lower() == 'nan':
                                    skipped += 1
                                    continue
                                
                                # Чистимо ТТН
                                if "721-" in ttn_raw:
                                    ttn_clean = ttn_raw
                                else:
                                    ttn_clean = utils.clean_ttn(ttn_raw)
                                
                                # Шукаємо в таблиці
                                for i, df_row in st.session_state.df.iterrows():
                                    if str(df_row['ТТН']).strip() == ttn_clean:
                                        st.session_state.df.at[i, 'Номер накладної'] = invoice_num
                                        updated += 1
                                        found_count += 1
                                        break
                                else:
                                    skipped += 1
                            
                            sheets.save_manual(st.session_state.df)
                            st.success(f"✅ Обновлено {updated} накладних! (Знайдено ТТН: {found_count}, Пропущено: {skipped})")
                            if updated > 0:
                                time.sleep(1); st.rerun()
            except Exception as e:
                st.error(f"❌ Помилка: {str(e)}")
                import traceback
                st.error(traceback.format_exc())

    if st.button("🚪 Вийти", type="secondary"): st.session_state.logged_in = False; st.session_state.pop("auth_user", None); st.rerun()




_flush_rozetka_pending_up_create()

_auth_lc = str(st.session_state.get("auth_user", "")).strip().lower()
_is_manager = _auth_lc == "manager"
# Вкладка «УП ТТН» (eCom / майстер) — лише для admin; менеджер її не бачить.
_show_up_ttn_tab = _auth_lc == "admin"
_show_rozetka_tab = _auth_lc == "admin"

_tab_names = [
    "📨 Видати чек",
    "📊 Таблиця",
]
if _show_up_ttn_tab:
    _tab_names.append("📮 УП ТТН")
if _show_rozetka_tab:
    _tab_names.append("🛒 Rozetka")
_tab_names.extend(
    [
        "❌ Відмови",
        "🧾 Архів чеків",
        "⏳ Нагадування",
    ]
)
# Менеджеру не показуємо журнал дій (вкладка «Контроль»).
if not _is_manager:
    _tab_names.append("📋 Контроль")
_tabs = st.tabs(_tab_names)
_i = 0
tab1 = _tabs[_i]
_i += 1
tab2 = _tabs[_i]
_i += 1
if _show_up_ttn_tab:
    tab_up = _tabs[_i]
    _i += 1
if _show_rozetka_tab:
    tab_rz = _tabs[_i]
    _i += 1
tab3 = _tabs[_i]
_i += 1
tab4 = _tabs[_i]
_i += 1
tab5 = _tabs[_i]
_i += 1
with tab1:
    tab1_checkout.render_fragment()
with tab2:
    tab2_table.render_fragment()
if _show_up_ttn_tab:
    with tab_up:
        render_up_shipments_tab()
if _show_rozetka_tab:
    with tab_rz:
        tab_rozetka.render_tab()
with tab3:
    tab3_refusals.render_tab()
with tab4:
    tab4_archive.render_tab()
with tab5:
    tab5_reminders.render_tab()

if not _is_manager:
    with _tabs[-1]:
        render_audit_tab()

if st.session_state.get('_deferred_save'):
    st.session_state._deferred_save = False
    if not sheets.save_manual(st.session_state.df):
        st.error("❌ Не вдалося зберегти зміни після позначення 'Готово'.")
