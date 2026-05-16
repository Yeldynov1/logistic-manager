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