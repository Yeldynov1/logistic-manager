import copy
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

# Selenium для серверного режиму (headless)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# --- ПІДКЛЮЧЕННЯ МОДУЛІВ ---
import auth  # Локальний вхід (bcrypt + Secrets)
import config  # Налаштування
import utils  # Технічні функції

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="Alius Checkbox", page_icon="☑️", layout="wide")

import sheets  # Google Sheets (після set_page_config — коректна реєстрація st.cache_data у sheets)


@st.cache_data(ttl=20)
def _cached_audit_log_df():
    return sheets.read_audit_log()


def _audit_lookup_ship_cost(ttn_raw, main_df):
    ttn = str(ttn_raw).strip()
    if not ttn or ttn.lower() == "nan":
        return None
    try:
        m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
        if m.empty:
            return None
        v = m.iloc[0]["Вартість"]
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _audit_lookup_receipt_sum(detail_raw, chk_df):
    """Сума з архіву Checkbox, якщо у «Деталі» є URL чека."""
    if chk_df is None or chk_df.empty:
        return None
    d = str(detail_raw).lower()
    for _, cr in chk_df.iterrows():
        link = str(cr.get("Посилання", "")).lower().strip()
        if link and link in d:
            try:
                return float(cr.get("Сума", 0) or 0)
            except Exception:
                continue
    return None


def _audit_num_from_cell(val):
    if val is None:
        return float("nan")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return float("nan")
    try:
        return float(s.replace(",", ".").strip())
    except (TypeError, ValueError):
        return float("nan")


def _enrich_audit_table(adf, main_df, chk_df):
    """Додає / уточнює «Вартість ТТН» та «Сума чеку»: спочатку збережені в журналі, інакше з таблиці + Checkbox."""
    out = adf.head(500).copy()
    ships, sums = [], []
    for _, r in out.iterrows():
        saved_ship = _audit_num_from_cell(r.get("Вартість ТТН"))
        saved_rcpt = _audit_num_from_cell(r.get("Сума чеку"))
        ttn = str(r.get("ТТН", "")).strip()
        detail = r.get("Деталі", "")

        if not pd.isna(saved_ship):
            ship_f = saved_ship
        else:
            sc = _audit_lookup_ship_cost(ttn, main_df)
            ship_f = float(sc) if sc is not None else float("nan")

        if not pd.isna(saved_rcpt):
            rcpt_f = saved_rcpt
        else:
            rs = _audit_lookup_receipt_sum(detail, chk_df)
            if rs is None and ttn:
                m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
                if not m.empty:
                    curl = str(m.iloc[0].get("Чек", "")).strip()
                    if curl and curl.lower() != "nan":
                        rs = _audit_lookup_receipt_sum(curl, chk_df)
            rcpt_f = float(rs) if rs is not None else float("nan")

        ships.append(ship_f)
        sums.append(rcpt_f)
    out["Вартість ТТН"] = ships
    out["Сума чеку"] = sums
    return out


def _style_audit_amounts(df):
    """Підсвічує дві останні колонки: зелений збіг, червоний розбіжність (обидва числа є)."""

    def _row_style(row):
        blank = ""
        sty = [blank] * len(row)
        if "Вартість ТТН" not in row.index or "Сума чеку" not in row.index:
            return pd.Series(sty, index=row.index)
        ok = "background-color: #c8e6c9; color: #1b5e20; font-weight: 600"
        bad = "background-color: #ffcdd2; color: #b71c1c; font-weight: 600"
        a = row["Вартість ТТН"]
        b = row["Сума чеку"]
        try:
            fa = float(a) if not pd.isna(a) else None
        except (TypeError, ValueError):
            fa = None
        try:
            fb = float(b) if not pd.isna(b) else None
        except (TypeError, ValueError):
            fb = None
        i_a = row.index.get_loc("Вартість ТТН")
        i_b = row.index.get_loc("Сума чеку")
        if fa is not None and fb is not None:
            c = ok if abs(fa - fb) < 0.01 else bad
            sty[i_a] = c
            sty[i_b] = c
        return pd.Series(sty, index=row.index)

    return df.style.apply(_row_style, axis=1)


# ==========================================
# 🔌 АВТО-ПІДКЛЮЧЕННЯ СЕКРЕТІВ
# ==========================================
def load_secrets_to_config():
    if "UP_TRACKING_TOKEN" in st.secrets: config.UP_TRACKING_TOKEN = st.secrets["UP_TRACKING_TOKEN"]
    if "UP_BEARER_TOKEN" in st.secrets: config.UP_BEARER_TOKEN = st.secrets["UP_BEARER_TOKEN"]
    if "UP_USER_TOKEN" in st.secrets: config.UP_USER_TOKEN = st.secrets["UP_USER_TOKEN"]
    if "UP_UUID" in st.secrets: config.UP_UUID = st.secrets["UP_UUID"]
    if "UP_UUID_SAND" in st.secrets: config.UP_UUID_SAND = st.secrets["UP_UUID_SAND"]
    if "UP_COUNTERPARTY_TOKEN" in st.secrets: config.UP_COUNTERPARTY_TOKEN = st.secrets["UP_COUNTERPARTY_TOKEN"]
    if "UP_SENDER_UUID" in st.secrets: config.UP_SENDER_UUID = st.secrets["UP_SENDER_UUID"]
    if "UP_CABINET_URL" in st.secrets: config.UP_CABINET_URL = st.secrets["UP_CABINET_URL"]
    if "API_KEY_NP" in st.secrets: config.API_KEY_NP = st.secrets["API_KEY_NP"]
    if "CHECKBOX_LICENSE_KEY" in st.secrets: config.CHECKBOX_LICENSE_KEY = st.secrets["CHECKBOX_LICENSE_KEY"]
    if "CHECKBOX_PASSWORD" in st.secrets: config.CHECKBOX_PASSWORD = st.secrets["CHECKBOX_PASSWORD"]
    if "TURBOSMS_TOKEN" in st.secrets: setattr(config, 'TURBOSMS_TOKEN', st.secrets["TURBOSMS_TOKEN"])
    if "MEEST_API_TOKEN" in st.secrets: config.MEEST_API_TOKEN = st.secrets["MEEST_API_TOKEN"]

load_secrets_to_config()

# ==========================================
# 🔐 АВТОРИЗАЦІЯ
# ==========================================
def check_password():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.markdown("""<style>.stTextInput input {text-align: center;} div[data-testid="stForm"] {border: 1px solid #444; padding: 2rem; border-radius: 10px;}</style>""", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
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


def audit_log(action, ttn="", detail="", ship_cost=None, receipt_sum=None):
    """Журнал дій (аркуш LogisticAudit у книзі Orders)."""
    u = str(st.session_state.get("auth_user", "")).strip() or "?"
    if sheets.append_audit_log(
        u, action, ttn, detail, ship_cost=ship_cost, receipt_sum=receipt_sum
    ):
        _cached_audit_log_df.clear()


# ==========================================
# Автогенерація повідомлень для черги видачі чека
# ==========================================
def ensure_messages_exist(df):
    for i, row in df.iterrows():
        msg_val = str(row["Повідомлення"]).strip()
        is_sent = str(row["Статус СМС"]) == "Отправлено"
        current_status = str(row["Статус"]).lower()
        link = str(row["Чек"]).strip()

        if is_sent:
            continue
        if not (link and len(link) > 5 and link.lower() != "nan"):
            continue
        if not utils.status_has_any(current_status, utils.DELIVERED_STATUS_KEYWORDS):
            continue

        short = len(msg_val) <= 5 or msg_val.lower() == "nan"
        msg_missing_current_link = link not in msg_val
        if short or msg_missing_current_link:
            df.at[i, "Повідомлення"] = f"Магазин Alius. Ваш чек: {link}"
            if len(str(row["Телефон"])) > 5:
                df.at[i, "Статус СМС"] = "Не отправлено"
    return df

# ==========================================
# 🌐 API ФУНКЦІЇ
# ==========================================

# --- CHECKBOX ---
@st.cache_data(ttl=300)
def fetch_checkbox_archive():
    if not config.CHECKBOX_LOGIN or not config.CHECKBOX_LICENSE_KEY: return None
    auth_url = "https://api.checkbox.in.ua/api/v1/cashier/signin"
    try:
        r = utils.make_request("POST", auth_url, json={"login": config.CHECKBOX_LOGIN, "password": config.CHECKBOX_PASSWORD})
        if not r or r.status_code != 200: return None
        token = r.json().get('access_token')
        date_from = (datetime.now() - timedelta(days=30)).isoformat()
        r_rec = utils.make_request("GET", "https://api.checkbox.in.ua/api/v1/receipts", 
                             headers={"Authorization": f"Bearer {token}", "X-License-Key": config.CHECKBOX_LICENSE_KEY},
                             params={"desc": "true", "limit": 100, "from_date": date_from})
        if not r_rec or r_rec.status_code != 200: return None
        parsed = []
        for item in r_rec.json().get('results', []):
            raw_date = item.get('created_at', '')
            try: 
                dt = datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=3)
                f_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception: f_date = utils.normalize_date(raw_date)
            parsed.append({
                "ID": item.get('id'), "Дата": f_date, "Сума": item.get('total_sum', 0) / 100,
                "Посилання": f"https://check.checkbox.ua/{item.get('id')}"
            })
        return pd.DataFrame(parsed)
    except Exception: return None


