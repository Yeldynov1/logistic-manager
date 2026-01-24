# config.py
import streamlit as st
import os

def get_secret(key):
    # Спочатку шукаємо в секретах Streamlit, потім в змінних оточення
    if key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, "")

# Константи
NP_API_KEY = get_secret("NP_API_KEY")
# Інші ключі додавай так само
# config.py
# Налаштування користувачів
USERS = {
    "1": "1"
}

FILE_NAME = "Orders.xlsx"
# ... решта коду хай залишається як є