import streamlit as st

# --- 1. КОРИСТУВАЧІ ---
# Паролі не зберігаються тут. Додай у .streamlit/secrets.toml (або Streamlit Cloud Secrets):
#   [auth_users]
#   твій_логін = "$2b$12$..."   # bcrypt; згенерувати: python auth.py 'Пароль'
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
# Функція, щоб не було помилок, якщо ключа немає
def get_secret(key):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return ""

API_KEY_NP = get_secret("NOVA_POSHTA_API_KEY")

# Checkbox
CHECKBOX_LOGIN = get_secret("CHECKBOX_LOGIN")
CHECKBOX_PASSWORD = get_secret("CHECKBOX_PASSWORD")
CHECKBOX_LICENSE_KEY = get_secret("CHECKBOX_LICENSE_KEY")

# Укрпошта
UP_TRACKING_TOKEN = get_secret("UP_TRACKING_TOKEN")
UP_BEARER_TOKEN = get_secret("UP_BEARER_TOKEN")
UP_USER_TOKEN = get_secret("UP_USER_TOKEN")

# Meest
MEEST_API_TOKEN = get_secret("MEEST_API_TOKEN")
MEEST_CONTRACT_ID = get_secret("MEEST_CONTRACT_ID")