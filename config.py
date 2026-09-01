import os

import streamlit as st

# Версія програми показується у верхній частині лівої панелі.
APP_VERSION = "v-1.7.1"

# Секції TOML, куди часто кладуть ключі УП (окрім кореня файлу)
_UP_SECRET_SECTIONS = ("ukrposhta", "ukrposhta_api", "up", "ecom", "ukrposhta_api_keys")
_PROM_SECRET_SECTIONS = ("prom", "promua", "prom_ua", "prom.ua")
_EPICENTR_SECRET_SECTIONS = ("epicentr", "epicentrm", "epic", "epicenter")
_EPICENTR_TOKEN_KEYS = (
    "EPICENTR_API_TOKEN",
    "EPICENTR_TOKEN",
    "EPICENTR_API_KEY",
    "EPICENTR_MERCHANT_TOKEN",
)
_EPICENTR_FIELD_ALIASES = (
    "EPICENTR_API_TOKEN",
    "EPICENTR_TOKEN",
    "token",
    "api_token",
    "access_token",
)
_PROM_TOKEN_KEYS = (
    "PROM_UA_TOKEN",
    "PROM_TOKEN",
    "PROM_API_TOKEN",
    "PROM_UA_API_TOKEN",
)
_PROM_FIELD_ALIASES = (
    "PROM_UA_TOKEN",
    "PROM_TOKEN",
    "token",
    "api_token",
    "access_token",
)


def get_secret(key: str, default: str = "") -> str:
    """Читає secret з кореня st.secrets, вкладених [секцій] або змінної середовища."""
    val = ""
    if hasattr(st, "secrets"):
        candidates = []
        try:
            candidates.append(st.secrets[key])
        except Exception:
            pass
        try:
            if hasattr(st.secrets, "get"):
                candidates.append(st.secrets.get(key))
        except Exception:
            pass
        try:
            candidates.append(getattr(st.secrets, key, None))
        except Exception:
            pass
        for section in _UP_SECRET_SECTIONS:
            try:
                block = st.secrets.get(section) if hasattr(st.secrets, "get") else None
                if block is None:
                    block = st.secrets[section]
            except Exception:
                block = None
            if isinstance(block, dict) and key in block:
                candidates.append(block[key])
        try:
            for section_key in st.secrets:
                block = st.secrets[section_key]
                if isinstance(block, dict) and key in block:
                    candidates.append(block[key])
        except Exception:
            pass
        for item in candidates:
            if item is not None and str(item).strip():
                val = str(item).strip()
                break
    if not val:
        val = str(os.environ.get(key, "") or "").strip()
    return val or default


def _normalize_bearer_token(val: str) -> str:
    s = str(val or "").strip()
    if s.lower().startswith("bearer "):
        s = s[7:].strip()
    return s


def _secret_dict_value(block, field: str) -> str:
    if not isinstance(block, dict):
        return ""
    try:
        raw = block.get(field) if hasattr(block, "get") else block[field]
    except Exception:
        raw = None
    if raw is None:
        return ""
    return _normalize_bearer_token(str(raw))


def get_prom_ua_token() -> str:
    """Токен Prom.ua: корінь Secrets, вкладені [prom*], альтернативні імена ключів."""
    for key in _PROM_TOKEN_KEYS:
        val = get_secret(key)
        if val:
            return _normalize_bearer_token(val)
    if hasattr(st, "secrets"):
        for section in _PROM_SECRET_SECTIONS:
            try:
                block = st.secrets.get(section) if hasattr(st.secrets, "get") else None
                if block is None:
                    block = st.secrets[section]
            except Exception:
                block = None
            for field in _PROM_FIELD_ALIASES:
                val = _secret_dict_value(block, field)
                if val:
                    return val
        try:
            for section_key in st.secrets:
                name = str(section_key).lower()
                if "prom" not in name:
                    continue
                try:
                    block = st.secrets[section_key]
                except Exception:
                    continue
                for field in _PROM_FIELD_ALIASES:
                    val = _secret_dict_value(block, field)
                    if val:
                        return val
        except Exception:
            pass
    return ""


