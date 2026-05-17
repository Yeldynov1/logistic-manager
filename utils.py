import pandas as pd
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import re
import webbrowser

# Meest часто: «Відправлення отримане» (не «отримано») — треба окремі форми слова.
DELIVERED_STATUS_KEYWORDS = [
    "отримано",
    "отримане",
    "отримані",
    "отриманий",
    "отримана",
    "доставлено",
    "вручено",
    "delivered",
    "відділенні",
]
# Після цих статусів трекінг не оновлюємо (НП / УП / Meest).
STOP_TRACKING_STATUS_KEYWORDS = ["отримано", "отримане", "отримані", "вручено"]
DECLINED_STATUS_KEYWORDS = ['відмова']

# --- ІМПОРТИ БІБЛІОТЕК ---
try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL = True
except ImportError:
    curl_requests = None
    HAS_CURL = False

import json as _json
import requests as std_requests

# --- ФУНКЦІЇ ---

_last_request_error = ""


def get_last_request_error() -> str:
    return _last_request_error


class SimpleHttpResponse:
    """Мінімальна обгортка відповіді (requests або urllib fallback)."""

    __slots__ = ("status_code", "text", "content")

    def __init__(self, status_code: int, text: str):
        self.status_code = int(status_code)
        self.text = text or ""
        self.content = self.text.encode("utf-8", errors="replace")

    def json(self):
        return _json.loads(self.text)


def _urllib_request(method: str, url: str, **kwargs):
    import urllib.error
    import urllib.parse
    import urllib.request

    global _last_request_error
    headers = dict(kwargs.get("headers") or {})
    headers.setdefault("User-Agent", "logistic-manager/1.0")
    params = kwargs.get("params")
    timeout = kwargs.get("timeout", 25)
    full_url = url
    if params:
        sep = "&" if "?" in full_url else "?"
        full_url = f"{full_url}{sep}{urllib.parse.urlencode(params)}"

    body_bytes = None
    if kwargs.get("json") is not None:
        body_bytes = _json.dumps(kwargs["json"]).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
    elif kwargs.get("data") is not None:
        data = kwargs["data"]
        if isinstance(data, dict):
            body_bytes = urllib.parse.urlencode(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body_bytes = data

    req = urllib.request.Request(
        full_url,
        data=body_bytes,
        headers=headers,
        method=str(method or "GET").upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return SimpleHttpResponse(resp.status, text)
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return SimpleHttpResponse(e.code, text)
    except Exception as e:
        _last_request_error = str(e)[:400]
        return None


def make_request(method, url, **kwargs):
    global _last_request_error
    _last_request_error = ""
    kwargs.setdefault("timeout", 25)
    if HAS_CURL and curl_requests is not None:
        try:
            return curl_requests.request(method, url, impersonate="chrome120", **kwargs)
        except Exception as e:
            _last_request_error = str(e)[:400]
    try:
        return std_requests.request(method, url, **kwargs)
    except Exception as e:
        _last_request_error = _last_request_error or str(e)[:400]
    return _urllib_request(method, url, **kwargs)

def clean_ttn(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    s = s.replace("-", "").replace(" ", "")
    return s.upper()


def normalize_invoice_number(val):
    """Номер накладної (НП тощо): якщо рівно 5 цифр — додаємо 0 спереду (6 цифр). Інакше без змін."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, bool):
        s = str(val).strip()
    elif isinstance(val, (int, float)):
        try:
            fv = float(val)
            if fv == int(fv):
                s = str(int(abs(fv)))
            else:
                s = str(val).strip()
        except (TypeError, ValueError):
            s = str(val).strip()
    else:
        s = str(val).strip().replace("'", "")
    if s.lower().endswith(".0") and len(s) > 2 and s[:-2].isdigit():
        s = s[:-2]
    if not s or s.lower() == "nan":
        return ""
    if s.isdigit() and len(s) == 5:
        return "0" + s
    return s

# Блок із типовим записом UA-номера (текст навколо ігнорується)
_UA_PHONE_BLOCK = re.compile(
    r'(?:\+?\s*380|\+?\s*38\s*0|(?<!\d)380)(?:[\s\-\(\)]*\d){9}'
    r'|'
    r'(?<!\d)0(?:[\s\-\(\)]*\d){9}(?!\d)',
    re.IGNORECASE,
)


def _normalize_ua_phone_digits(digits: str) -> str:
    if not digits:
        return ""
    d = digits
    if d.startswith('0'):
        d = '38' + d
    if not d.startswith('380') and len(d) == 9:
        d = '380' + d
    if len(d) == 12 and d.startswith('380'):
        return d
    return ""


def extract_first_ua_phone(text: str) -> str:
    """Змішаний рядок (ПІБ + телефон тощо) → перший нормалізований номер 380… або ''."""
    if text is None:
        return ""
    try:
        if pd.isna(text):
            return ""
    except TypeError:
        pass
    s = str(text).strip()
    if not s or s.lower() == 'nan':
        return ""
    for m in _UA_PHONE_BLOCK.finditer(s):
        d = ''.join(filter(str.isdigit, m.group()))
        n = _normalize_ua_phone_digits(d)
        if n:
            return n
    return ""


def clean_phone(val):
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s.lower() == 'nan':
        return ""
    extracted = extract_first_ua_phone(s)
    if extracted:
        return extracted
    digits = ''.join(filter(str.isdigit, s))
    if digits.startswith('0'):
        digits = '38' + digits
    if not digits.startswith('380') and len(digits) == 9:
        digits = '380' + digits
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
    if any(
        x in val
        for x in [
            "отримано",
            "отримане",
            "отримані",
            "отриманий",
            "отримана",
            "вручено",
            "delivered",
            "завершено",
        ]
    ):
        return "background-color: #abf7b1; color: black"
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
