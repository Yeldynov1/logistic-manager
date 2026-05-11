import streamlit as st
import pandas as pd
import time
import streamlit.components.v1 as components
from datetime import datetime, timedelta
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
import sheets  # Google Sheets
import utils   # Технічні функції

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="LogisticManager v6.37 (Clean)", page_icon="🚛", layout="wide")

# ==========================================
# 🔌 АВТО-ПІДКЛЮЧЕННЯ СЕКРЕТІВ
# ==========================================
def load_secrets_to_config():
    if "UP_TRACKING_TOKEN" in st.secrets: config.UP_TRACKING_TOKEN = st.secrets["UP_TRACKING_TOKEN"]
    if "UP_BEARER_TOKEN" in st.secrets: config.UP_BEARER_TOKEN = st.secrets["UP_BEARER_TOKEN"]
    if "UP_USER_TOKEN" in st.secrets: config.UP_USER_TOKEN = st.secrets["UP_USER_TOKEN"]
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

# ==========================================
# Автогенерація повідомлень для черги видачі чека
# ==========================================
def ensure_messages_exist(df):
    for i, row in df.iterrows():
        msg_val = str(row['Повідомлення'])
        is_sent = str(row['Статус СМС']) == 'Отправлено'
        current_status = str(row['Статус']).lower()
        
        if (len(msg_val) <= 5 or msg_val.lower() == 'nan') and not is_sent:
            if utils.status_has_any(current_status, utils.DELIVERED_STATUS_KEYWORDS):
                link = str(row['Чек'])
                
                # Короткий шаблон повідомлення з посиланням на чек
                if link and len(link) > 5 and link.lower() != 'nan':
                    txt_msg = f"Магазин Alius. Ваш чек: {link}"
                    
                    df.at[i, 'Повідомлення'] = txt_msg
                    if len(str(row['Телефон'])) > 5:
                        df.at[i, 'Статус СМС'] = 'Не отправлено'
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
                "Телефон": phone, "Вартість": cost, "Номер накладної": client_barcode, "Чек": "", 
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

