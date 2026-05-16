import os

import streamlit as st

# Секції TOML, куди часто кладуть ключі УП (окрім кореня файлу)
_UP_SECRET_SECTIONS = ("ukrposhta", "ukrposhta_api", "up", "ecom", "ukrposhta_api_keys")


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
UP_SENDER_ADDRESS = get_secret("UP_SENDER_ADDRESS")
UP_SENDER_POSTCODE = get_secret("UP_SENDER_POSTCODE")
UP_SENDER_BRANCH_INDEX = get_secret("UP_SENDER_BRANCH_INDEX")
# Посилання «стандарт» у кабінеті ok.ukrposhta (кнопка на вкладці УП ТТН); якщо порожньо — вбудований приклад URL
UP_CABINET_URL = get_secret("UP_CABINET_URL")

# Meest
MEEST_API_TOKEN = get_secret("MEEST_API_TOKEN")
MEEST_CONTRACT_ID = get_secret("MEEST_CONTRACT_ID")