def used_checkbox_links_from_df(df):
    used = set()
    for _, r in df.iterrows():
        lk = str(r.get("Чек", "")).strip()
        if lk and len(lk) > 5 and lk.lower() != "nan":
            used.add(lk)
    return used


def tab1_unattached_receipt_picker_rows(df, checkbox_df, amount):
    """Чеки з Checkbox: сума збігається з відправленням, посилання ще не в колонці «Чек»."""
    if checkbox_df is None or checkbox_df.empty:
        return []
    try:
        amt = float(str(amount).replace(",", ".").strip())
    except Exception:
        return []
    if amt <= 0:
        return []
    used = used_checkbox_links_from_df(df)
    try:
        sums = pd.to_numeric(checkbox_df["Сума"], errors="coerce")
    except Exception:
        sums = checkbox_df["Сума"]
    cand = checkbox_df.loc[(sums - amt).abs() < 0.01]
    seen = set()
    raw_rows = []
    for _, r in cand.iterrows():
        link = str(r.get("Посилання", "")).strip()
        if not link or link in used or link in seen:
            continue
        seen.add(link)
        dt_s = str(r.get("Дата", "")).strip()
        dt_obj = pd.to_datetime(dt_s, errors="coerce")
        if pd.isna(dt_obj):
            if len(dt_s) >= 16:
                dt_label = dt_s[:16].strip()
            elif len(dt_s) >= 10:
                dt_label = dt_s[:10]
            else:
                dt_label = dt_s or "—"
        else:
            dt_label = dt_obj.strftime("%Y-%m-%d %H:%M")
        try:
            sm = float(r.get("Сума", 0) or 0)
        except Exception:
            sm = 0.0
        raw_rows.append({"link": link, "dt_label": dt_label, "sm": sm, "sort_ts": dt_obj})

    def _sort_ts(x):
        ts = x["sort_ts"]
        return ts if not pd.isna(ts) else pd.Timestamp(1970, 1, 1)

    raw_rows.sort(key=_sort_ts, reverse=True)

    base_n = {}
    out = []
    for t in raw_rows:
        sum_txt = f"{t['sm']:.2f}".replace(".", ",")
        base = f"{t['dt_label']} — {sum_txt} грн"
        base_n[base] = base_n.get(base, 0) + 1
        n = base_n[base]
        label = base if n == 1 else f"{base} ({n})"
        out.append({"link": t["link"], "label": label})
    return out


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
    date_from = (datetime.now() - timedelta(days=60)).strftime("%d.%m.%Y")
    date_to = datetime.now().strftime("%d.%m.%Y")
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
    headers = {}
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
    d_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
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
    if not config.UP_USER_TOKEN:
        return None, "Немає UP_USER_TOKEN у Secrets."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN у Secrets."
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    params = {"token": config.UP_USER_TOKEN}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=config.UP_COUNTERPARTY_TOKEN or None,
        include_content_type=True,
    )
    try:
        r = utils.make_request("POST", url, headers=headers, params=params, json=body)
        if not r:
            return None, "Немає відповіді від сервера."
        if r.status_code == 200 or r.status_code == 201:
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        try:
            err_js = r.json()
        except Exception:
            err_js = {"text": r.text[:800]}
        return None, f"HTTP {r.status_code}: {err_js}"
    except Exception as e:
        return None, str(e)[:500]


def _up_barcode_from_create_response(data):
    if not isinstance(data, dict):
        return None
    for key in ("barcode", "barCode", "shipmentNumber"):
        v = data.get(key)
        if v and str(v).strip():
            return str(v).strip()
    return None


def _up_build_shipment_dict_from_wizard():
    """Збір тіла POST /shipments з полів майстра (UUID з кабінету eCom)."""
    sender = str(st.session_state.get("upwiz_sender_uuid", "")).strip() or str(
        getattr(config, "UP_SENDER_UUID", "") or ""
    ).strip()
    recipient = str(st.session_state.get("upwiz_recipient_uuid", "")).strip()
    if not sender or not recipient:
        return None, "Заповни UUID відправника та UUID отримувача (вкладка «Підключення API»)."
    try:
        w_kg = float(str(st.session_state.get("upwiz_weight_kg", 0.5)).replace(",", ".").strip() or 0.5)
    except Exception:
        w_kg = 0.5
    grams = max(1, int(round(w_kg * 1000)))
    try:
        L = int(float(str(st.session_state.get("upwiz_length_cm", 30)).replace(",", ".").strip() or 30))
    except Exception:
        L = 30
    L = max(1, min(L, 150))
    delivery = st.session_state.get("upwiz_delivery", "W2D")
    paid = bool(st.session_state.get("upwiz_paid_recipient", False))
    body = {
        "sender": {"uuid": sender},
        "recipient": {"uuid": recipient},
        "deliveryType": delivery,
        "paidByRecipient": paid,
        "nonCashPayment": False,
        "parcels": [{"weight": grams, "length": L}],
    }
    return body, ""


