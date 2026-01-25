import streamlit as st
import pandas as pd
import time
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import html
import gspread
import requests

# --- ПІДКЛЮЧЕННЯ МОДУЛІВ ---
import config
import utils

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="LogisticManager v6.0 (Final)", page_icon="🚛", layout="wide")

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

load_secrets_to_config()

# ==========================================
# 🔐 АВТОРИЗАЦІЯ
# ==========================================
def check_password():
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
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
                        st.session_state.logged_in = True; st.toast("Успішний вхід!", icon="✅"); time.sleep(0.5); st.rerun()
                    else: st.error("❌ Невірний логін або пароль")
        return False
    return True

if not check_password(): st.stop()

# ==========================================
# 🌐 GOOGLE SHEETS
# ==========================================
def get_google_sheet():
    try:
        if "gcp_service_account" not in st.secrets: st.error("❌ Не знайдено 'gcp_service_account'!"); return None
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"]).open("Orders").sheet1
    except Exception as e: st.error(f"❌ Помилка Google Sheets: {e}"); return None

# ==========================================
# 🧠 ЛОГІКА: АВТО-ГЕНЕРАЦІЯ ПОВІДОМЛЕНЬ
# ==========================================
def ensure_messages_exist(df):
    """
    Ця функція проходить по таблиці і створює повідомлення, 
    якщо статус 'Отримано', а тексту немає.
    Працює навіть при F5.
    """
    count_generated = 0
    for i, row in df.iterrows():
        msg_val = str(row['Повідомлення'])
        is_sent = str(row['Статус СМС']) == 'Отправлено'
        current_status = str(row['Статус']).lower()
        
        # Якщо повідомлення пусте (або 'nan'), ще не відправлено, і посилка прибула/отримана
        if (len(msg_val) <= 5 or msg_val.lower() == 'nan') and not is_sent:
            if any(x in current_status for x in ['отримано', 'доставлено', 'вручено', 'delivered', 'відділенні']):
                link = str(row['Чек'])
                txt_msg = "Доброго дня!\nВаше замовлення отримано.\n"
                if link and len(link) > 5 and link.lower() != 'nan':
                    txt_msg += f"Переглянути чек: {link}\n"
                txt_msg += "Щиро дякуємо за покупку!"
                
                df.at[i, 'Повідомлення'] = txt_msg
                if len(str(row['Телефон'])) > 5:
                    df.at[i, 'Статус СМС'] = 'Не отправлено'
                count_generated += 1
    return df

@st.cache_data(ttl=60)
def load_data_from_gsheets():
    sheet = get_google_sheet()
    if not sheet: return pd.DataFrame(columns=config.COLS)
    try:
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        return df if not df.empty else pd.DataFrame(columns=config.COLS)
    except: return pd.DataFrame(columns=config.COLS)

# ==========================================
# 🌐 API ФУНКЦІЇ (TURBO + SMART)
# ==========================================

# --- НОВА ПОШТА (МАСОВИЙ ЗАПИТ) ---
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
                            "Phone": item.get('RecipientPhone', '') 
                        }
        except: pass
    return results

def get_np_status_full(ttn):
    # Fallback
    r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={"apiKey": config.API_KEY_NP, "modelName": "TrackingDocument", "calledMethod": "getStatusDocuments", "methodProperties": {"Documents": [{"DocumentNumber": ttn}]}})
    status, phone, date, cost = "", "", "", 0.0
    if r and r.json()['success']:
        item = r.json()['data'][0]; status = item.get('Status', ''); cost = float(item.get('AnnouncedPrice') or 0)
    r_det = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={"apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList", "methodProperties": {"IntDocNumber": ttn}})
    if r_det and r_det.json()['success'] and r_det.json()['data']:
        item = r_det.json()['data'][0]; date = utils.normalize_date(item.get('CreateTime') or item.get('DateTime', ''))
        phone = item.get('RecipientContactPhone', ''); 
        if cost == 0: cost = float(item.get('Cost') or item.get('DeclaredCost') or 0)
    return status, utils.clean_phone(phone), date, cost

