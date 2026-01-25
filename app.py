import streamlit as st
import pandas as pd
import time
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import html
import gspread
import requests

# --- ПІДКЛЮЧЕННЯ НАЛАШТУВАНЬ ---
import config
import utils

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="LogisticManager v5.7 (Debug)", page_icon="🚛", layout="wide")

# ==========================================
# 🔌 АВТО-ПІДКЛЮЧЕННЯ СЕКРЕТІВ
# ==========================================
def load_secrets_to_config():
    # Укрпошта
    if "UP_TRACKING_TOKEN" in st.secrets:
        config.UP_TRACKING_TOKEN = st.secrets["UP_TRACKING_TOKEN"]
    if "UP_BEARER_TOKEN" in st.secrets:
        config.UP_BEARER_TOKEN = st.secrets["UP_BEARER_TOKEN"]
    if "UP_USER_TOKEN" in st.secrets:
        config.UP_USER_TOKEN = st.secrets["UP_USER_TOKEN"]
    
    # Нова Пошта
    if "API_KEY_NP" in st.secrets:
        config.API_KEY_NP = st.secrets["API_KEY_NP"]

    # Checkbox
    if "CHECKBOX_LICENSE_KEY" in st.secrets:
        config.CHECKBOX_LICENSE_KEY = st.secrets["CHECKBOX_LICENSE_KEY"]
    if "CHECKBOX_PASSWORD" in st.secrets:
        config.CHECKBOX_PASSWORD = st.secrets["CHECKBOX_PASSWORD"]

    # SMS
    if "TURBOSMS_TOKEN" in st.secrets:
        setattr(config, 'TURBOSMS_TOKEN', st.secrets["TURBOSMS_TOKEN"])

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
                    if username in config.USERS and config.USERS[username] == password:
                        st.session_state.logged_in = True
                        st.toast("Успішний вхід!", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ Невірний логін або пароль")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 🌐 GOOGLE SHEETS
# ==========================================
def get_google_sheet():
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Не знайдено 'gcp_service_account' у Secrets!")
            return None
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc.open("Orders").sheet1
    except Exception as e:
        st.error(f"❌ Помилка Google Sheets: {e}")
        return None

@st.cache_data(ttl=60)
def load_data_from_gsheets():
    sheet = get_google_sheet()
    if not sheet: return pd.DataFrame(columns=config.COLS)
    try:
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        if df.empty: return pd.DataFrame(columns=config.COLS)
        return df
    except: return pd.DataFrame(columns=config.COLS)

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
                dt = datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=2)
                f_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            except: f_date = utils.normalize_date(raw_date)
            parsed.append({
                "ID": item.get('id'), "Дата": f_date, "Сума": item.get('total_sum', 0) / 100,
                "Посилання": f"https://check.checkbox.ua/{item.get('id')}"
            })
        return pd.DataFrame(parsed)
    except: return None

# --- НОВА ПОШТА ---
def get_np_status_full(ttn):
    r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "TrackingDocument", "calledMethod": "getStatusDocuments",
        "methodProperties": {"Documents": [{"DocumentNumber": ttn}]}
    })
    status, phone, date, cost = "", "", "", 0.0
    if r and r.json()['success']:
        item = r.json()['data'][0]
        status = item.get('Status', '')
        cost = float(item.get('AnnouncedPrice') or 0)
    
    r_det = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList", 
        "methodProperties": {"IntDocNumber": ttn}
    })
    if r_det and r_det.json()['success'] and r_det.json()['data']:
        item = r_det.json()['data'][0]
        if item.get('CreateTime'): date = utils.normalize_date(item.get('CreateTime'))
        elif not date: date = utils.normalize_date(item.get('DateTime', ''))
        if not phone: phone = item.get('RecipientContactPhone', '')
        if cost == 0: cost = float(item.get('Cost') or item.get('DeclaredCost') or 0)
    return status, utils.clean_phone(phone), date, cost