def render_up_shipments_tab():
    """Оформлення УП у стилі кабінету ok.ukrposhta + POST eCom."""
    import json as _json

    _cabinet_default = (
        "https://ok.ukrposhta.ua/ua/lk_old/standart/add/c0e7298c-f821-4879-8d04-efe1be943123#/know-index"
    )
    cabinet_url = str(getattr(config, "UP_CABINET_URL", "") or "").strip() or _cabinet_default

    st.markdown(
        '<div style="background:linear-gradient(180deg,#fffdf7,#f5f2e8);border:1px solid #e3dcc8;border-radius:12px;'
        'padding:16px 18px;margin-bottom:12px;">'
        '<div style="color:#0057b7;font-weight:800;font-size:1.28rem;">Стандартне відправлення</div>'
        '<div style="color:#555;font-size:0.92rem;margin-top:6px;line-height:1.45;">'
        "Оформлення кроками, як у кабінеті Укрпошти; відправлення в eCom — за зібраним JSON (UUID клієнтів з кабінету бізнесу)."
        "</div></div>",
        unsafe_allow_html=True,
    )
    st.link_button("Відкрити кабінет Укрпошти (стандарт)", cabinet_url)
    st.caption(
        "Потрібні **UP_BEARER_TOKEN**, **UP_USER_TOKEN**; опційно **UP_SENDER_UUID** (дефолт UUID відправника) та **UP_CABINET_URL** (своє посилання кабінету замість вбудованого прикладу)."
    )

    if "upwiz_sender_uuid" not in st.session_state:
        st.session_state.upwiz_sender_uuid = str(getattr(config, "UP_SENDER_UUID", "") or "")
    if "up_shipment_json_draft" not in st.session_state:
        st.session_state.up_shipment_json_draft = _json.dumps(
            {
                "sender": {"uuid": "UUID-відправника"},
                "recipient": {"uuid": "UUID-отримувача"},
                "deliveryType": "W2D",
                "paidByRecipient": False,
                "nonCashPayment": False,
                "parcels": [{"weight": 500, "length": 30}],
            },
            indent=2,
            ensure_ascii=False,
        )

    mode = st.radio(
        "Режим",
        ["Майстер (як у кабінеті)", "JSON вручну"],
        horizontal=True,
        key="up_ui_mode",
    )

    if mode.startswith("Майстер"):
        t1, t2, t3, t4, t5 = st.tabs(
            ["Доставка", "Отримувач", "Адреса", "Посилка", "Підключення API"]
        )
        with t1:
            st.markdown(
                '<p style="color:#0057b7;font-weight:700;border-bottom:3px solid #ffcc00;padding-bottom:6px;margin:0 0 12px 0;">Куди та як веземо</p>',
                unsafe_allow_html=True,
            )
            st.selectbox(
                "Тип доставки (deliveryType)",
                ["W2D", "W2W", "D2D", "D2W"],
                index=0,
                key="upwiz_delivery",
            )
            st.checkbox("Доставку оплачує отримувач", key="upwiz_paid_recipient")
        with t2:
            st.markdown(
                '<p style="color:#0057b7;font-weight:700;border-bottom:3px solid #ffcc00;padding-bottom:6px;margin:0 0 12px 0;">Отримувач</p>',
                unsafe_allow_html=True,
            )
            x1, x2 = st.columns(2)
            with x1:
                st.text_input("Прізвище", key="upwiz_lastname", placeholder="Петренко")
            with x2:
                st.text_input("Ім’я", key="upwiz_firstname", placeholder="Петро")
            st.text_input("По батькові", key="upwiz_middlename", placeholder="необов’язково")
            st.text_input("Мобільний телефон", key="upwiz_phone", placeholder="380671112233")
        with t3:
            st.markdown(
                '<p style="color:#0057b7;font-weight:700;border-bottom:3px solid #ffcc00;padding-bottom:6px;margin:0 0 12px 0;">Адреса</p>',
                unsafe_allow_html=True,
            )
            st.text_input("Індекс", key="upwiz_postcode", placeholder="01001", max_chars=5)
            y1, y2 = st.columns(2)
            with y1:
                st.text_input("Область", key="upwiz_region")
            with y2:
                st.text_input("Місто / село", key="upwiz_city")
            st.text_input("Вулиця", key="upwiz_street")
            z1, z2 = st.columns(2)
            with z1:
                st.text_input("Будинок", key="upwiz_house")
            with z2:
                st.text_input("Квартира", key="upwiz_apartment")
            st.caption(
                "Поля адреси для орієнтації в програмі; у JSON eCom підставляються лише UUID у кроці «Підключення API»."
            )
        with t4:
            st.markdown(
                '<p style="color:#0057b7;font-weight:700;border-bottom:3px solid #ffcc00;padding-bottom:6px;margin:0 0 12px 0;">Параметри посилки</p>',
                unsafe_allow_html=True,
            )
            u1, u2 = st.columns(2)
            with u1:
                st.number_input("Вага, кг", min_value=0.01, max_value=30.0, value=0.5, step=0.1, key="upwiz_weight_kg")
            with u2:
                st.number_input("Довжина, см", min_value=1, max_value=150, value=30, key="upwiz_length_cm")
            st.number_input("Оголошена вартість (грн) — у колонку «Вартість» у таблиці", min_value=0.0, value=0.0, step=1.0, key="upwiz_declared_uah")
        with t5:
            st.markdown(
                '<p style="color:#0057b7;font-weight:700;border-bottom:3px solid #ffcc00;padding-bottom:6px;margin:0 0 12px 0;">Підключення API eCom</p>',
                unsafe_allow_html=True,
            )
            st.text_input(
                "UUID відправника (sender)",
                key="upwiz_sender_uuid",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            )
            st.text_input(
                "UUID отримувача (recipient)",
                key="upwiz_recipient_uuid",
                placeholder="скопіюй з кабінету Укрпошти",
            )
            if st.button("Зібрати JSON з форми", type="secondary", key="upwiz_build_json"):
                body, err = _up_build_shipment_dict_from_wizard()
                if err:
                    st.error(err)
                else:
                    st.session_state.up_shipment_json_draft = _json.dumps(
                        body, indent=2, ensure_ascii=False
                    )
                    st.success("Готово — JSON нижче оновлено.")

    with st.expander(
        "JSON для POST /shipments (можна відредагувати)",
        expanded=not mode.startswith("Майстер"),
    ):
        st.text_area("json", key="up_shipment_json_draft", height=260, label_visibility="collapsed")

    st.divider()
    st.markdown("**Після створення ТТН** — додати рядок у Google-таблицю (якщо треба інший телефон/сума, підправ тут):")
    cph, cco = st.columns(2)
    with cph:
        st.text_input("Телефон у таблицю (якщо порожньо — з кроку «Отримувач»)", key="tab_up_new_phone", placeholder="380…")
    with cco:
        st.text_input("Вартість у таблицю (якщо порожньо — з «Оголошена вартість»)", key="tab_up_new_cost", placeholder="0")

    if st.button("Створити відправлення (POST)", type="primary", key="tab_up_post_btn"):
        raw = str(st.session_state.get("up_shipment_json_draft", "")).strip()
        try:
            body = _json.loads(raw)
        except _json.JSONDecodeError as e:
            st.error(f"Некоректний JSON: {e}")
        else:
            data, err = up_post_shipment_create(body)
            if err:
                st.error(err)
            else:
                st.session_state.up_last_create_response = data
                st.toast("Укрпошта: відповідь отримано", icon="✅")

    resp = st.session_state.get("up_last_create_response")
    if resp is not None:
        with st.expander("Остання відповідь API", expanded=True):
            st.json(resp)
        bc = _up_barcode_from_create_response(resp)
        if bc:
            if len(bc) == 12 and bc.isdigit():
                bc = "0" + bc
            st.caption(f"**ТТН:** `{bc}`")

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
                    try:
                        c_w = float(
                            str(st.session_state.get("upwiz_declared_uah", 0)).replace(",", ".").strip() or 0
                        )
                    except Exception:
                        c_w = 0.0
                    try:
                        c_t = float(
                            str(st.session_state.get("tab_up_new_cost", "")).replace(",", ".").strip() or -1
                        )
                    except Exception:
                        c_t = -1.0
                    cost_v = c_t if c_t >= 0 else c_w
                    st.session_state.df.loc[len(st.session_state.df)] = {
                        "ТТН": bc,
                        "Служба": "УП",
                        "Статус": "Нове",
                        "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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


# --- MEEST: SELENIUM (ПРАВИЛЬНА ВЕРСІЯ ДЛЯ СЕРВЕРА) ---
def get_meest_status(ttn):
    chrome_options = Options()
    
    # Налаштування для сервера (ОБОВ'ЯЗКОВО ТАКІ)
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Маскування
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Шлях до Chromium (встановлюється з packages.txt)
    chrome_options.binary_location = "/usr/bin/chromium"
    
    driver = None
    status_result = "Не знайдено"
    
    try:
        # Вказуємо шлях до драйвера
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        url = f"https://meestposhta.com.ua/search?query={ttn}"
        driver.get(url)
        
        time.sleep(8) 
        
        content = driver.execute_script("return document.body.innerText")
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        
        for i in range(len(lines)):
            current_line = lines[i]
            
            if "Поточний статус:" in current_line or "Статус:" in current_line:
                if len(current_line) > 17:
                    status_result = current_line.replace("Поточний статус:", "").strip()
                elif i + 1 < len(lines):
                    status_result = lines[i+1]
                else:
                    status_result = current_line
                break
                
            if any(word in current_line for word in ["Відправлено", "Прибуло", "Митне", "оформлення", "отримано", "у відділенні"]):
                status_result = current_line
                break
                
        res_low = status_result.lower()
        if "отримано" in res_low: return "Отримано", "", "", 0.0
        if "у відділенні" in res_low: return "У відділенні", "", "", 0.0
        if "в дорозі" in res_low: return "В дорозі", "", "", 0.0
        
        return status_result[:60], "", "", 0.0

    except Exception as e:
        return f"Error: {str(e)[:50]}", "", "", 0.0
    finally:
        if driver:
            driver.quit()

def fetch_new_orders_meest(existing_ttns):
    return []

# ==========================================
# 📊 ЛОГІКА ДАНИХ
# ==========================================

def ensure_columns(df):
    for c in config.COLS:
        if c not in df.columns:
            if c == "Дія": df[c] = False
            elif c == "Вартість": df[c] = 0.0
            else: df[c] = ""
    return df

def restore_leading_zero(val):
    s = str(val).replace("'", "").strip()
    if len(s) == 12 and s.isdigit(): return "0" + s
    return s


def normalize_table_column_order(order):
    if not order:
        return list(config.COLS)
    seen = []
    for c in order:
        if c in config.COLS and c not in seen:
            seen.append(c)
    for c in config.COLS:
        if c not in seen:
            seen.append(c)
    return seen


def get_table_column_order():
    if "table_column_order" in st.session_state:
        return normalize_table_column_order(st.session_state.table_column_order)
    user = str(st.session_state.get("auth_user", "")).strip()
    loaded = sheets.load_table_column_order(user) if user else None
    order = normalize_table_column_order(loaded or config.COLS)
    st.session_state.table_column_order = order
    return order


def persist_table_column_order(order):
    order = normalize_table_column_order(order)
    st.session_state.table_column_order = order
    user = str(st.session_state.get("auth_user", "")).strip()
    if user:
        sheets.save_table_column_order(user, order)
    return order


def apply_table_column_order(df, order=None):
    order = order or get_table_column_order()
    cols = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    return df[cols + rest]


def _coalesce_edited_table(editor_value, base: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """Повертає повну таблицю з data_editor (return value або session_state з edited_rows)."""
    base = (base if base is not None else st.session_state.get("df")).copy()
    if editor_value is None:
        return None
    if isinstance(editor_value, pd.DataFrame):
        return editor_value.copy()
    if not isinstance(editor_value, dict):
        return None
    df = base.copy()
    for idx, changes in (editor_value.get("edited_rows") or {}).items():
        row_pos = int(idx)
        row_key = _resolve_row_index(df, row_pos)
        if row_key is None:
            continue
        for col, val in (changes or {}).items():
            if col in df.columns:
                df.at[row_key, col] = val
    for idx in sorted((editor_value.get("deleted_rows") or []), reverse=True):
        i = int(idx)
        if i in df.index:
            df = df.drop(index=i)
    added = editor_value.get("added_rows") or []
    if added:
        df = pd.concat([df, pd.DataFrame(added)], ignore_index=True)
    return df.reset_index(drop=True)


def _prepare_table_df_for_save(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df.copy())
    df = apply_table_column_order(df)
    if "ТТН" in df.columns:
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
            df[col] = df[col].astype(str).replace("nan", "").str.strip()
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
            .replace({"True": True, "False": False, "": False, "FALSE": False, "TRUE": True, 1: True, 0: False})
            .infer_objects(copy=False)
            .fillna(False)
            .astype(bool)
        )
    if "Дата" in df.columns:
        df["Дата"] = df["Дата"].apply(utils.normalize_date)
    return ensure_messages_exist(df)


def _table_data_changed(candidate: pd.DataFrame, baseline: pd.DataFrame) -> bool:
    a = _prepare_table_df_for_save(candidate)
    b = _prepare_table_df_for_save(baseline)
    if len(a) != len(b):
        return True
    cols = [c for c in config.COLS if c in a.columns and c in b.columns]
    a = a[cols].reset_index(drop=True)
    b = b[cols].reset_index(drop=True)
    for col in cols:
        if col == "Вартість":
            if not pd.to_numeric(a[col], errors="coerce").fillna(0).equals(
                pd.to_numeric(b[col], errors="coerce").fillna(0)
            ):
                return True
        elif col == "Дія":
            if not a[col].astype(bool).equals(b[col].astype(bool)):
                return True
        else:
            if not a[col].astype(str).equals(b[col].astype(str)):
                return True
    return False


def _resolve_row_index(df: pd.DataFrame, pos: int):
    """Індекс рядка в df за позицією в таблиці (0, 1, 2…)."""
    if pos in df.index:
        return pos
    if 0 <= pos < len(df):
        return df.index[pos]
    return None


def _normalize_table_cell(col: str, val):
    if val is None:
        return ""
    if col == "ТТН":
        return restore_leading_zero(str(val))
    if col == "Номер накладної":
        return utils.normalize_invoice_number(str(val))
    if col == "Вартість":
        s = str(val).replace(",", ".").strip()
        return float(pd.to_numeric(s, errors="coerce") or 0.0)
    if col == "Дія":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "так")
    if col == "Дата":
        return utils.normalize_date(str(val))
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def _refresh_row_message_if_needed(df: pd.DataFrame, row_key) -> bool:
    """Оновлює «Повідомлення» для одного рядка після зміни чека."""
    if row_key is None or "Чек" not in df.columns or "Повідомлення" not in df.columns:
        return False
    row = df.loc[row_key]
    if str(row.get("Статус СМС", "")).strip() == "Отправлено":
        return False
    link = str(row.get("Чек", "")).strip()
    if not link or len(link) < 5 or link.lower() == "nan":
        return False
    if not utils.status_has_any(str(row.get("Статус", "")).lower(), utils.DELIVERED_STATUS_KEYWORDS):
        return False
    msg_val = str(row.get("Повідомлення", "")).strip()
    if len(msg_val) > 5 and msg_val.lower() != "nan" and link in msg_val:
        return False
    new_msg = f"Магазин Alius. Ваш чек: {link}"
    df.at[row_key, "Повідомлення"] = new_msg
    if "Статус СМС" in df.columns and len(str(row.get("Телефон", "")).strip()) > 5:
        df.at[row_key, "Статус СМС"] = "Не отправлено"
    return True