def get_epicentr_token() -> str:
    """Токен Епіцентр: корінь Secrets, вкладені [epicentr*], альтернативні імена."""
    for key in _EPICENTR_TOKEN_KEYS:
        val = get_secret(key)
        if val:
            return _normalize_bearer_token(val)
    if hasattr(st, "secrets"):
        for section in _EPICENTR_SECRET_SECTIONS:
            try:
                block = st.secrets.get(section) if hasattr(st.secrets, "get") else None
                if block is None:
                    block = st.secrets[section]
            except Exception:
                block = None
            for field in _EPICENTR_FIELD_ALIASES:
                val = _secret_dict_value(block, field)
                if val:
                    return val
        try:
            for section_key in st.secrets:
                name = str(section_key).lower()
                if "epic" not in name:
                    continue
                try:
                    block = st.secrets[section_key]
                except Exception:
                    continue
                for field in _EPICENTR_FIELD_ALIASES:
                    val = _secret_dict_value(block, field)
                    if val:
                        return val
        except Exception:
            pass
    return ""


def apply_epicentr_secrets() -> None:
    """Оновити EPICENTR_* у config після зміни Secrets."""
    global EPICENTR_API_TOKEN, EPICENTR_IMPORT_LIMIT
    EPICENTR_API_TOKEN = get_epicentr_token()
    try:
        lim = int(get_secret("EPICENTR_IMPORT_LIMIT") or "50")
        EPICENTR_IMPORT_LIMIT = lim
    except ValueError:
        pass


def epicentr_secret_diagnostics() -> dict[str, str]:
    token = get_epicentr_token()
    masked = "—"
    if token:
        masked = f"{token[:6]}…{token[-4:]}" if len(token) > 10 else "✓"
    found_keys = [k for k in _EPICENTR_TOKEN_KEYS if get_secret(k)]
    epic_sections = []
    try:
        for k in st.secrets:
            if "epic" in str(k).lower():
                epic_sections.append(str(k))
    except Exception:
        pass
    return {
        "token": masked,
        "found_keys": ", ".join(found_keys) if found_keys else "(немає)",
        "epic_sections": ", ".join(epic_sections) if epic_sections else "(немає)",
        "hint": (
            "Ключ у корені: EPICENTR_API_TOKEN = \"...\" "
            "(з кабінету Епіцентр → Налаштування → API). Після зміни — Reboot app."
        ),
    }


def apply_prom_secrets() -> None:
    """Оновити PROM_* у config після зміни Secrets (без перезапуску процесу)."""
    global PROM_UA_TOKEN, PROM_UA_SYNC_SEC, PROM_UA_IMPORT_LIMIT
    PROM_UA_TOKEN = get_prom_ua_token()
    try:
        sync = int(get_secret("PROM_UA_SYNC_SEC") or "300")
        PROM_UA_SYNC_SEC = sync
    except ValueError:
        pass
    try:
        lim = int(get_secret("PROM_UA_IMPORT_LIMIT") or "50")
        PROM_UA_IMPORT_LIMIT = lim
    except ValueError:
        pass


def prom_secret_diagnostics() -> dict[str, str]:
    """Діагностика Prom Secrets (без повного токена)."""
    token = get_prom_ua_token()
    masked = "—"
    if token:
        masked = f"{token[:6]}…{token[-4:]}" if len(token) > 10 else "✓"
    found_keys = []
    for key in _PROM_TOKEN_KEYS:
        if get_secret(key):
            found_keys.append(key)
    prom_sections = []
    try:
        for k in st.secrets:
            if "prom" in str(k).lower():
                prom_sections.append(str(k))
    except Exception:
        pass
    return {
        "token": masked,
        "found_keys": ", ".join(found_keys) if found_keys else "(немає)",
        "prom_sections": ", ".join(prom_sections) if prom_sections else "(немає)",
        "hint": (
            "Ключ у корені файлу: PROM_UA_TOKEN = \"...\" "
            "(без Bearer). Після зміни Secrets — Reboot app."
        ),
    }


