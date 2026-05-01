import pandas as pd
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import re
import webbrowser

DELIVERED_STATUS_KEYWORDS = ['отримано', 'доставлено', 'вручено', 'delivered', 'відділенні']
STOP_TRACKING_STATUS_KEYWORDS = ['отримано', 'вручено']
DECLINED_STATUS_KEYWORDS = ['відмова']

# --- ІМПОРТИ БІБЛІОТЕК ---
try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

try:
    from curl_cffi import requests
    HAS_CURL = True
except ImportError:
    import requests
    HAS_CURL = False

# --- ФУНКЦІЇ ---

def make_request(method, url, **kwargs):
    kwargs['timeout'] = 15
    try:
        if HAS_CURL: return requests.request(method, url, impersonate="chrome120", **kwargs)
        return requests.request(method, url, **kwargs)
    except Exception: return None

def clean_ttn(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    s = s.replace("-", "").replace(" ", "")
    return s.upper()

def clean_phone(val):
    if pd.isna(val): return ""
    digits = ''.join(filter(str.isdigit, str(val)))
    if digits.startswith('0'): digits = '38' + digits
    if not digits.startswith('380') and len(digits) == 9: digits = '380' + digits
    return digits


def status_has_any(status_value, keywords):
    status_text = str(status_value).lower()
    return any(keyword in status_text for keyword in keywords)


def read_uploaded_table(uploaded_file, min_columns=1, require_non_empty=False, csv_encodings=None, csv_separators=None):
    if uploaded_file is None:
        return None

    encodings = csv_encodings or ['utf-8', 'cp1251', 'latin1', 'iso-8859-1']
    separators = csv_separators or [',', ';', '\t', '|', ' ']

    if uploaded_file.name.endswith('.csv'):
        for enc in encodings:
            for sep in separators:
                try:
                    uploaded_file.seek(0)
                    df_test = pd.read_csv(uploaded_file, dtype=str, encoding=enc, sep=sep)
                    if len(df_test.columns) < min_columns:
                        continue
                    if require_non_empty and len(df_test) == 0:
                        continue
                    return df_test
                except Exception:
                    continue
        return None

    try:
        uploaded_file.seek(0)
        df_test = pd.read_excel(uploaded_file, dtype=str)
        if len(df_test.columns) < min_columns:
            return None
        if require_non_empty and len(df_test) == 0:
            return None
        return df_test
    except Exception:
        return None

def identify_service(ttn):
    s = str(ttn).strip().upper()
    if any(s.startswith(x) for x in ["CV", "MY", "RO", "ZA", "T", "720", "AP"]): return "Meest"
    
    clean = ''.join(filter(str.isdigit, s))
    if len(clean) == 14: return "НП"
    if len(clean) == 13: return "УП"
    if len(clean) in [10, 12]: return "Meest"
    
    if len(s) == 13 and s[0:2].isalpha() and s.endswith("UA"): return "УП"
    return "Інше"

def normalize_date(val):
    if not val or pd.isna(val): return ""
    s = str(val).strip().replace("T", " ")[:19]
    if len(s) >= 10 and (s[2] in ['-', '.'] or s[2:4].isdigit() == False):
        for fmt in ["%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d-%m-%Y", "%d.%m.%Y"]:
            try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except Exception: continue
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in formats:
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except Exception: continue
    return s

def color_status(val):
    if not isinstance(val, str): return ''
    val = val.lower()
    if any(x in val for x in ['отримано', 'вручено', 'delivered', 'завершено']): return 'background-color: #abf7b1; color: black'
    if any(x in val for x in ['відмова', 'повернення', 'denied', 'не доставлено']): return 'background-color: #ffadad; color: black'
    if any(x in val for x in ['прибув', 'прибуло', 'відділенні', 'надійшло', 'department', 'змінено']): return 'background-color: #ffea85; color: black'
    return ''

def process_viber_send(phone, text):
    if HAS_CLIPBOARD:
        try: pyperclip.copy(text); st.toast("Текст скопійовано!", icon="📋")
        except Exception: pass
    ph = clean_phone(phone)
    if ph:
        try: webbrowser.open(f"viber://chat?number=%2B{ph}")
        except Exception:
            link = f"viber://chat?number=%2B{ph}"
            components.html(f"<script>window.open('{link}', '_self');</script>", height=0)

def process_sms_send(phone, text):
    if HAS_CLIPBOARD:
        try: pyperclip.copy(text); st.toast("Текст скопійовано!", icon="📋")
        except Exception: pass
    ph = clean_phone(phone)
    if ph:
        try: webbrowser.open(f"sms:+{ph}")
        except Exception:
            link = f"sms:+{ph}"
            components.html(f"<script>window.open('{link}', '_self');</script>", height=0)