def load_data():
    if 'df' not in st.session_state:
        df = sheets.load_data_from_gsheets()
        if "Номер ТТН" in df.columns: df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
        df = ensure_columns(df)
        df = df[config.COLS]
        # Залишаємо leading_zero
        df['ТТН'] = df['ТТН'].apply(restore_leading_zero)
        
        text_cols = ["ТТН", "Служба", "Статус", "Дата", "Телефон", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування", "Номер накладної"]
        for col in text_cols:
            df[col] = df[col].astype(str).replace('nan', '')

        if 'Вартість' in df.columns:
            df['Вартість'] = df['Вартість'].astype(str).str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
            df['Вартість'] = pd.to_numeric(df['Вартість'], errors='coerce').fillna(0.0)

        df['Дія'] = df['Дія'].replace({'True': True, 'False': False, '': False, 'FALSE': False, 'TRUE': True, 1: True, 0: False}).infer_objects(copy=False).fillna(False).astype(bool)
        df['Дата'] = df['Дата'].apply(utils.normalize_date)
        
        df = ensure_messages_exist(df)
        st.session_state.df = df
    else:
        st.session_state.df = ensure_columns(st.session_state.df)

def run_auto_linking(silent=False):
    """Підбір чека з Checkbox: сума + найближчий час; один чек — лише один рядок таблиці."""
    checkbox_df = fetch_checkbox_archive()
    if checkbox_df is None or checkbox_df.empty:
        return 0
    checkbox_df = checkbox_df.copy()
    checkbox_df["dt_obj"] = pd.to_datetime(checkbox_df["Дата"], errors="coerce")

    df = st.session_state.df.copy()
    for col in df.columns:
        df[col] = df[col].astype(object)

    used_links = set()
    for _, r in df.iterrows():
        lk = str(r.get("Чек", "")).strip()
        if lk and len(lk) > 5 and lk.lower() != "nan":
            used_links.add(lk)

    # Макс. відстань у часі між датою рядка в таблиці та фіскальним чеком.
    max_dt_sec = 24 * 3600

    def _link_row_meta(row):
        try:
            c = float(str(row.get("Вартість", 0)).replace(",", ".").strip())
            ds = str(row.get("Дата", "")).strip()
            if c <= 0 or len(ds) < 10:
                return None
            return c, pd.to_datetime(ds)
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
        cost, np_dt = meta
        to_link.append((idx, np_dt, cost))

    to_link.sort(key=lambda x: x[1])

    try:
        sums = pd.to_numeric(checkbox_df["Сума"], errors="coerce")
    except Exception:
        sums = checkbox_df["Сума"]

    matches = 0
    for idx, np_dt, np_cost in to_link:
        cand_mask = (sums - np_cost).abs() < 0.01
        cand = checkbox_df.loc[cand_mask].copy()
        if cand.empty:
            continue
        cand = cand[~cand["Посилання"].astype(str).isin(used_links)]
        if cand.empty:
            continue

        best_link = None
        best_delta = None
        for _, check in cand.iterrows():
            cdt = check["dt_obj"]
            if pd.isna(cdt):
                continue
            delta_sec = abs((np_dt - cdt).total_seconds())
            if delta_sec > max_dt_sec:
                continue
            if best_delta is None or delta_sec < best_delta:
                best_delta = delta_sec
                best_link = str(check["Посилання"])

        if best_link:
            df.at[idx, "Чек"] = best_link
            used_links.add(best_link)
            matches += 1

    if matches > 0:
        st.session_state.df = df
        if sheets.save_manual(df):
            if not silent:
                st.success(f"✅ Знайдено {matches} чеків!")
                time.sleep(1.5)
                st.rerun()
    return matches

def process_status_updates(show_ui=True):
    work_df = st.session_state.df.copy()
    # Переводимо колонки в object, щоб уникнути TypeError при присвоєнні
    for col in work_df.columns:
        work_df[col] = work_df[col].astype(object)
    count_sms = 0
    total = len(work_df)
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

    # Batch НП checks
    np_ttns = [str(row['ТТН']) for _, row in work_df.iterrows() if row['Служба'] == "НП" and len(str(row['ТТН'])) > 5]
    np_statuses = get_np_statuses_bulk(np_ttns) if np_ttns else {}

    for i, row in work_df.iterrows():
        if show_ui: progress_bar.progress((i + 1) / total)
        ttn = str(work_df.loc[i, 'ТТН'])
        if len(ttn) < 5: continue
        
        svc = work_df.loc[i, 'Служба']
        current = str(work_df.loc[i, 'Статус']).lower()
        
        s, d, cost, phone, extra = "", None, 0.0, "", ""
        
        if svc == "НП" and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS):
            if ttn in np_statuses:
                info = np_statuses[ttn]
                s = info.get('Status', '')
                cost = info.get('Cost', 0.0)
                phone = info.get('Phone', '')
                invoice = info.get('ClientBarcode', '')
                if invoice:
                    work_df.loc[i, 'Номер накладної'] = str(invoice)
        
        elif svc == "УП" and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS):
            if show_ui: status_text.text(f"Перевірка УП: {ttn}")
            s, d, cost, phone, extra = get_up_status_smart(ttn)
            if phone and len(str(work_df.loc[i, 'Телефон'])) < 10:
                work_df.loc[i, 'Телефон'] = str(phone)
        
        elif svc == "Meest" and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS):
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

st.markdown("""<style>button[data-baseweb="tab"] { font-size: 24px !important; font-weight: 700 !important; } div.stButton > button { font-size: 16px !important; font-weight: 500 !important; } section[data-testid="stSidebar"] div.stButton > button { width: 100% !important; border: 1px solid #4CAF50 !important; }</style>""", unsafe_allow_html=True)

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
    inv = str(invoice_num).strip()
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


def tab1_default_sms_text(row) -> str:
    """Текст для СМС у черзі видачі чека: довге «Повідомлення» з таблиці або шаблон з посиланням на чек."""
    msg = str(row.get("Повідомлення", "")).strip()
    link = str(row.get("Чек", "")).strip()
    if len(msg) > 5 and msg.lower() != "nan":
        return msg
    if link and len(link) > 5 and link.lower() != "nan":
        return f"Магазин Alius. Ваш чек: {link}"
    return msg if msg and msg.lower() != "nan" else ""


st.title("📦 LogisticManager (GSheets + Selenium)")
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
                                "invoice": "" if raw_invoice.lower() == 'nan' else raw_invoice
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
                        invoice_num = str(src.get("invoice", "")).strip()

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
                                invoice_num = str(row[invoice_num_col]).strip()
                                
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
                            "Телефон": utils.clean_phone(manual_phone), "Вартість": cost_value, "Номер накладної": manual_invoice, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
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
    if st.button("🔗 Авто-підбір чеків"): run_auto_linking(silent=False)
    st.divider()
    if st.button("🔄 Оновити статуси"): count, saved = process_status_updates(show_ui=True); 
    st.divider()
    if st.button("🗑️ Видалити відправлені", type="secondary"): new_df = st.session_state.df[st.session_state.df['Статус СМС'] != 'Отправлено'].reset_index(drop=True); sheets.save_manual(new_df); st.success("✅ Очищено!"); time.sleep(1); st.rerun()
    if st.button("🚪 Вийти", type="secondary"): st.session_state.logged_in = False; st.rerun()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📨 Видати чек", "📊 Таблиця", "❌ Відмови", "🧾 Архів чеків", "⏳ Нагадування"])