def _invalidate_tab2_display_df():
    st.session_state.pop("_tab2_display_df", None)
    st.session_state.pop("_tab2_display_order", None)


def _tab2_display_dataframe(col_order):
    """Стабільний той самий DataFrame для data_editor — менше перемальовок і стрибків прокрутки."""
    order_key = tuple(col_order)
    disp = st.session_state.get("_tab2_display_df")
    if (
        isinstance(disp, pd.DataFrame)
        and st.session_state.get("_tab2_display_order") == order_key
        and len(disp) == len(st.session_state.df)
    ):
        return disp
    disp = apply_table_column_order(st.session_state.df, col_order).copy()
    st.session_state._tab2_display_df = disp
    st.session_state._tab2_display_order = order_key
    return disp


def _mirror_df_rows_to_tab2_display(row_positions: list[int]):
    """Оновити лише змінені рядки в кеші таблиці (той самий об'єкт)."""
    disp = st.session_state.get("_tab2_display_df")
    df = st.session_state.df
    if not isinstance(disp, pd.DataFrame):
        return
    for row_pos in row_positions:
        rk_df = _resolve_row_index(df, int(row_pos))
        rk_disp = _resolve_row_index(disp, int(row_pos))
        if rk_df is None or rk_disp is None:
            continue
        for col in disp.columns:
            if col in df.columns:
                disp.at[rk_disp, col] = df.at[rk_df, col]


def _cell_values_equal(col: str, a, b) -> bool:
    return str(_normalize_table_cell(col, a)) == str(_normalize_table_cell(col, b))


def _merge_edited_rows_dicts(*sources: dict) -> dict:
    """Об'єднати кілька edited_rows (рядок → {колонка: значення})."""
    merged = {}
    for src in sources:
        if not src:
            continue
        for idx, changes in src.items():
            row = int(idx)
            if row not in merged:
                merged[row] = {}
            merged[row].update(changes or {})
    return merged


def _edited_rows_from_main_state(main_state) -> dict:
    if not isinstance(main_state, dict):
        return {}
    raw = main_state.get("edited_rows") or {}
    return {int(k): dict(v) for k, v in raw.items()}


def _diff_edited_rows(baseline: pd.DataFrame, current: pd.DataFrame) -> dict:
    """Порівняння таблиці з редактором і baseline — зміни з останнього збереження."""
    b = apply_table_column_order(baseline).reset_index(drop=True)
    c = apply_table_column_order(current).reset_index(drop=True)
    n = min(len(b), len(c))
    edited_rows = {}
    for i in range(n):
        changes = {}
        for col in config.COLS:
            if col not in b.columns or col not in c.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, b.at[i, col], c.at[i, col]):
                changes[col] = c.at[i, col]
        if changes:
            edited_rows[i] = changes
    return edited_rows


def _apply_partial_edits_to_df(edited_rows: dict) -> tuple[dict, list]:
    """Оновлює session_state.df; повертає (cells для Google, extra_cells)."""
    df = st.session_state.df
    extra_sheet_cells = []
    norm_for_sheet = {}

    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        row_key = _resolve_row_index(df, row_pos)
        if row_key is None:
            continue
        norm_for_sheet[row_pos] = {}
        for col, val in (changes or {}).items():
            if col not in df.columns or col == "Дія":
                continue
            norm = _normalize_table_cell(col, val)
            df.at[row_key, col] = norm
            norm_for_sheet[row_pos][col] = norm
        if "Чек" in (changes or {}) and _refresh_row_message_if_needed(df, row_key):
            extra_sheet_cells.append(
                (row_pos, "Повідомлення", df.at[row_key, "Повідомлення"])
            )
            if "Статус СМС" in df.columns:
                extra_sheet_cells.append(
                    (row_pos, "Статус СМС", df.at[row_key, "Статус СМС"])
                )
    if edited_rows:
        _mirror_df_rows_to_tab2_display([int(i) for i in edited_rows.keys()])
    return norm_for_sheet, extra_sheet_cells


def _tab2_reset_editor_baseline():
    st.session_state._tab2_editor_baseline = st.session_state.df.copy()


def _editor_dataframe_from_value(value) -> pd.DataFrame | None:
    """data_editor може повернути DataFrame або Styler — нормалізуємо."""
    if isinstance(value, pd.DataFrame):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, pd.DataFrame):
        return data
    return None