def fetch_new_orders_np(existing_ttns):
    date_from = (datetime.now() - timedelta(days=30)).strftime("%d.%m.%Y")
    r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList",
        "methodProperties": {"DateFrom": date_from, "DateTo": datetime.now().strftime("%d.%m.%Y"), "GetFullList": "1"}
    })
    new_rows = []
    if r and r.json()['success']:
        for doc in r.json()['data']:
            ttn = utils.clean_ttn(str(doc.get('IntDocNumber')))
            if ttn and ttn not in existing_ttns:
                cost = float(doc.get('Cost') or doc.get('DeclaredCost') or 0)
                date = utils.normalize_date(doc.get('CreateTime') or doc.get('DateTime', ''))
                phone = utils.clean_phone(doc.get('RecipientContactPhone', ''))
                new_rows.append({
                    "ТТН": ttn, "Служба": "НП", "Статус": doc.get('StateName', 'Нове'), "Дата": date,
                    "Телефон": phone, "Вартість": cost, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                })
    return new_rows

# --- УКРПОШТА (SMART + DEBUG) ---
def get_up_status_smart(barcode):
    # 1. ПУБЛІЧНИЙ API
    if config.UP_TRACKING_TOKEN and len(config.UP_TRACKING_TOKEN) > 5:
        try:
            r = utils.make_request("GET", f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}", 
                            headers={"Authorization": f"Bearer {config.UP_TRACKING_TOKEN}", "Accept": "application/json"})
            if r and r.status_code == 200:
                data = r.json()
                if data and isinstance(data, list):
                    last = data[-1]
                    return last.get('eventName', 'В дорозі'), utils.normalize_date(last.get('date', '')), 0.0
        except: pass

    # 2. БІЗНЕС API
    if config.UP_BEARER_TOKEN and len(config.UP_BEARER_TOKEN) > 10 and config.UP_USER_TOKEN:
        try:
            url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
            headers = {"Authorization": f"Bearer {config.UP_BEARER_TOKEN}", "Content-Type": "application/json"}
            params = {"token": config.UP_USER_TOKEN}
            r = utils.make_request("GET", url, headers=headers, params=params)
            if r.status_code == 200:
                data = r.json()
                status_raw = data.get('lifecycle', {}).get('status')
                last_event = data.get('lifecycle', {}).get('eventName')
                final_status = last_event if last_event else (status_raw if status_raw else "В дорозі")
                date_raw = data.get('lifecycle', {}).get('date') or data.get('lastModified')
                return final_status, utils.normalize_date(date_raw), 0.0
        except: pass

    return "Не знайдено", None, 0.0

def fetch_new_orders_up(existing_ttns):
    if not config.UP_BEARER_TOKEN or len(config.UP_BEARER_TOKEN) < 10 or not config.UP_USER_TOKEN: return []
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    d_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {"token": config.UP_USER_TOKEN, "lastModifiedFrom": d_from}
    headers = {"Authorization": f"Bearer {config.UP_BEARER_TOKEN}", "Content-Type": "application/json"}
    try:
        r = utils.make_request("GET", url, headers=headers, params=params)
        if r.status_code != 200: return []
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
                    "Телефон": phone, "Вартість": cost, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                })
        return new_rows
    except: return []