def list_secret_top_keys():
    try:
        return [str(k) for k in st.secrets.keys()]
    except Exception:
        return []


def list_up_keys_in_secrets() -> list:
    """Усі UP_* з кореня Secrets і вкладених [секцій]."""
    found = []
    try:
        for section in st.secrets:
            name = str(section)
            block = st.secrets[section]
            if isinstance(block, dict):
                for k in block:
                    if str(k).startswith("UP_"):
                        found.append(f"[{name}].{k}")
            elif name.startswith("UP_"):
                found.append(name)
    except Exception:
        pass
    seen = set()
    out = []
    for x in found:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def secret_source(key: str) -> str:
    """Звідки взято значення: файл / [секція] / inline / env."""
    try:
        if key in st.secrets:
            return "secrets (корінь)"
        for section in st.secrets:
            block = st.secrets[section]
            if isinstance(block, dict) and key in block:
                return f"secrets [{section}]"
    except Exception:
        pass
    if str(os.environ.get(key, "") or "").strip():
        return "змінна середовища (не TOML)"
    return ""


def _parse_up_inline_blob(blob: str) -> dict:
    wrapped = f"[up]\n{blob}"
    for mod in ("tomllib", "tomli"):
        try:
            if mod == "tomllib":
                import tomllib as parser  # type: ignore
            else:
                import tomli as parser  # type: ignore
        except ImportError:
            continue
        try:
            table = parser.loads(wrapped).get("up", {})
            if isinstance(table, dict):
                return {
                    str(k): str(v).strip()
                    for k, v in table.items()
                    if str(k).startswith("UP_") and v is not None and str(v).strip()
                }
        except Exception:
            continue
    out = {}
    for line in blob.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k.startswith("UP_") and v:
            out[k] = v
    return out


def load_up_inline_secrets() -> dict:
    """Парсить UP_INLINE_SECRETS — один багаторядковий блок, якщо окремі ключі не зберігаються."""
    blob = get_secret("UP_INLINE_SECRETS")
    if not blob:
        return {}
    return _parse_up_inline_blob(blob)


# --- 1. КОРИСТУВАЧІ ---
# Паролі не зберігаються тут. Додай у .streamlit/secrets.toml (або Streamlit Cloud Secrets):
#   [auth_users]
#   твій_логін = "$2b$12$..."   # bcrypt; згенерувати: python auth.py 'Пароль'
# Менеджер (логін manager) — рядок для Secrets (один рядок = один логін):
#   manager = "$2b$12$OtHNnmJ3aqcYw9js8y474.xxI8x3MvMufWDtlXQsUtgS6eTk7KJq."
# Які вкладки бачить manager — налаштовує admin у sidebar «Доступ менеджера»
# (зберігається в Google Sheets TabAccess або Supabase role_settings).
# Опційно для локальної розробки можна тимчасово задати USERS нижче (plain) — не коміть реальні паролі.
USERS = {}

# --- 2. ФАЙЛ БАЗИ ДАНИХ ---
FILE_NAME = "Orders.xlsx"

# --- 3. СПИСОК КОЛОНОК (Це те, через що була помилка) ---
COLS = [
    "ТТН", "Служба", "Статус", "Дата", "Телефон",
    "Вартість", "Номер накладної", "Чек", "Повідомлення", 
    "Статус СМС", "Статус Нагадування", "Дія"
]

# --- 4. КЛЮЧІ API (Автоматично беруться з Secrets) ---
API_KEY_NP = get_secret("NOVA_POSHTA_API_KEY")
NP_SENDER_REF = get_secret("NP_SENDER_REF")
NP_SENDER_CONTACT_REF = get_secret("NP_SENDER_CONTACT_REF")
NP_SENDER_CITY_REF = get_secret("NP_SENDER_CITY_REF")
NP_SENDER_WAREHOUSE_REF = get_secret("NP_SENDER_WAREHOUSE_REF")
NP_SENDER_PHONE = get_secret("NP_SENDER_PHONE")

# Checkbox
CHECKBOX_LOGIN = get_secret("CHECKBOX_LOGIN")
CHECKBOX_PASSWORD = get_secret("CHECKBOX_PASSWORD")
CHECKBOX_LICENSE_KEY = get_secret("CHECKBOX_LICENSE_KEY")