def _filter_edited_rows_vs_baseline(
    edited_rows: dict, baseline: pd.DataFrame | None = None
) -> dict:
    """Лишити комірки, що відрізняються від baseline (знімок після останнього збереження)."""
    if not edited_rows:
        return {}
    if baseline is None or not isinstance(baseline, pd.DataFrame):
        baseline = st.session_state.get("_tab2_editor_baseline", st.session_state.df)
    base = apply_table_column_order(baseline).reset_index(drop=True)
    filtered = {}
    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        if row_pos < 0 or row_pos >= len(base):
            continue
        real = {}
        for col, val in (changes or {}).items():
            if col not in base.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, val, base.at[row_pos, col]):
                real[col] = val
        if real:
            filtered[row_pos] = real
    return filtered


def _collect_pending_table_edits(editor_value=None, edited_df=None) -> dict:
    """Зібрати зміни: snapshot/callback edited_rows + diff від baseline."""
    baseline = st.session_state.get("_tab2_editor_baseline")
    if baseline is None or not isinstance(baseline, pd.DataFrame):
        baseline = st.session_state.df

    snap = st.session_state.get("_tab2_main_snapshot")
    editor_state = snap if isinstance(snap, dict) else editor_value
    from_main = _edited_rows_from_main_state(editor_state)
    current_df = _editor_dataframe_from_value(edited_df)
    from_diff = _diff_edited_rows(baseline, current_df) if current_df is not None else {}
    return _filter_edited_rows_vs_baseline(_merge_edited_rows_dicts(from_main, from_diff), baseline)


def _apply_partial_edits(edited_rows: dict, *, write_google: bool = True) -> bool:
    if not edited_rows:
        return False
    norm_for_sheet, extra_sheet_cells = _apply_partial_edits_to_df(edited_rows)
    if write_google:
        if not sheets.update_table_cell_edits(norm_for_sheet, extra_sheet_cells, silent=True):
            return False
    _tab2_reset_editor_baseline()
    return True


def _autosave_table_edits_partial(editor_value=None, edited_df=None) -> bool:
    """Зберігає лише змінені комірки."""
    if isinstance(editor_value, dict) and (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        return _autosave_table_if_changed(editor_value, show_toast=False)

    edited_rows = _collect_pending_table_edits(editor_value, edited_df)
    return _apply_partial_edits(edited_rows, write_google=True)


def _autosave_table_from_editor(edited_df) -> bool:
    """Autosave таблиці (fallback після data_editor, якщо callback не встиг)."""
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)

    edited_rows = _collect_pending_table_edits(main, edited_df)
    return _apply_partial_edits(edited_rows, write_google=True)