with tab1:
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
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                
                with c1: 
                    st.markdown(f"**{row['Служба']}** `{row['ТТН']}`")
                    st.caption(row['Статус'])
                    st.markdown(f"📞 **{row['Телефон']}**")
                    invoice_num = str(row.get('Номер накладної', '')).strip()
                    if invoice_num and invoice_num.lower() != 'nan':
                        render_copyable_invoice(invoice_num, row_key=f"tab1_{idx}")
                    if float(row.get('Вартість', 0)) > 0: 
                        st.markdown(f"💰 **{row['Вартість']} грн**")
                
                with c2:
                    current_link = str(row.get('Чек', ''))
                    # Якщо чека ще немає - показуємо поле вводу
                    if len(current_link) < 5 or current_link.lower() == 'nan':
                        new_link = st.text_input("➕ Додати чек вручну:", key=f"add_link_{idx}", placeholder="https://...")
                        if new_link:
                            st.session_state.df.at[idx, 'Чек'] = new_link
                            new_msg = f"Магазин Alius. Ваш чек: {new_link}"
                            st.session_state.df.at[idx, 'Повідомлення'] = new_msg
                            st.session_state[f"tab1_sms_{idx}"] = new_msg
                            st.session_state[f"_tab1_last_ck_{idx}"] = new_link
                            sheets.save_manual(st.session_state.df)
                            st.rerun()

                    wk = f"tab1_sms_{idx}"
                    ck = str(row.get("Чек", "")).strip()
                    syn_ck = f"_tab1_last_ck_{idx}"
                    loc_row = st.session_state.df.loc[idx]
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
                        row_key=f"tab1_{idx}",
                    )
                    if st.button("✅ Готово", key=f"done_{idx}", use_container_width=True): 
                        st.session_state.df.at[idx, 'Статус СМС'] = 'Отправлено'
                        st.session_state._deferred_save = True
                        st.rerun()
with tab2:
    edited = st.data_editor(st.session_state.df.style.map(utils.color_status, subset=['Статус']), key="main", height=600, use_container_width=True, hide_index=True, column_config={"Дія": None, "Статус": st.column_config.TextColumn(width="large", disabled=True), "Чек": st.column_config.LinkColumn(display_text="🧾"), "Статус СМС": st.column_config.SelectboxColumn(options=["", "Отправлено", "Не отправлено"]), "Статус Нагадування": st.column_config.SelectboxColumn(options=["", "Отправлено", "Не отправлено"]), "ТТН": st.column_config.TextColumn(help="Meest, НП, УП")})
    if st.button("💾 ЗБЕРЕГТИ ЗМІНИ", type="primary", use_container_width=True): 
        if sheets.save_manual(edited): st.success("✅ Збережено!"); time.sleep(1); st.rerun()
with tab3: mask = st.session_state.df['Статус'].str.lower().str.contains('відмова|повернення|denied', na=False); st.dataframe(st.session_state.df[mask].style.map(utils.color_status, subset=['Статус']), use_container_width=True, hide_index=True)
with tab4:
    if st.button("🔄 Оновити Архів"): st.cache_data.clear(); st.rerun()
    c_df = fetch_checkbox_archive()
    if c_df is not None: used = set(st.session_state.df['Чек'].dropna().astype(str).tolist()); st.dataframe(c_df.style.apply(lambda x: ['background-color: #abf7b1; color: black']*len(x) if str(x['Посилання']) in used else ['']*len(x), axis=1), use_container_width=True, hide_index=True, column_config={"Посилання": st.column_config.LinkColumn(display_text="🧾 Чек")})
with tab5:
    st.subheader("⏳ Посилки, що чекають > 5 днів"); today = datetime.now(); found_rem = False
    for idx, row in st.session_state.df.iterrows():
        s_low = str(row['Статус']).lower()
        if any(x in s_low for x in ['прибув', 'прибуло', 'відділенні']) and not any(x in s_low for x in ['отримано', 'відмова']):
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

if st.session_state.get('_deferred_save'):
    st.session_state._deferred_save = False
    if not sheets.save_manual(st.session_state.df):
        st.error("❌ Не вдалося зберегти зміни після позначення 'Готово'.")
