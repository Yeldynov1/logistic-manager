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
USERS = {
    "admin": "24688642",
    "user": "24688642"
}