def _autosave_table_if_changed(editor_value=None, *, show_toast: bool = False) -> bool:
    if isinstance(editor_value, dict) and editor_value.get("edited_rows") and not (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        if _autosave_table_edits_partial(editor_value):
            if show_toast:
                st.session_state._tab2_autosave_ok = True
            return True
        return False
    edited = _coalesce_edited_table(editor_value)
    if edited is None:
        return False
    prepared = _prepare_table_df_for_save(edited)
    if not _table_data_changed(prepared, st.session_state.df):
        return False
    if sheets.save_manual(prepared, clear_cache=False, merge_session=True):
        _invalidate_tab2_display_df()
        _tab2_reset_editor_baseline()
        if show_toast:
            st.session_state._tab2_autosave_ok = True
        return True
    return False


def _try_sync_column_order_from_editor(editor_df: pd.DataFrame | None = None):
    """Порядок колонок — лише з dict-стану редактора (drag), не з return DataFrame."""
    main = st.session_state.get("main")
    if not isinstance(main, dict):
        return
    cols = [str(c) for c in (main.get("column_order") or []) if c in config.COLS]
    if not cols:
        return
    norm = normalize_table_column_order(cols)
    if norm != get_table_column_order():
        persist_table_column_order(norm)
        _invalidate_tab2_display_df()
        st.session_state.df = apply_table_column_order(st.session_state.df, norm)


def load_data():
    if 'df' not in st.session_state:
        df = sheets.load_data_from_gsheets()
        if "Номер ТТН" in df.columns: df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
        df = ensure_columns(df)
        df = apply_table_column_order(df, get_table_column_order())
        # Залишаємо leading_zero
        df['ТТН'] = df['ТТН'].apply(restore_leading_zero)
        
        text_cols = ["ТТН", "Служба", "Статус", "Дата", "Телефон", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування", "Номер накладної"]
        for col in text_cols:
            df[col] = df[col].astype(str).replace('nan', '')

        df["Номер накладної"] = df["Номер накладної"].apply(utils.normalize_invoice_number)

        if 'Вартість' in df.columns:
            df['Вартість'] = df['Вартість'].astype(str).str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
            df['Вартість'] = pd.to_numeric(df['Вартість'], errors='coerce').fillna(0.0)

        df['Дія'] = df['Дія'].replace({'True': True, 'False': False, '': False, 'FALSE': False, 'TRUE': True, 1: True, 0: False}).infer_objects(copy=False).fillna(False).astype(bool)
        df['Дата'] = df['Дата'].apply(utils.normalize_date)
        
        df = ensure_messages_exist(df)
        st.session_state.df = df
        _invalidate_tab2_display_df()
    else:
        st.session_state.df = ensure_columns(st.session_state.df)
        if "Номер накладної" in st.session_state.df.columns:
            st.session_state.df["Номер накладної"] = st.session_state.df["Номер накладної"].apply(
                utils.normalize_invoice_number
            )

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
        ``("НП", "УП")`` для швидкого режиму без Selenium Meest.
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
            
        if s and not s.startswith("Error") and s != "Не знайдено":
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
        
    work_df = ensure_messages_exist(work_df)
    st.session_state.df = work_df
    saved = sheets.save_manual(st.session_state.df)
    if show_ui: status_text.empty(); progress_bar.empty()
    return count_sms, saved

st.markdown(
    """<style>
button[data-baseweb="tab"] { font-size: 24px !important; font-weight: 700 !important; }
div.stButton > button { font-size: 16px !important; font-weight: 500 !important; }
section[data-testid="stSidebar"] div.stButton > button { width: 100% !important; border: 1px solid #4CAF50 !important; }
/* Червона кнопка «Вибрати чек зі списку» (черга видачі чека) */
button[data-testid="baseButton-secondary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="baseButton-primary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="stBaseButton-secondary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="stBaseButton-primary"][aria-label*="Вибрати чек зі списку"] {
  background-color: #c62828 !important;
  color: #ffffff !important;
  border: 1px solid #8e0000 !important;
}
button[data-testid="baseButton-secondary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="baseButton-primary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="stBaseButton-secondary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="stBaseButton-primary"][aria-label*="Вибрати чек зі списку"]:hover {
  background-color: #b71c1c !important;
  border-color: #5c0000 !important;
}
</style>""",
    unsafe_allow_html=True,
)

def render_smart_buttons(phone, message, row_key=None):
    if not phone or len(str(phone)) < 10: st.caption("Невірний телефон"); return
    raw_phone = str(phone); digits = ''.join(filter(str.isdigit, raw_phone))
    if len(digits) == 10 and digits.startswith('0'): digits = '38' + digits
    if len(digits) != 12: st.caption(f"Формат? {raw_phone}"); return
    msg_safe = str(message).replace("\\", "\\\\").replace('\n', '\\n').replace('\r', '').replace("'", "\\'")
    token_raw = f"{digits}_{row_key if row_key is not None else 'default'}"
    token = re.sub(r"[^0-9A-Za-z_]", "_", token_raw)
    js_code = f"""<script>function clickHandler_{token}(type) {{ const text = '{msg_safe}'; const url = type === 'viber' ? 'viber://chat?number=%2B{digits}' : 'sms:+{digits}'; const el = document.createElement('textarea'); el.value = text; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el); const link = document.createElement('a'); link.href = url; document.body.appendChild(link); link.click(); document.body.removeChild(link); }}</script><div style="display: flex; flex-direction: column; gap: 8px;"><button onclick="clickHandler_{token}('viber')" style="background-color: #7360f2; color: white; border: none; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">💬 Viber</button><button onclick="clickHandler_{token}('sms')" style="background-color: #f0f2f6; color: #31333F; border: 1px solid #ccc; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">📩 SMS</button></div>"""
    st.components.v1.html(js_code, height=100)


def render_copyable_invoice(invoice_num, row_key):
    inv = utils.normalize_invoice_number(invoice_num)
    if not inv or inv.lower() == 'nan':
        return
    inv_safe = html.escape(inv).replace("\\", "\\\\").replace("'", "\\'")
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"invoice_{row_key}")
    js_code = f"""
<script>
function showCopied_{token}() {{
  const el = document.getElementById('copied_{token}');
  if (!el) return;
  el.style.opacity = '1';
  setTimeout(() => {{ el.style.opacity = '0'; }}, 1200);
}}
function copyInvoice_{token}() {{
  const text = '{inv_safe}';
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text);
    showCopied_{token}();
    return;
  }}
  const el = document.createElement('textarea');
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  showCopied_{token}();
}}
</script>
<div style="margin-top: 4px; display: flex; align-items: center; gap: 8px;">
  <button onclick="copyInvoice_{token}()"
          title="Натисніть, щоб скопіювати номер"
          style="background: transparent; border: none; color: #1f77b4; cursor: pointer; padding: 0; font: inherit; text-decoration: underline; white-space: nowrap; line-height: 1.35;">
    📄 Накладна: {inv_safe}
  </button>
  <span id="copied_{token}" style="opacity: 0; transition: opacity .2s ease; color: #2e7d32; font-size: 13px; font-weight: 600;">✅ Скопійовано</span>
</div>
"""
    st.components.v1.html(js_code, height=42)


_CHECKBOX_RECEIPT_HOST = "check.checkbox.ua/"


def tab1_default_sms_text(row) -> str:
    """Текст СМС: колонка «Чек» — джерело правди; без неї не показуємо «леві» URL з «Повідомлення»."""
    msg = str(row.get("Повідомлення", "")).strip()
    link = str(row.get("Чек", "")).strip()
    has_link = link and len(link) > 5 and link.lower() != "nan"
    if has_link:
        if len(msg) > 5 and msg.lower() != "nan" and link in msg:
            return msg
        return f"Магазин Alius. Ваш чек: {link}"
    if len(msg) > 5 and msg.lower() != "nan":
        if _CHECKBOX_RECEIPT_HOST in msg.lower():
            return ""
        return msg
    return ""


def tab1_row_widget_id(row) -> str:
    """Стабільний id для ключів Streamlit (індекс DataFrame змінюється після reset_index)."""
    raw = f"{str(row.get('ТТН', '')).strip()}|{str(row.get('Телефон', '')).strip()}"
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _dataframe_row_pos(df: pd.DataFrame, idx) -> int:
    try:
        loc = df.index.get_loc(idx)
        if isinstance(loc, slice):
            return int(loc.start)
        if hasattr(loc, "__iter__"):
            return int(list(loc)[0])
        return int(loc)
    except Exception:
        return int(idx)


def _tab1_mark_done(idx, row) -> None:
    """Миттєво прибрати з черги; Google + журнал — у фоні (не чекати ~5 с API)."""
    st.session_state.df.at[idx, "Статус СМС"] = "Отправлено"
    row_pos = _dataframe_row_pos(st.session_state.df, idx)
    chk = str(st.session_state.df.at[idx, "Чек"]).strip()
    msg = str(st.session_state.df.at[idx, "Повідомлення"]).strip()
    cells = {row_pos: {"Статус СМС": "Отправлено"}}
    if msg and msg.lower() != "nan":
        cells[row_pos]["Повідомлення"] = msg
    if chk and len(chk) > 5 and chk.lower() != "nan":
        cells[row_pos]["Чек"] = chk

    try:
        sc_done = float(
            str(st.session_state.df.at[idx, "Вартість"]).replace(",", ".").strip()
        )
    except Exception:
        sc_done = None
    detail = chk[:120] if chk else "(без посилання на чек)"
    ttn = str(row.get("ТТН", "")).strip()[:40]
    cells_copy = {k: dict(v) for k, v in cells.items()}

    def _persist_async():
        try:
            if not sheets.update_table_cell_edits(cells_copy, silent=True):
                st.session_state["_tab1_save_failed"] = ttn
            audit_log("смс_готово", ttn, detail, ship_cost=sc_done, receipt_sum=None)
        except Exception:
            st.session_state["_tab1_save_failed"] = ttn

    threading.Thread(target=_persist_async, daemon=True).start()


st.title("Alius Checkbox")
load_data()

if 'auto_refresh' not in st.session_state: st.session_state.auto_refresh = False
if 'last_status_update' not in st.session_state: st.session_state.last_status_update = 0
if '_deferred_save' not in st.session_state: st.session_state._deferred_save = False
st.sidebar.toggle("🔄 Авто-пошук (ВКЛ/ВИКЛ)", key="auto_refresh")

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
            # Без Meest: Selenium на кожну ТТН дуже повільний у фоні.
            sms_count, _ = process_status_updates(
                show_ui=False, services=("НП", "УП")
            )
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
    
    # Імпорт файлу з фільтрацією за статусом
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
                            "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

    with st.expander("➕ Додати ТТН вручну", expanded=True):
        with st.form("manual_add_form", clear_on_submit=True):
            manual_ttn = st.text_input("Введіть ТТН (можна кілька через пробіл)")
            manual_phone = st.text_input("Телефон (необов'язково)")
            manual_cost = st.text_input("Вартість (грн)")
            manual_invoice = st.text_input("Номер накладної (необов'язково)")
            submitted = st.form_submit_button("Додати")
            if submitted and manual_ttn:
                ttns = manual_ttn.replace(",", " ").split(); added = 0
                try:
                    cost_value = float(manual_cost.replace(',', '.')) if manual_cost.strip() else 0.0
                except Exception:
                    cost_value = 0.0
                for t in ttns:
                    # Meest-номер залишаємо без чистки
                    if "721-" in t:
                        t_clean = t.strip()
                        svc = "Meest"
                    else:
                        t_clean = utils.clean_ttn(t)
                        svc = utils.identify_service(t_clean)
                        
                    if t_clean and t_clean not in st.session_state.df['ТТН'].tolist():
                        st.session_state.df.loc[len(st.session_state.df)] = {
                            "ТТН": t_clean, "Служба": svc, "Статус": "Нове", "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Телефон": utils.clean_phone(manual_phone), "Вартість": cost_value, "Номер накладної": utils.normalize_invoice_number(manual_invoice), "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                        }
                        added += 1
                if added > 0:
                    if sheets.save_manual(st.session_state.df):
                        st.success(f"Додано {added} накладних!")
                        time.sleep(1); st.rerun()
                    else:
                        st.error("Помилка збереження! Перевір права.")
                else: st.warning("Вже є в базі")
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
        "🔗 Авто-підбір чеків",
        help="Лише якщо сума чека = «Вартість» до копійки і різниця між датою відправлення та датою чека не більше 2 хв. Інших умов немає.",
    ):
        run_auto_linking(silent=False)
    st.divider()
    if st.button(
        "🔄 Оновити НП та УП",
        help="Швидко: пакетна Нова пошта + запити Укрпошти. Meest тут не оновлюється.",
    ):
        _, saved = process_status_updates(show_ui=True, services=("НП", "УП"))
        if saved:
            st.success("Статуси НП та УП оновлено.")
            time.sleep(0.8)
            st.rerun()
    if st.button(
        "🐢 Оновити Meest",
        help="Повільно: для кожної ТТН Meest відкривається Chromium (Selenium) і очікування сторінки ~8 с.",
    ):
        _, saved = process_status_updates(show_ui=True, services=("Meest",))
        if saved:
            st.success("Статуси Meest оновлено.")
            time.sleep(0.8)
            st.rerun()
    st.caption(
        "Потрібні обидві? Спочатку **НП та УП**, потім **Meest** — так швидше, ніж все в одному проході."
    )
    with st.expander("Усі служби одним запуском (довго)"):
        st.caption("НП + УП + Meest підряд. Meest через Selenium — на кожну ТТН ~8+ с.")
        if st.button("🔄 Оновити все (НП + УП + Meest)", key="status_all_services"):
            _, saved = process_status_updates(show_ui=True, services=None)
            if saved:
                st.success("Усі статуси оновлено.")
                time.sleep(0.8)
                st.rerun()
    st.divider()
    if st.button("🗑️ Видалити відправлені", type="secondary"): new_df = st.session_state.df[st.session_state.df['Статус СМС'] != 'Отправлено'].reset_index(drop=True); sheets.save_manual(new_df); st.success("✅ Очищено!"); time.sleep(1); st.rerun()
    if st.button("🚪 Вийти", type="secondary"): st.session_state.logged_in = False; st.session_state.pop("auth_user", None); st.rerun()


def _autosave_table_on_edit():
    """Зберегти одразу в callback (edited_rows ще в session_state), інакше — fallback у фрагменті."""
    st.session_state.pop("_tab2_saved_in_callback", None)
    main = st.session_state.get("main")
    if isinstance(main, dict):
        st.session_state["_tab2_main_snapshot"] = copy.deepcopy(main)

    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        st.session_state["_tab2_pending_save"] = "full"
        return

    baseline = st.session_state.get("_tab2_editor_baseline", st.session_state.df)
    to_save = _filter_edited_rows_vs_baseline(_edited_rows_from_main_state(main), baseline)
    if to_save and _apply_partial_edits(to_save, write_google=True):
        st.session_state["_tab2_saved_in_callback"] = True
        st.session_state["_tab2_show_toast"] = True
        return

    st.session_state["_tab2_pending_save"] = True


def _mark_tab2_saved():
    try:
        st.toast("Збережено", icon="✅")
    except Exception:
        pass


def _save_table_from_editor(edited_df=None) -> bool:
    """Зберегти таблицю вручну: частково або повністю."""
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)
    pending = _collect_pending_table_edits(main, edited_df)
    if pending and _apply_partial_edits(pending, write_google=True):
        return True
    if isinstance(edited_df, pd.DataFrame) and _autosave_table_from_editor(edited_df):
        return True
    src = _coalesce_edited_table(main) if main else None
    if src is None and isinstance(edited_df, pd.DataFrame):
        src = edited_df
    if src is None:
        src = st.session_state.df
    prepared = _prepare_table_df_for_save(src)
    if sheets.save_manual(prepared, clear_cache=False, merge_session=True):
        _invalidate_tab2_display_df()
        return True
    return False