# --- MEEST ---
def get_meest_status(ttn):
    if not config.MEEST_API_TOKEN: return "Немає токена (Meest)", "", "", 0.0
    headers = {"token": config.MEEST_API_TOKEN, "Content-Type": "application/json"}
    try:
        url = f"https://api.meest.com/v3.0/openAPI/tracking/{ttn}"
        r = utils.make_request("GET", url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            if data.get('status') == 'OK' and data.get('result'):
                res = data['result']
                history = res.get('history', []) if isinstance(res, dict) else res
                if not history and isinstance(res, list): history = res
                if history:
                    last = history[-1]
                    status = last.get('status_ua') or last.get('status_en') or last.get('status', 'В дорозі')
                    date = utils.normalize_date(last.get('date', ''))
                    return status, "", date, 0.0
    except: pass

    try:
        url = "https://api.meest.com/v3.0/openAPI/trackingShipment"
        payload = {"number": ttn}
        if config.MEEST_CONTRACT_ID: payload["contractID"] = config.MEEST_CONTRACT_ID
        r = utils.make_request("POST", url, headers=headers, json=payload)
        if r.status_code == 200:
            data = r.json()
            if data.get('status') == 'OK' and data.get('result_table'):
                items = data['result_table'].get('items', [])
                if items:
                    last = items[-1]
                    status = last.get('ActionMessages_UA', 'В дорозі')
                    date = utils.normalize_date(last.get('DateTimeAction', ''))
                    return status, "", date, 0.0
    except: pass
    
    return "Не знайдено", "", "", 0.0

def fetch_new_orders_meest(existing_ttns):
    if not config.MEEST_API_TOKEN: return []
    headers = {"token": config.MEEST_API_TOKEN, "Content-Type": "application/json"}
    new_rows = []
    for i in range(3):
        d_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        url = f"https://api.meest.com/v3.0/openAPI/parcelsList/{d_str}"
        try:
            r = utils.make_request("GET", url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                items = data.get('result', [])
                if isinstance(items, list):
                    for item in items:
                        ttn = utils.clean_ttn(item.get('number', ''))
                        if ttn and ttn not in existing_ttns:
                            date = utils.normalize_date(item.get('date', ''))
                            cost = float(item.get('cod', 0) or item.get('declaredValue', 0) or 0)
                            new_rows.append({
                                "ТТН": ttn, "Служба": "Meest", "Статус": "Нове", "Дата": date,
                                "Телефон": "", "Вартість": cost, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                            })
        except: pass
    return new_rows

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

def load_data():
    if 'df' not in st.session_state:
        df = load_data_from_gsheets()
        if "Номер ТТН" in df.columns: df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
        df = ensure_columns(df)
        df = df[config.COLS]

        text_cols = ["ТТН", "Служба", "Статус", "Дата", "Телефон", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування"]
        for col in text_cols:
            df[col] = df[col].astype(str).replace('nan', '')

        if 'Вартість' in df.columns:
            df['Вартість'] = df['Вартість'].astype(str).str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
            df['Вартість'] = pd.to_numeric(df['Вартість'], errors='coerce').fillna(0.0)

        df['Дія'] = df['Дія'].replace({'True': True, 'False': False, '': False, 'FALSE': False, 'TRUE': True, 1: True, 0: False}).infer_objects(copy=False).fillna(False).astype(bool)
        df['Дата'] = df['Дата'].apply(utils.normalize_date)
        st.session_state.df = df
    else:
        st.session_state.df = ensure_columns(st.session_state.df)

def save_manual(df_to_save):
    try:
        sheet = get_google_sheet()
        if sheet:
            to_save = df_to_save.drop(columns=['Дія'], errors='ignore')
            to_save = to_save.fillna("")
            data = [to_save.columns.values.tolist()] + to_save.values.tolist()
            sheet.clear(); sheet.update(data)
            st.session_state.df = df_to_save
            st.cache_data.clear()
            return True
        else:
            st.error("❌ Не вдалося підключитися до таблиці!")
            return False
    except Exception as e:
        st.error(f"❌ Помилка збереження: {e}")
        return False

def run_auto_linking(silent=False):
    checkbox_df = fetch_checkbox_archive()
    if checkbox_df is None or checkbox_df.empty: return 0
    checkbox_df['dt_obj'] = pd.to_datetime(checkbox_df['Дата'], errors='coerce')
    df = st.session_state.df
    matches = 0
    for idx, row in df.iterrows():
        if len(str(row['Чек'])) > 5: continue
        try:
            np_cost = float(row.get('Вартість', 0)); np_date = str(row.get('Дата', ''))
            if np_cost == 0 or len(np_date) < 10: continue
            np_dt = pd.to_datetime(np_date)
        except: continue
        candidates = checkbox_df[abs(checkbox_df['Сума'] - np_cost) < 0.01]
        for _, check in candidates.iterrows():
            if pd.isna(check['dt_obj']): continue
            if abs((np_dt - check['dt_obj']).total_seconds()) <= 70:
                df.at[idx, 'Чек'] = check['Посилання']; matches += 1; break
    if matches > 0:
        if save_manual(df):
            if not silent: st.success(f"✅ Знайдено {matches} чеків!"); time.sleep(1.5); st.rerun()
    return matches

def process_status_updates(show_ui=True):
    work_df = st.session_state.df.copy()
    count_sms = 0
    total = len(work_df)
    progress_bar = st.progress(0) if show_ui else None
    status_text = st.empty() if show_ui else None

    for i, row in work_df.iterrows():
        if show_ui: progress_bar.progress((i + 1) / total)
        ttn = utils.clean_ttn(str(row['ТТН']))
        if len(ttn) < 5: continue
        svc = row['Служба']
        if not svc or svc == "Інше": svc = utils.identify_service(ttn); work_df.at[i, 'Служба'] = svc
        current = str(work_df.at[i, 'Статус']).lower()
        
        if not any(x in current for x in ['отримано', 'вручено', 'відмова', 'повернення']):
            if show_ui: status_text.text(f"Перевірка {svc}: {ttn}")
            if svc == "НП":
                s, p, d, cost = get_np_status_full(ttn)
                work_df.at[i, 'Статус'] = s
                if p: work_df.at[i, 'Телефон'] = p
                if d: work_df.at[i, 'Дата'] = d 
                if cost > 0: work_df.at[i, 'Вартість'] = cost
            elif svc == "УП":
                s, d, cost = get_up_status_smart(ttn)
                work_df.at[i, 'Статус'] = s
                if d: work_df.at[i, 'Дата'] = d
            elif svc == "Meest":
                s, p, d, cost = get_meest_status(ttn)
                work_df.at[i, 'Статус'] = s
                if d: work_df.at[i, 'Дата'] = d
                if cost > 0: work_df.at[i, 'Вартість'] = cost
        
        msg_val = str(work_df.at[i, 'Повідомлення'])
        has_msg = len(msg_val.strip()) > 5 and msg_val.lower().strip() != 'nan'
        is_sent = str(work_df.at[i, 'Статус СМС']) == 'Отправлено'
        current_new = str(work_df.at[i, 'Статус']).lower()
        if not has_msg and not is_sent:
            if any(x in current_new for x in ['отримано', 'доставлено', 'вручено', 'delivered', 'відділенні']):
                link = str(work_df.at[i, 'Чек'])
                msg = "Доброго дня!\nВаше замовлення отримано.\n"
                if link and len(link) > 5 and link.lower() != 'nan': msg += f"Переглянути чек: {link}\n"
                msg += "Щиро дякуємо за покупку!"
                work_df.at[i, 'Повідомлення'] = msg
                if len(str(work_df.at[i, 'Телефон'])) > 5: work_df.at[i, 'Статус СМС'] = 'Не отправлено'
                count_sms += 1
    
    st.session_state.df = work_df
    saved = save_manual(st.session_state.df)
    if show_ui: status_text.empty(); progress_bar.empty()
    return count_sms, saved

def show_analytics(df):
    if df.empty: st.info("Ще немає даних."); return
    data = df.copy()
    data['Вартість'] = pd.to_numeric(data['Вартість'], errors='coerce').fillna(0)
    data['DateObj'] = pd.to_datetime(data['Дата'], errors='coerce')
    data['Day'] = data['DateObj'].dt.date
    today = datetime.now().date(); df_today = data[data['Day'] == today]
    count_today = len(df_today); sum_today = df_today['Вартість'].sum()
    if not df_today.empty: svc_counts = df_today['Служба'].value_counts(); services_str = ", ".join([f"{k}: {v}" for k, v in svc_counts.items()])
    else: services_str = "—"
    total_orders = len(data); total_money = data['Вартість'].sum()
    st.markdown(f"### 📅 Статистика за сьогодні ({today.strftime('%d.%m.%Y')})")
    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("📦 Відправлень", f"{count_today}", delta=f"Всього: {total_orders}")
    kpi2.metric("💰 Сума", f"{sum_today:,.0f} грн", delta=f"Всього: {total_money:,.0f} грн")
    kpi3.metric("🚚 Служби", services_str)
    st.divider()
    c_chart1, c_chart2 = st.columns(2)
    with c_chart1: st.markdown("##### 📅 Динаміка"); daily_counts = data.groupby('Day').size().reset_index(name='Кількість'); st.bar_chart(daily_counts, x='Day', y='Кількість')
    with c_chart2: st.markdown("##### 🚚 Розподіл служб"); st.bar_chart(data['Служба'].value_counts())

st.markdown("""<style>button[data-baseweb="tab"] { font-size: 24px !important; font-weight: 700 !important; } div.stButton > button { font-size: 16px !important; font-weight: 500 !important; } section[data-testid="stSidebar"] div.stButton > button { width: 100% !important; border: 1px solid #4CAF50 !important; }</style>""", unsafe_allow_html=True)

def render_smart_buttons(phone, message):
    if not phone or len(str(phone)) < 10: st.caption("Невірний телефон"); return
    raw_phone = str(phone); digits = ''.join(filter(str.isdigit, raw_phone))
    if len(digits) == 10 and digits.startswith('0'): digits = '38' + digits
    if len(digits) != 12: st.caption(f"Формат? {raw_phone}"); return
    msg_safe = html.escape(message).replace('\n', '\\n').replace("'", "\\'")
    js_code = f"""<script>function clickHandler_{digits}(type) {{ const text = '{msg_safe}'; const url = type === 'viber' ? 'viber://chat?number=%2B{digits}' : 'sms:+{digits}'; const el = document.createElement('textarea'); el.value = text; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el); const link = document.createElement('a'); link.href = url; document.body.appendChild(link); link.click(); document.body.removeChild(link); }}</script><div style="display: flex; flex-direction: column; gap: 8px;"><button onclick="clickHandler_{digits}('viber')" style="background-color: #7360f2; color: white; border: none; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">💬 Viber</button><button onclick="clickHandler_{digits}('sms')" style="background-color: #f0f2f6; color: #31333F; border: 1px solid #ccc; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">📩 SMS</button></div>"""
    st.components.v1.html(js_code, height=100)

st.title("📦 LogisticManager (GSheets)")
load_data()

# --- САЙДБАР З ДІАГНОСТИКОЮ ---
with st.sidebar:
    st.header("🎮 Пульт")

    # === БЛОК ДІАГНОСТИКИ (ТІЛЬКИ ДЛЯ УП) ===
    with st.expander("🛠️ Тест Укрпошти"):
        # 1. Перевірка токена
        token_preview = config.UP_TRACKING_TOKEN[:5] + "..." if config.UP_TRACKING_TOKEN else "❌ НЕМАЄ"
        st.write(f"Токен: `{token_preview}`")
        
        # 2. Кнопка тесту
        test_barcode = st.text_input("Введи ТТН УП для тесту")
        if st.button("🚀 Перевірити з'єднання"):
            if not config.UP_TRACKING_TOKEN:
                st.error("Токен не знайдено!")
            else:
                try:
                    url = f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={test_barcode}"
                    headers = {"Authorization": f"Bearer {config.UP_TRACKING_TOKEN}", "Accept": "application/json"}
                    
                    st.write("📡 Запит на сервер...")
                    r = requests.get(url, headers=headers)
                    
                    if r.status_code == 200:
                        st.success("✅ Успіх! (200 OK)")
                        st.json(r.json())
                    else:
                        st.error(f"❌ Помилка: {r.status_code}")
                        st.write(f"Відповідь: {r.text}")
                except Exception as e:
                    st.error(f"Помилка коду: {e}")

    with st.expander("➕ Додати ТТН вручну", expanded=True):
        with st.form("manual_add_form", clear_on_submit=True):
            manual_ttn = st.text_input("Введіть ТТН (можна кілька через пробіл)")
            manual_phone = st.text_input("Телефон (необов'язково)")
            submitted = st.form_submit_button("Додати")
            if submitted and manual_ttn:
                ttns = manual_ttn.replace(",", " ").split(); added = 0
                for t in ttns:
                    t_clean = utils.clean_ttn(t)
                    if t_clean and t_clean not in st.session_state.df['ТТН'].tolist():
                        svc = utils.identify_service(t_clean)
                        st.session_state.df.loc[len(st.session_state.df)] = {
                            "ТТН": t_clean, "Служба": svc, "Статус": "Нове", "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Телефон": utils.clean_phone(manual_phone), "Вартість": 0, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                        }
                        added += 1
                if added > 0:
                    if save_manual(st.session_state.df):
                        st.success(f"Додано {added} накладних!")
                        time.sleep(1); st.rerun()
                    else: st.error("Помилка збереження! Перевір права.")
                else: st.warning("Вже є в базі")
    if st.button("📥 Завантажити нові", type="primary"):
        with st.status("Завантаження...", expanded=True):
            existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
            n_np = fetch_new_orders_np(existing); n_up = fetch_new_orders_up(existing); n_meest = fetch_new_orders_meest(existing)
            all_new = n_np + n_up + n_meest
            if all_new:
                new_df = pd.DataFrame(all_new)
                for c in config.COLS:
                    if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
                st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
                save_manual(st.session_state.df); st.success(f"✅ Додано {len(all_new)} нових!"); time.sleep(1); st.rerun()
            else: st.info("Нових немає")
    st.divider()
    if st.button("🔗 Авто-підбір чеків"): run_auto_linking(silent=False)
    st.divider()
    if st.button("🔄 Оновити статуси"): count, saved = process_status_updates(show_ui=True); 
    if st.button("🗑️ Видалити відправлені", type="secondary"): new_df = st.session_state.df[st.session_state.df['Статус СМС'] != 'Отправлено'].reset_index(drop=True); save_manual(new_df); st.success("✅ Очищено!"); time.sleep(1); st.rerun()
    st.divider(); 
    if st.button("🚪 Вийти", type="secondary"): st.session_state.logged_in = False; st.rerun()

if 'auto_refresh' not in st.session_state: st.session_state.auto_refresh = False
if 'last_status_update' not in st.session_state: st.session_state.last_status_update = 0
st.sidebar.toggle("🔄 Авто-пошук (ВКЛ/ВИКЛ)", key="auto_refresh")

if st.session_state.auto_refresh:
    with st.spinner("⏳ Авто: Пошук нових..."):
        st.cache_data.clear() 
        existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
        n_np = fetch_new_orders_np(existing); n_up = fetch_new_orders_up(existing); n_meest = fetch_new_orders_meest(existing)
        all_new = n_np + n_up + n_meest
        if all_new:
            new_df = pd.DataFrame(all_new)
            for c in config.COLS:
                if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
            st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
            save_manual(st.session_state.df)
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📨 Видати чек", "📊 Таблиця", "❌ Відмови", "🧾 Архів чеків", "⏳ Нагадування", "📈 Аналітика"])
with tab1:
    mask = ((st.session_state.df['Повідомлення'].str.len() > 5) & (st.session_state.df['Статус СМС'] != 'Отправлено'))
    pending = st.session_state.df[mask]
    if pending.empty: st.success("🎉 Черга пуста!")
    else:
        for idx, row in pending.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                with c1: st.markdown(f"**{row['Служба']}** `{row['ТТН']}`"); st.caption(row['Статус']); st.markdown(f"📞 **{row['Телефон']}**"); 
                if float(row.get('Вартість', 0)) > 0: st.markdown(f"💰 **{row['Вартість']} грн**")
                with c2: txt = st.text_area("Текст", row['Повідомлення'], height=100, key=f"t_{idx}", label_visibility="collapsed")
                with c3: render_smart_buttons(row['Телефон'], row['Повідомлення']); 
                if st.button("✅ Готово", key=f"done_{idx}", use_container_width=True): st.session_state.df.at[idx, 'Статус СМС'] = 'Отправлено'; save_manual(st.session_state.df); st.rerun()
with tab2:
    edited = st.data_editor(st.session_state.df.style.map(utils.color_status, subset=['Статус']), key="main", height=600, use_container_width=True, hide_index=True, column_config={"Дія": None, "Статус": st.column_config.TextColumn(width="large", disabled=True), "Чек": st.column_config.LinkColumn(display_text="🧾"), "Статус СМС": st.column_config.SelectboxColumn(options=["", "Отправлено", "Не отправлено"]), "Статус Нагадування": st.column_config.SelectboxColumn(options=["", "Отправлено", "Не отправлено"]), "ТТН": st.column_config.TextColumn(help="Meest, НП, УП")})
    if st.button("💾 ЗБЕРЕГТИ ЗМІНИ", type="primary", use_container_width=True): 
        if save_manual(edited): st.success("✅ Збережено!"); time.sleep(1); st.rerun()
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
                        with c3: render_smart_buttons(row['Телефон'], msg); 
                        if st.button("✅ Вже нагадав", key=f"rem_done_{idx}", use_container_width=True): st.session_state.df.at[idx, 'Статус Нагадування'] = 'Отправлено'; save_manual(st.session_state.df); st.rerun()
            except: continue
    if not found_rem: st.info("👍 Боржників немає.")
with tab6: show_analytics(st.session_state.df)