import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import streamlit as st

# Часовий пояс програми — Київ (Україна)
KYIV_TZ = ZoneInfo("Europe/Kyiv")


def now_kyiv() -> datetime:
    """Поточний момент у Europe/Kyiv (з tzinfo)."""
    return datetime.now(KYIV_TZ)


def now_kyiv_naive() -> datetime:
    """Локальний час Києва без tzinfo — для колонок «Дата»/«Час» і порівнянь."""
    return now_kyiv().replace(tzinfo=None)


def today_kyiv():
    """Сьогоднішня дата за київським календарем."""
    return now_kyiv().date()


def utc_naive_to_kyiv_naive(dt: datetime) -> datetime:
    """Конвертує naive UTC у naive локальний час Києва."""
    return dt.replace(tzinfo=timezone.utc).astimezone(KYIV_TZ).replace(tzinfo=None)
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
# Meest у «Видати чек» — лише фінальне вручення (не «у відділенні», не «в дорозі»).
MEEST_CHECKOUT_STATUS_KEYWORDS = [
    "отримано",
    "отримане",
    "отримані",
    "отриманий",
    "отримана",
    "доставлено",
    "вручено",
    "delivered",
    "вручен",
    "доручен",
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
import warnings
import requests as std_requests

try:
    import certifi

    HAS_CERTIFI = True
except ImportError:
    certifi = None
    HAS_CERTIFI = False

# --- ФУНКЦІЇ ---


ROZETKA_API_HOSTS = ("api-seller.rozetka.com.ua", "api.seller.rozetka.com.ua")


def _ssl_context():
    """SSL з пакетом CA (certifi) — усуває CERTIFICATE_VERIFY_FAILED на macOS."""
    import ssl

    if HAS_CERTIFI:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _ssl_context_unverified():
    import ssl

    return ssl._create_unverified_context()


def _requests_verify():
    return certifi.where() if HAS_CERTIFI else True


def _is_ssl_verify_failure(msg: str) -> bool:
    m = (msg or "").lower()
    return (
        "certificate_verify_failed" in m
        or "unable to get local issuer certificate" in m
        or "certificate has expired" in m
        or "ssl: certificate" in m
    )


def _rozetka_ssl_workaround(url: str) -> bool:
    u = str(url or "").lower()
    return any(h in u for h in ROZETKA_API_HOSTS)

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
    ssl_unverified = bool(kwargs.pop("_ssl_unverified", False))
    ctx = _ssl_context_unverified() if ssl_unverified else _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
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


def _make_request_once(method, url, **kwargs):
    """Один прохід HTTP без повтору SSL для Rozetka."""
    global _last_request_error
    _last_request_error = ""
    kwargs.setdefault("timeout", 25)
    url_s = str(url or "").lower()
    prefer_urllib = "ukrposhta.ua" in url_s
    ssl_unverified = bool(kwargs.get("_ssl_unverified"))

    if prefer_urllib:
        resp = _urllib_request(method, url, **kwargs)
        if resp is not None:
            return resp

    req_kw = dict(kwargs)
    if ssl_unverified:
        req_kw["verify"] = False
    else:
        req_kw.setdefault("verify", _requests_verify())

    if HAS_CURL and curl_requests is not None:
        try:
            resp = curl_requests.request(
                method, url, impersonate="chrome120", **req_kw
            )
            if resp is not None:
                return resp
            _last_request_error = _last_request_error or "curl_cffi повернув порожню відповідь"
        except Exception as e:
            _last_request_error = str(e)[:400]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = std_requests.request(method, url, **req_kw)
        if resp is not None:
            return resp
        _last_request_error = _last_request_error or "requests повернув порожню відповідь"
    except Exception as e:
        _last_request_error = _last_request_error or str(e)[:400]
    if not prefer_urllib:
        resp = _urllib_request(method, url, **kwargs)
        if resp is not None:
            return resp
    return None


def make_request(method, url, **kwargs):
    """HTTP-запит: для ukrposhta.ua — спочатку urllib; інакше curl → requests → urllib."""
    resp = _make_request_once(method, url, **kwargs)
    if resp is not None:
        return resp
    if _rozetka_ssl_workaround(url) and _is_ssl_verify_failure(_last_request_error):
        retry_kw = dict(kwargs)
        retry_kw["verify"] = False
        retry_kw["_ssl_unverified"] = True
        return _make_request_once(method, url, **retry_kw)
    return None

def clean_ttn(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    s = s.replace("-", "").replace(" ", "")
    return s.upper()


def session_cache_is_fresh(storage_key: str, ttl_sec: float = 180.0) -> bool:
    """Чи є значення в session_state і чи не прострочене (для списків Rozetka/Prom)."""
    import time

    import streamlit as st

    return (
        storage_key in st.session_state
        and (time.time() - float(st.session_state.get(f"{storage_key}__ts") or 0)) < ttl_sec
    )


def session_cache_touch(storage_key: str) -> None:
    import time

    import streamlit as st

    st.session_state[f"{storage_key}__ts"] = time.time()


def session_cache_invalidate(storage_key: str) -> None:
    import streamlit as st

    st.session_state.pop(storage_key, None)
    st.session_state.pop(f"{storage_key}__ts", None)


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


def receipt_not_required_identifier(val) -> bool:
    """Накладна/ТТН з * на початку — чек Checkbox не видаємо."""
    s = str(val or "").strip()
    return bool(s and s.lower() != "nan" and s.startswith("*"))


def row_receipt_not_required(row) -> bool:
    for key in ("Номер накладної", "ТТН"):
        if receipt_not_required_identifier(row.get(key) if hasattr(row, "get") else ""):
            return True
    return False


def row_is_meest(row) -> bool:
    svc = str(row.get("Служба", "") or "").strip().lower()
    if svc == "meest" or "meest" in svc:
        return True
    ttn = str(row.get("ТТН", "") or "").strip()
    if ttn:
        try:
            return identify_service(ttn) == "Meest"
        except Exception:
            pass
    return False


def apply_no_receipt_auto_sent(df) -> int:
    """
    Накладна з * — чек не потрібен: при статусі «отримано» закриваємо рядок як «Отправлено».
    Повертає кількість оновлених рядків.
    """
    if df is None or df.empty or "Статус СМС" not in df.columns:
        return 0
    n = 0
    for i, row in df.iterrows():
        if not row_receipt_not_required(row):
            continue
        if str(row.get("Статус СМС", "")).strip() == "Отправлено":
            continue
        status = str(row.get("Статус", "")).lower()
        if not status_has_any(status, DELIVERED_STATUS_KEYWORDS):
            continue
        df.at[i, "Статус СМС"] = "Отправлено"
        n += 1
    return n


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


def sort_orders_by_date(df: pd.DataFrame, *, ascending: bool = False) -> pd.DataFrame:
    """Сортування замовлень за «Дата» (за замовчуванням — нові зверху)."""
    if df is None or df.empty or "Дата" not in df.columns:
        return df
    out = df.copy()
    out["_sort_dt"] = pd.to_datetime(out["Дата"].map(normalize_date), errors="coerce")
    out = out.sort_values("_sort_dt", ascending=ascending, na_position="last")
    return out.drop(columns=["_sort_dt"]).reset_index(drop=True)


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


def _turbosms_response_ok(code, status: str) -> bool:
    """TurboSMS: 0/OK або 800–805 / SUCCESS_* — прийнято до відправки."""
    s = str(status or "").strip().upper()
    if s in ("", "OK") or s.startswith("SUCCESS_"):
        return True
    if code in (0, "0", None):
        return True
    try:
        c = int(code)
        if c == 0 or 800 <= c <= 805:
            return True
    except (TypeError, ValueError):
        pass
    return code in (800, 801, 802, 803, 804, 805)


def turbosms_configured() -> bool:
    import config

    token = str(getattr(config, "TURBOSMS_TOKEN", "") or "").strip()
    sender = str(getattr(config, "TURBOSMS_SENDER", "") or "").strip()
    return bool(token and sender)


def turbosms_send(phone: str, text: str):
    """
    Відправка SMS через TurboSMS HTTP API.
    Повертає (success, message_id|None, error_text).
    """
    import config

    token = str(getattr(config, "TURBOSMS_TOKEN", "") or "").strip()
    sender = str(getattr(config, "TURBOSMS_SENDER", "") or "Zamovlenya").strip()
    if not token:
        return False, None, "Немає TURBOSMS_TOKEN у Secrets."
    if not sender:
        return False, None, "Немає TURBOSMS_SENDER у Secrets."
    ph = clean_phone(phone)
    if len(ph) != 12 or not ph.startswith("380"):
        return False, None, f"Некоректний телефон для TurboSMS: {phone}"
    msg = str(text or "").strip()
    if len(msg) < 2:
        return False, None, "Порожній текст SMS."

    url = "https://api.turbosms.ua/message/send.json"
    body = {
        "recipients": [ph],
        "sms": {"sender": sender[:25], "text": msg[:1521]},
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    r = make_request(
        "POST",
        url,
        params={"token": token},
        headers=headers,
        json=body,
        timeout=45,
    )
    if not r:
        hint = get_last_request_error()
        return False, None, hint or "Немає відповіді від TurboSMS."
    try:
        data = r.json()
    except Exception:
        return False, None, f"TurboSMS HTTP {r.status_code}: {(r.text or '')[:200]}"

    top_code = data.get("response_code")
    top_status = str(data.get("response_status") or "")

    result = data.get("response_result")
    if isinstance(result, list) and result:
        item = result[0] if isinstance(result[0], dict) else {}
        mid = item.get("message_id")
        item_code = item.get("response_code", 0)
        item_status = str(item.get("response_status") or "")
        if mid:
            return True, str(mid), ""
        if _turbosms_response_ok(item_code, item_status):
            return True, None, ""
        if not _turbosms_response_ok(top_code, top_status):
            return False, None, item_status or str(item_code) or top_status
    elif isinstance(result, dict):
        mid = result.get("message_id")
        if mid:
            return True, str(mid), ""

    if _turbosms_response_ok(top_code, top_status):
        return True, None, ""
    return False, None, f"TurboSMS: {top_status or top_code or data}"