@st.fragment
def tab2_main_fragment():
    """Окремий фрагмент: автозбереження після редагування (без окремої кнопки)."""
    if st.session_state.pop("_tab2_save_failed", False):
        st.warning(
            "Останні зміни в таблиці могли не записатись у Google — натисни «Зберегти» ще раз."
        )

    if "_tab2_editor_baseline" not in st.session_state:
        _tab2_reset_editor_baseline()

    col_order = get_table_column_order()
    display_df = _tab2_display_dataframe(col_order)

    with st.expander("↔️ Порядок колонок", expanded=False):
        order = list(col_order)
        for i, col in enumerate(order):
            c1, c2, c3 = st.columns([6, 1, 1])
            with c1:
                st.markdown(f"**{i + 1}.** {col}")
            with c2:
                if st.button("↑", key=f"tab2_col_up_{col}", disabled=(i == 0)):
                    new_order = list(order)
                    new_order[i], new_order[i - 1] = new_order[i - 1], new_order[i]
                    persist_table_column_order(new_order)
                    _invalidate_tab2_display_df()
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
            with c3:
                if st.button("↓", key=f"tab2_col_dn_{col}", disabled=(i == len(order) - 1)):
                    new_order = list(order)
                    new_order[i], new_order[i + 1] = new_order[i + 1], new_order[i]
                    persist_table_column_order(new_order)
                    _invalidate_tab2_display_df()
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
        if st.button("Скинути порядок колонок", key="tab2_col_reset"):
            persist_table_column_order(list(config.COLS))
            _invalidate_tab2_display_df()
            st.session_state.df = apply_table_column_order(st.session_state.df, config.COLS)
            st.rerun()

    edited_df = st.data_editor(
        display_df,
        key="main",
        height=600,
        use_container_width=True,
        hide_index=True,
        column_order=col_order,
        on_change=_autosave_table_on_edit,
        column_config={
            "Дія": None,
            "Статус": st.column_config.TextColumn(width="large", disabled=True),
            "Чек": st.column_config.LinkColumn(display_text="🧾"),
            "Статус СМС": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "Статус Нагадування": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "ТТН": st.column_config.TextColumn(help="Meest, НП, УП"),
        },
    )
    if st.session_state.pop("_tab2_show_toast", False):
        _mark_tab2_saved()

    pending = st.session_state.pop("_tab2_pending_save", False)
    st.session_state.pop("_tab2_main_snapshot", None)
    if pending and not st.session_state.pop("_tab2_saved_in_callback", False):
        if pending == "full":
            main = st.session_state.get("main")
            if _autosave_table_if_changed(main, show_toast=False):
                _mark_tab2_saved()
        elif _autosave_table_from_editor(edited_df):
            _mark_tab2_saved()

    if st.button(
        "💾 Зберегти",
        type="primary",
        use_container_width=True,
        key="tab2_manual_save",
    ):
        if _save_table_from_editor(edited_df):
            _mark_tab2_saved()
        else:
            st.error("Не вдалося зберегти таблицю.")

    st.caption(
        "Зміни зберігаються автоматично після Enter або кліку поза коміркою. "
        "Кнопка «Зберегти» — на всяк випадок, якщо автозбереження не спрацювало."
    )


_auth_lc = str(st.session_state.get("auth_user", "")).strip().lower()
_is_manager = _auth_lc == "manager"
# Вкладка «УП ТТН» (eCom / майстер) — лише для admin; менеджер її не бачить.
_show_up_ttn_tab = _auth_lc == "admin"