def fetch_new_orders_np(existing):
    r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={"apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList", "methodProperties": {"DateFrom": (datetime.now() - timedelta(days=30)).strftime("%d.%m.%Y"), "DateTo": datetime.now().strftime("%d.%m.%Y"), "GetFullList": "1"}})
    new_rows = []
    if r and r.json()['success']:
        for doc in r.json()['data']:
            ttn = utils.clean_ttn(str(doc.get('IntDocNumber')))
            if ttn and ttn not in existing:
                new_rows.append({"ТТН": ttn, "Служба": "НП", "Статус": doc.get('StateName', 'Нове'), "Дата": utils.normalize_date(doc.get('CreateTime') or doc.get('DateTime', '')), "Телефон": utils.clean_phone(doc.get('RecipientContactPhone', '')), "Вартість": float(doc.get('Cost') or doc.get('DeclaredCost') or 0), "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False})
    return new_rows

# --- УКРПОШТА ---
def get_up_status_smart(barcode):
    # Примусовий фікс нуля для запиту
    if len(barcode) == 12 and barcode.isdigit(): barcode = "0" + barcode
        
    if config.UP_BEARER_TOKEN and len(config.UP_BEARER_TOKEN) > 10:
        try:
            r = utils.make_request("GET", f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}", headers={"Authorization": f"Bearer {config.UP_BEARER_TOKEN}", "Content-Type": "application/json"}, params={"token": config.UP_USER_TOKEN})
            if r.status_code == 200:
                d = r.json(); st_raw = d.get('lifecycle', {}).get('status'); ev = d.get('lifecycle', {}).get('eventName')
                return ev if ev else (st_raw if st_raw else "В дорозі"), utils.normalize_date(d.get('lifecycle', {}).get('date') or d.get('lastModified')), 0.0
        except: pass
    if config.UP_TRACKING_TOKEN:
        try:
            r = utils.make_request("GET", f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}", headers={"Authorization": f"Bearer {config.UP_TRACKING_TOKEN}", "Accept": "application/json"})
            if r.status_code == 200:
                d = r.json(); 
                if d and isinstance(d, list): return d[-1].get('eventName', 'В дорозі'), utils.normalize_date(d[-1].get('date', '')), 0.0
        except: pass
    return "Не знайдено", None, 0.0

def fetch_new_orders_up(existing):
    if not config.UP_BEARER_TOKEN: return []
    try:
        r = utils.make_request("GET", "https://www.ukrposhta.ua/ecom/0.0.1/shipments", headers={"Authorization": f"Bearer {config.UP_BEARER_TOKEN}", "Content-Type": "application/json"}, params={"token": config.UP_USER_TOKEN, "lastModifiedFrom": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")})
        if r.status_code != 200: return []
        new_rows = []
        for s in (r.json() if isinstance(r.json(), list) else r.json().get('shipments', [])):
            ttn = s.get('barcode')
            if ttn and ttn not in existing:
                new_rows.append({"ТТН": ttn, "Служба": "УП", "Статус": "Нове", "Дата": utils.normalize_date(s.get('registrationDate', '') or s.get('lastModified', '')), "Телефон": utils.clean_phone(s.get('recipient', {}).get('phoneNumber', '')), "Вартість": float(s.get('declaredPrice', 0)), "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False})
        return new_rows
    except: return []

# --- MEEST ---
def get_meest_status(ttn):
    if not config.MEEST_API_TOKEN: return "Не знайдено", "", "", 0.0
    h = {"token": config.MEEST_API_TOKEN, "Content-Type": "application/json"}
    try:
        r = utils.make_request("GET", f"https://api.meest.com/v3.0/openAPI/tracking/{ttn}", headers=h)
        if r.status_code == 200 and r.json().get('result'):
            hist = r.json()['result'].get('history', r.json()['result'])
            if hist: return (hist[-1].get('status_ua') or 'В дорозі'), utils.normalize_date(hist[-1].get('date', '')), 0.0
    except: pass
    try:
        r = utils.make_request("POST", "https://api.meest.com/v3.0/openAPI/trackingShipment", headers=h, json={"number": ttn})
        if r.status_code == 200 and r.json().get('result_table'):
            items = r.json()['result_table'].get('items', [])
            if items: return items[-1].get('ActionMessages_UA', 'В дорозі'), utils.normalize_date(items[-1].get('DateTimeAction', '')), 0.0
    except: pass
    return "Не знайдено", "", "", 0.0

def fetch_new_orders_meest(existing):
    if not config.MEEST_API_TOKEN: return []
    h = {"token": config.MEEST_API_TOKEN, "Content-Type": "application/json"}; new_rows = []
    for i in range(3):
        try:
            r = utils.make_request("GET", f"https://api.meest.com/v3.0/openAPI/parcelsList/{(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')}", headers=h)
            if r.status_code == 200:
                for item in r.json().get('result', []):
                    ttn = utils.clean_ttn(item.get('number', ''))
                    if ttn and ttn not in existing:
                        new_rows.append({"ТТН": ttn, "Служба": "Meest", "Статус": "Нове", "Дата": utils.normalize_date(item.get('date', '')), "Телефон": "", "Вартість": float(item.get('cod', 0) or item.get('declaredValue', 0) or 0), "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False})
        except: pass
    return new_rows

# --- CHECKBOX ---
@st.cache_data(ttl=300)
def fetch_checkbox_archive():
    if not config.CHECKBOX_LOGIN or not config.CHECKBOX_LICENSE_KEY: return None
    try:
        r = utils.make_request("POST", "https://api.checkbox.in.ua/api/v1/cashier/signin", json={"login": config.CHECKBOX_LOGIN, "password": config.CHECKBOX_PASSWORD})
        if not r or r.status_code != 200: return None
        token = r.json().get('access_token')
        r_rec = utils.make_request("GET", "https://api.checkbox.in.ua/api/v1/receipts", headers={"Authorization": f"Bearer {token}", "X-License-Key": config.CHECKBOX_LICENSE_KEY}, params={"desc": "true", "limit": 100, "from_date": (datetime.now() - timedelta(days=30)).isoformat()})
        if not r_rec or r_rec.status_code != 200: return None
        parsed = []
        for item in r_rec.json().get('results', []):
            raw = item.get('created_at', '')
            try: dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=2); f_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            except: f_date = utils.normalize_date(raw)
            parsed.append({"ID": item.get('id'), "Дата": f_date, "Сума": item.get('total_sum', 0) / 100, "Посилання": f"https://check.checkbox.ua/{item.get('id')}"})
        return pd.DataFrame(parsed)
    except: return None

# ==========================================
# 📊 ЛОГІКА ДАНИХ
# ==========================================
def ensure_columns(df):
    for c in config.COLS:
        if c not in df.columns: df[c] = False if c == "Дія" else (0.0 if c == "Вартість" else "")
    return df

def restore_leading_zero(val):
    s = str(val).strip()
    if len(s) == 12 and s.isdigit(): return "0" + s
    return s

def load_data():
    if 'df' not in st.session_state:
        df = load_data_from_gsheets()
        if "Номер ТТН" in df.columns: df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
        df = ensure_columns(df)[config.COLS]
        
        # Відновлюємо нулі
        df['ТТН'] = df['ТТН'].apply(restore_leading_zero)

        for c in ["ТТН", "Служба", "Статус", "Дата", "Телефон", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування"]:
            df[c] = df[c].astype(str).replace('nan', '')
        if 'Вартість' in df.columns:
            df['Вартість'] = df['Вартість'].astype(str).str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
            df['Вартість'] = pd.to_numeric(df['Вартість'], errors='coerce').fillna(0.0)
        df['Дія'] = df['Дія'].replace({'True': True, 'False': False, '': False, 'FALSE': False, 'TRUE': True, 1: True, 0: False}).infer_objects(copy=False).fillna(False).astype(bool)
        df['Дата'] = df['Дата'].apply(utils.normalize_date)
        
        # === ВІЧНА ЧЕРГА: Генеруємо повідомлення одразу після завантаження ===
        df = ensure_messages_exist(df)
        # ====================================================================
        
        st.session_state.df = df
    else: st.session_state.df = ensure_columns(st.session_state.df)

def save_manual(df_to_save):
    try:
        sh = get_google_sheet(); 
        if sh: 
            # === FIX ДЛЯ ГУГЛА: Додаємо апостроф, щоб нуль не зникав ===
            df_export = df_to_save.copy()
            df_export['ТТН'] = df_export['ТТН'].apply(lambda x: "'" + str(x) if str(x).startswith("0") and len(str(x)) > 10 else str(x))
            
            to_save = df_export.drop(columns=['Дія'], errors='ignore').fillna("")
            data = [to_save.columns.values.tolist()] + to_save.values.tolist()
            sh.clear(); sh.update(data)
            
            st.session_state.df = df_to_save; st.cache_data.clear(); return True
    except Exception as e: st.error(f"Save Error: {e}")
    return False

def run_auto_linking(silent=False):
    c_df = fetch_checkbox_archive()
    if c_df is None or c_df.empty: return 0
    c_df['dt_obj'] = pd.to_datetime(c_df['Дата'], errors='coerce'); df = st.session_state.df; matches = 0
    for i, row in df.iterrows():
        if len(str(row['Чек'])) > 5: continue
        try: 
            cost = float(row.get('Вартість', 0)); dt = pd.to_datetime(str(row.get('Дата', '')))
            if cost == 0: continue
            cand = c_df[abs(c_df['Сума'] - cost) < 0.01]
            for _, ch in cand.iterrows():
                if abs((dt - ch['dt_obj']).total_seconds()) <= 70: df.at[i, 'Чек'] = ch['Посилання']; matches += 1; break
        except: continue
    if matches > 0: save_manual(df); 
    if not silent and matches > 0: st.success(f"Знайдено {matches}!"); time.sleep(1.5); st.rerun()
    return matches

def process_status_updates(show_ui=True):
    df = st.session_state.df.copy(); count = 0; total = len(df); 
    pb = st.progress(0) if show_ui else None; txt = st.empty() if show_ui else None
    
    # 1. ТУРБО НП
    np_ttns = []
    for i, row in df.iterrows():
        ttn = utils.clean_ttn(str(row['ТТН']))
        # Відновлюємо нуль для УП, якщо треба
        if len(ttn) == 12 and ttn.isdigit(): ttn = "0" + ttn
        
        svc = row['Служба'] if row['Служба'] not in ["", "Інше"] else utils.identify_service(ttn); 
        df.at[i, 'Служба'] = svc 
        if svc == "НП" and not any(x in str(row['Статус']).lower() for x in ['отримано', 'вручено', 'відмова', 'повернення']):
            np_ttns.append(ttn)

    # 2. ЗАПИТ
    if show_ui and np_ttns: txt.text(f"🚀 Turbo: Перевірка {len(np_ttns)} посилок НП...")
    np_cache = get_np_statuses_bulk(np_ttns)

    # 3. ОНОВЛЕННЯ
    for i, row in df.iterrows():
        if show_ui: pb.progress((i+1)/total)
        ttn = utils.clean_ttn(str(row['ТТН']))
        if len(ttn) == 12 and ttn.isdigit(): ttn = "0" + ttn
        if len(ttn) < 5: continue
        
        svc = df.at[i, 'Служба']
        current = str(df.at[i, 'Статус']).lower()
        
        if not any(x in current for x in ['отримано', 'вручено', 'відмова', 'повернення']):
            s, d, cost = "", None, 0.0
            if svc == "НП" and ttn in np_cache:
                info = np_cache[ttn]; s = info['Status']; cost = info['Cost']
                if info['Phone'] and len(str(row['Телефон'])) < 10: df.at[i, 'Телефон'] = info['Phone']
            elif svc == "УП": 
                if show_ui: txt.text(f"Перевірка УП: {ttn}")
                s, d, cost = get_up_status_smart(ttn)
            elif svc == "Meest": 
                if show_ui: txt.text(f"Перевірка Meest: {ttn}")
                s, p, d, cost = get_meest_status(ttn)
            
            if s: df.at[i, 'Статус'] = s
            if d: df.at[i, 'Дата'] = d
            if cost > 0: df.at[i, 'Вартість'] = cost

    # === ГЕНЕРАЦІЯ ПОВІДОМЛЕНЬ (ВКЛЮЧЕНО В ЦИКЛ) ===
    df = ensure_messages_exist(df)
    
    st.session_state.df = df; save_manual(df); 
    if show_ui: txt.empty(); pb.empty()
    return count, True

def show_analytics(df):
    if df.empty: return
    d = df.copy(); d['Вартість'] = pd.to_numeric(d['Вартість'], errors='coerce').fillna(0)
    d['Day'] = pd.to_datetime(d['Дата'], errors='coerce').dt.date
    today = d[d['Day'] == datetime.now().date()]
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Сьогодні", len(today)); c2.metric("💰 Сума", f"{today['Вартість'].sum():,.0f}"); c3.metric("Всього", len(d))
    st.bar_chart(d.groupby('Day').size())

# --- UI ---
st.markdown("""<style>button[data-baseweb="tab"] {font-size: 24px!important;font-weight: 700!important} div.stButton>button {width: 100%!important}</style>""", unsafe_allow_html=True)
def render_smart_buttons(ph, msg):
    ph = ''.join(filter(str.isdigit, str(ph))); 
    if len(ph)==10: ph='38'+ph
    if len(ph)!=12: st.caption("No phone"); return
    js = f"""<script>function cl(t){{const x=document.createElement('textarea');x.value='{html.escape(msg).replace("'", "\\'")}';document.body.appendChild(x);x.select();document.execCommand('copy');document.body.removeChild(x);const l=document.createElement('a');l.href=t==='v'?'viber://chat?number=%2B{ph}':'sms:+{ph}';l.click()}}</script><div style='display:flex;gap:5px'><button onclick="cl('v')" style='background:#7360f2;color:fff;border:none;padding:10px;border-radius:5px;width:100%'>Viber</button><button onclick="cl('s')" style='background:#f0f2f6;border:1px solid #ccc;padding:10px;border-radius:5px;width:100%'>SMS</button></div>"""
    components.html(js, height=80)

st.title("📦 LogisticManager (v6.0 Final)")
load_data()

with st.sidebar:
    st.header("🎮 Пульт")
    with st.expander("➕ Додати ТТН"):
        with st.form("add"):
            ttn_in = st.text_input("ТТН"); ph_in = st.text_input("Тел")
            if st.form_submit_button("Додати") and ttn_in:
                for t in ttn_in.replace(",", " ").split():
                    tc = utils.clean_ttn(t); 
                    if len(tc) == 12 and tc.isdigit(): tc = "0" + tc 
                    st.session_state.df.loc[len(st.session_state.df)] = {"ТТН": tc, "Служба": utils.identify_service(tc), "Статус": "Нове", "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Телефон": utils.clean_phone(ph_in), "Вартість": 0, "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False}
                save_manual(st.session_state.df); st.rerun()

    if st.button("🔄 Оновити статуси"): process_status_updates(); st.rerun()
    if st.button("📥 Завантажити нові"): 
        new_np=fetch_new_orders_np(st.session_state.df['ТТН'].tolist()); new_up=fetch_new_orders_up(st.session_state.df['ТТН'].tolist()); new_mst=fetch_new_orders_meest(st.session_state.df['ТТН'].tolist())
        if new_np+new_up+new_mst: st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame(new_np+new_up+new_mst)], ignore_index=True); save_manual(st.session_state.df); st.rerun()

t1, t2, t3, t4 = st.tabs(["📨 Черга", "📊 Таблиця", "🧾 Чеки", "📈 Інфо"])
with t1:
    msk = ((st.session_state.df['Повідомлення'].str.len()>5) & (st.session_state.df['Статус СМС']!='Отправлено')); pen = st.session_state.df[msk]
    if pen.empty: st.success("Empty!")
    else:
        for i, r in pen.iterrows():
            with st.container(border=True):
                c1, c2 = st.columns([1, 2]); c1.markdown(f"**{r['Служба']}** `{r['ТТН']}`\n{r['Статус']}"); c2.text_area("", r['Повідомлення'], height=70, key=f"t{i}", label_visibility="collapsed"); render_smart_buttons(r['Телефон'], r['Повідомлення'])
                if st.button("✅ Done", key=f"d{i}"): st.session_state.df.at[i, 'Статус СМС']='Отправлено'; save_manual(st.session_state.df); st.rerun()
with t2:
    ed = st.data_editor(st.session_state.df, height=600, use_container_width=True, hide_index=True)
    if st.button("💾 Save Table"): save_manual(ed); st.rerun()
with t3: 
    if st.button("Load Archive"): st.dataframe(fetch_checkbox_archive())
with t4: show_analytics(st.session_state.df)