# Укрпошта
UP_TRACKING_TOKEN = get_secret("UP_TRACKING_TOKEN")
UP_BEARER_TOKEN = get_secret("UP_BEARER_TOKEN")
# Окремий bearer для address-classifier-ws (якщо порожньо — використовується UP_BEARER_TOKEN)
UP_CLASSIFIER_BEARER = get_secret("UP_CLASSIFIER_BEARER")
UP_USER_TOKEN = get_secret("UP_USER_TOKEN")
UP_UUID = get_secret("UP_UUID")
UP_UUID_SAND = get_secret("UP_UUID_SAND")
UP_COUNTERPARTY_TOKEN = get_secret("UP_COUNTERPARTY_TOKEN")
# UUID відправника з кабінету eCom (для майстра «УП ТТН»)
UP_SENDER_UUID = get_secret("UP_SENDER_UUID")
UP_SENDER_ADDRESS_ID = get_secret("UP_SENDER_ADDRESS_ID")
# Відображення блоку «Відправник» у формі УП ТТН (не обовʼязково для API)
UP_SENDER_NAME = get_secret("UP_SENDER_NAME")
UP_SENDER_PHONE = get_secret("UP_SENDER_PHONE")
UP_SENDER_ADDRESS = get_secret("UP_SENDER_ADDRESS")
UP_SENDER_POSTCODE = get_secret("UP_SENDER_POSTCODE")
UP_SENDER_BRANCH_INDEX = get_secret("UP_SENDER_BRANCH_INDEX")
# ФОП: ІПН (10 цифр), опційно IBAN; тип FOP / INDIVIDUAL (за замовч. ФОП якщо в імені «ФОП» або є TIN)
UP_SENDER_TIN = get_secret("UP_SENDER_TIN")
UP_SENDER_BANK_ACCOUNT = get_secret("UP_SENDER_BANK_ACCOUNT")
UP_SENDER_TYPE = get_secret("UP_SENDER_TYPE")
# Посилання «стандарт» у кабінеті ok.ukrposhta (кнопка на вкладці УП ТТН); якщо порожньо — вбудований приклад URL
UP_CABINET_URL = get_secret("UP_CABINET_URL")

# Meest
MEEST_API_TOKEN = get_secret("MEEST_API_TOKEN")
MEEST_CONTRACT_ID = get_secret("MEEST_CONTRACT_ID")

# TurboSMS (видача чеків)
TURBOSMS_TOKEN = get_secret("TURBOSMS_TOKEN")
TURBOSMS_SENDER = get_secret("TURBOSMS_SENDER") or "Zamovlenya"

# Rozetka Seller API (логін кабінету продавця; пароль у Secrets — звичайний текст)
ROZETKA_USERNAME = get_secret("ROZETKA_USERNAME")
ROZETKA_PASSWORD = get_secret("ROZETKA_PASSWORD")
try:
    ROZETKA_TTN_STATUS = int(get_secret("ROZETKA_TTN_STATUS") or "3")
except ValueError:
    ROZETKA_TTN_STATUS = 3

# Prom.ua API
PROM_UA_TOKEN = get_prom_ua_token() or get_secret("PROM_UA_TOKEN")
try:
    PROM_UA_SYNC_SEC = int(get_secret("PROM_UA_SYNC_SEC") or "300")
except ValueError:
    PROM_UA_SYNC_SEC = 300
try:
    PROM_UA_IMPORT_LIMIT = int(get_secret("PROM_UA_IMPORT_LIMIT") or "50")
except ValueError:
    PROM_UA_IMPORT_LIMIT = 50

# Епіцентр Marketplace API
EPICENTR_API_TOKEN = get_epicentr_token() or get_secret("EPICENTR_API_TOKEN")
try:
    EPICENTR_IMPORT_LIMIT = int(get_secret("EPICENTR_IMPORT_LIMIT") or "50")
except ValueError:
    EPICENTR_IMPORT_LIMIT = 50