_tab_names = [
    "📨 Видати чек",
    "📊 Таблиця",
]
if _show_up_ttn_tab:
    _tab_names.append("📮 УП ТТН")
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
tab3 = _tabs[_i]
_i += 1
tab4 = _tabs[_i]
_i += 1
tab5 = _tabs[_i]
_i += 1
@st.fragment
def tab1_checkout_fragment():
    failed_ttn = st.session_state.pop("_tab1_save_failed", None)
    if failed_ttn:
        st.warning(
            f"Рядок `{failed_ttn}` прибрано з черги, але запис у Google не вдався — "
            "перевір інтернет і натисни «Зберегти» на вкладці «Таблиця» за потреби."
        )

    # 1. Створюємо список статусів, при яких нам потенційно потрібно додати чек вручну
    target_statuses = utils.DELIVERED_STATUS_KEYWORDS
    
    # 2. Оновлена маска: показуємо, якщо СМС ще не відправлено І (вже є текст АБО статус підходить для видачі чека)
    mask = (
        (st.session_state.df['Статус СМС'] != 'Отправлено') & 
        (
            (st.session_state.df['Повідомлення'].str.len() > 5) | 
            (st.session_state.df['Статус'].str.lower().str.contains('|'.join(target_statuses)))
        )
    )
    
    pending = st.session_state.df[mask]
    
    if pending.empty: 
        st.success("🎉 Черга пуста!")
    else:
        for idx, row in pending.iterrows():
            wid = tab1_row_widget_id(row)
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                
                with c1: 
                    st.markdown(f"**{row['Служба']}** `{row['ТТН']}`")
                    st.caption(row['Статус'])
                    st.markdown(f"📞 **{row['Телефон']}**")
                    invoice_num = str(row.get('Номер накладної', '')).strip()
                    if invoice_num and invoice_num.lower() != 'nan':
                        render_copyable_invoice(invoice_num, row_key=f"tab1_{wid}")
                    if float(row.get('Вартість', 0)) > 0: 
                        st.markdown(f"💰 **{row['Вартість']} грн**")
                
                with c2:
                    current_link = str(row.get('Чек', ''))
                    # Якщо чека ще немає - показуємо поле вводу
                    if len(current_link) < 5 or current_link.lower() == 'nan':
                        new_link = st.text_input("➕ Додати чек вручну:", key=f"add_link_{wid}", placeholder="https://...")
                        if new_link:
                            st.session_state[f"tab1_pick_open_{wid}"] = False
                            st.session_state.df.at[idx, 'Чек'] = new_link
                            new_msg = f"Магазин Alius. Ваш чек: {new_link}"
                            st.session_state.df.at[idx, 'Повідомлення'] = new_msg
                            st.session_state[f"tab1_sms_{wid}"] = new_msg
                            st.session_state[f"_tab1_last_ck_{wid}"] = new_link
                            try:
                                sc_m = float(
                                    str(row.get("Вартість", 0))
                                    .replace(",", ".")
                                    .strip()
                                    or 0
                                )
                            except Exception:
                                sc_m = None
                            arch_m = fetch_checkbox_archive()
                            rs_m = (
                                _audit_lookup_receipt_sum(new_link, arch_m)
                                if arch_m is not None and not arch_m.empty
                                else None
                            )
                            audit_log(
                                "чек_посилання",
                                str(row.get("ТТН", "")).strip()[:40],
                                new_link[:120],
                                ship_cost=sc_m,
                                receipt_sum=rs_m,
                            )
                            st.session_state._deferred_save = True
                            st.rerun()

                        pick_key = f"tab1_pick_open_{wid}"
                        if not st.session_state.get(pick_key):
                            if st.button(
                                "📋 Вибрати чек зі списку",
                                key=f"open_pick_{wid}",
                                help="Оновлює чеки з Checkbox і показує варіанти з твоєю сумою",
                                type="primary",
                                use_container_width=True,
                            ):
                                fetch_checkbox_archive.clear()
                                st.session_state[pick_key] = True
                                st.rerun()
                        else:
                            st.markdown("**Чеки з Checkbox**")
                            try:
                                row_cost = float(
                                    str(row.get("Вартість", 0)).replace(",", ".").strip() or 0
                                )
                            except Exception:
                                row_cost = 0.0

                            arch = fetch_checkbox_archive()
                            pick_rows = tab1_unattached_receipt_picker_rows(
                                st.session_state.df, arch, row.get("Вартість", 0)
                            )

                            if arch is None:
                                st.caption("Архів недоступний: перевір логін / ліцензію Checkbox у Secrets.")
                            elif row_cost <= 0:
                                st.caption("Потрібна **вартість** відправлення в таблиці.")
                            elif not pick_rows:
                                st.caption(
                                    "Немає вільних чеків на цю суму (останні ~100 з API). "
                                    "Якщо чек щойно створили — онови запит."
                                )
                                if st.button(
                                    "🔄 Спробувати ще раз",
                                    key=f"retry_pick_{wid}",
                                    use_container_width=True,
                                ):
                                    fetch_checkbox_archive.clear()
                                    st.rerun()
                            else:
                                sum_show = f"{row_cost:.2f}".replace(".", ",")
                                st.caption(
                                    f"Обери рядок (дата, год:хв, сума). Новіші зверху. **{sum_show} грн**."
                                )
                                labels = [p["label"] for p in pick_rows]
                                label_to_link = {p["label"]: p["link"] for p in pick_rows}
                                rk = f"tab1_rcpt_{wid}"
                                st.radio(
                                    "Чек",
                                    labels,
                                    key=rk,
                                    label_visibility="collapsed",
                                )
                                if st.button(
                                    "Прикріпити",
                                    key=f"apply_chk_{wid}",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    choice = st.session_state.get(rk)
                                    sel_link = label_to_link.get(choice)
                                    if sel_link:
                                        fetch_checkbox_archive.clear()
                                        st.session_state[pick_key] = False
                                        st.session_state.df.at[idx, "Чек"] = sel_link
                                        new_msg = f"Магазин Alius. Ваш чек: {sel_link}"
                                        st.session_state.df.at[idx, "Повідомлення"] = new_msg
                                        st.session_state[f"tab1_sms_{wid}"] = new_msg
                                        st.session_state[f"_tab1_last_ck_{wid}"] = sel_link
                                        rs_p = (
                                            _audit_lookup_receipt_sum(sel_link, arch)
                                            if arch is not None and not arch.empty
                                            else None
                                        )
                                        audit_log(
                                            "чек_список",
                                            str(row.get("ТТН", "")).strip()[:40],
                                            sel_link[:120],
                                            ship_cost=row_cost if row_cost > 0 else None,
                                            receipt_sum=rs_p,
                                        )
                                        st.session_state._deferred_save = True
                                        st.rerun()

                            if st.button(
                                "Закрити список",
                                key=f"close_pick_{wid}",
                                use_container_width=True,
                            ):
                                st.session_state[pick_key] = False
                                st.rerun()

                    wk = f"tab1_sms_{wid}"
                    ck = str(row.get("Чек", "")).strip()
                    syn_ck = f"_tab1_last_ck_{wid}"
                    loc_row = st.session_state.df.loc[idx]
                    valid_ck = ck and len(ck) > 5 and ck.lower() != "nan"
                    if syn_ck not in st.session_state:
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                        st.session_state[syn_ck] = ck
                    elif st.session_state[syn_ck] != ck:
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                        st.session_state[syn_ck] = ck
                    elif not str(st.session_state.get(wk, "")).strip():
                        filled = tab1_default_sms_text(loc_row)
                        if len(filled) > 5:
                            st.session_state[wk] = filled
                    elif (
                        valid_ck
                        and ck
                        not in str(st.session_state.df.at[idx, "Повідомлення"])
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                    elif (
                        not valid_ck
                        and _CHECKBOX_RECEIPT_HOST
                        in str(st.session_state.get(wk, "")).lower()
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                    elif (
                        not valid_ck
                        and _CHECKBOX_RECEIPT_HOST
                        in str(st.session_state.df.at[idx, "Повідомлення"]).lower()
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)

                    txt = st.text_area(
                        "Текст СМС",
                        height=100,
                        key=wk,
                        label_visibility="collapsed",
                    )
                    st.session_state.df.at[idx, "Повідомлення"] = txt

                with c3:
                    render_smart_buttons(
                        row["Телефон"],
                        st.session_state.df.at[idx, "Повідомлення"],
                        row_key=f"tab1_{wid}",
                    )
                    if st.button("✅ Готово", key=f"done_{wid}", use_container_width=True):
                        _tab1_mark_done(idx, row)
                        st.rerun()
with tab1:
    tab1_checkout_fragment()
with tab2:
    tab2_main_fragment()
if _show_up_ttn_tab:
    with tab_up:
        render_up_shipments_tab()
with tab3: mask = st.session_state.df['Статус'].str.lower().str.contains('відмова|повернення|denied', na=False); st.dataframe(st.session_state.df[mask].style.map(utils.color_status, subset=['Статус']), use_container_width=True, hide_index=True)
with tab4:
    if st.button("🔄 Оновити Архів"): st.cache_data.clear(); st.rerun()
    c_df = fetch_checkbox_archive()
    if c_df is not None: used = set(st.session_state.df['Чек'].dropna().astype(str).tolist()); st.dataframe(c_df.style.apply(lambda x: ['background-color: #abf7b1; color: black']*len(x) if str(x['Посилання']) in used else ['']*len(x), axis=1), use_container_width=True, hide_index=True, column_config={"Посилання": st.column_config.LinkColumn(display_text="🧾 Чек")})
with tab5:
    st.subheader("⏳ Посилки, що чекають > 5 днів"); today = datetime.now(); found_rem = False
    for idx, row in st.session_state.df.iterrows():
        s_low = str(row['Статус']).lower()
        if any(x in s_low for x in ['прибув', 'прибуло', 'відділенні']) and not any(
            x in s_low
            for x in [
                "отримано",
                "отримане",
                "отримані",
                "отриманий",
                "отримана",
                "відмова",
            ]
        ):
            try:
                d_str = utils.normalize_date(str(row['Дата'])); 
                if not d_str: continue
                delta = today - datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")
                if delta.days >= 5:
                    found_rem = True; svc_map = {"НП": "Нова пошта", "УП": "Укрпошта", "Meest": "Meest Пошта"}; msg = f"Добрий день! Ваше замовлення вже у відділенні {svc_map.get(row['Служба'], row['Служба'])} {row['ТТН']}. Прохання забрати посилку."; is_sent = str(row.get('Статус Нагадування', '')) == 'Отправлено'
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([1.5, 3, 1.5])
                        with c1: st.markdown(f"**{row['Служба']}** `{row['ТТН']}`"); st.caption(f"Чекає: {delta.days} днів"); st.markdown(f"📞 **{row['Телефон']}**"); 
                        if is_sent: st.success("✅ Відправлено")
                        with c2: st.text_area("Текст", msg, height=80, key=f"rt_{idx}", label_visibility="collapsed")
                        with c3: render_smart_buttons(row['Телефон'], msg, row_key=f"tab5_{idx}"); 
                        if st.button("✅ Вже нагадав", key=f"rem_done_{idx}", use_container_width=True): st.session_state.df.at[idx, 'Статус Нагадування'] = 'Отправлено'; sheets.save_manual(st.session_state.df); st.rerun()
            except Exception: continue
    if not found_rem: st.info("👍 Боржників немає.")

if not _is_manager:
    with _tabs[-1]:
        st.subheader("📋 Хто що зробив")
        st.caption(
            "Журнал: Google **Orders** → **LogisticAudit**. "
            "**чек_посилання** — URL вручну; **чек_список** — з Checkbox; **чек_авто** — авто; **смс_готово** — «Готово». "
            "**Вартість ТТН** / **Сума чеку** зберігаються в аркуші на момент події; у таблиці нижче спочатку показуються вони, далі — підстановка з таблиці замовлень і архіву Checkbox. "
            "**Зелений** = збіг сум (±0,01 грн), **червоний** = розбіжність, коли обидва числа відомі."
        )
        if st.button("Оновити журнал", key="audit_refresh"):
            _cached_audit_log_df.clear()
            st.rerun()
        adf = _cached_audit_log_df()
        if adf.empty:
            st.info("Поки немає записів — після дій з’являться тут і в таблиці LogisticAudit.")
        else:
            chk_df = fetch_checkbox_archive()
            disp = _enrich_audit_table(adf, st.session_state.df, chk_df)
            styled = (
                _style_audit_amounts(disp).format(
                    {"Вартість ТТН": "{:.2f}", "Сума чеку": "{:.2f}"},
                    na_rep="—",
                )
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

if st.session_state.get('_deferred_save'):
    st.session_state._deferred_save = False
    if not sheets.save_manual(st.session_state.df):
        st.error("❌ Не вдалося зберегти зміни після позначення 'Готово'.")
