import streamlit as st

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
UP_UUID = get_secret("UP_UUID")
UP_UUID_SAND = get_secret("UP_UUID_SAND")
UP_COUNTERPARTY_TOKEN = get_secret("UP_COUNTERPARTY_TOKEN")
# UUID відправника з кабінету eCom (для майстра «УП ТТН»)
UP_SENDER_UUID = get_secret("UP_SENDER_UUID")
# Посилання «стандарт» у кабінеті ok.ukrposhta (кнопка на вкладці УП ТТН); якщо порожньо — вбудований приклад URL
UP_CABINET_URL = get_secret("UP_CABINET_URL")

# Meest
MEEST_API_TOKEN = get_secret("MEEST_API_TOKEN")
MEEST_CONTRACT_ID = get_secret("MEEST_CONTRACT_ID")