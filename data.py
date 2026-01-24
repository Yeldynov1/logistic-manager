# data.py
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# Назва листа в Гугл Таблиці
WORKSHEET_NAME = "Orders"

def get_connection():
    """Створює з'єднання з Google Sheets"""
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    """Завантажує дані з Гугл Таблиці у DataFrame"""
    try:
        conn = get_connection()
        # ttl=0 означає, що ми не кешуємо дані надовго, щоб бачити зміни відразу
        df = conn.read(worksheet=WORKSHEET_NAME, ttl=0)
        
        # Якщо таблиця порожня або нова, повертаємо пустий шаблон
        if df.empty:
            return pd.DataFrame(columns=["ТТН", "Служба", "Статус", "Дата", "Телефон", "Вартість", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування"])
            
        return df
    except Exception as e:
        st.error(f"Помилка завантаження бази даних: {e}")
        return pd.DataFrame()

def save_data(df):
    """Зберігає DataFrame назад у Гугл Таблицю"""
    try:
        conn = get_connection()
        conn.update(worksheet=WORKSHEET_NAME, data=df)
        st.toast("✅ Дані успішно збережено в хмару!", icon="☁️")
    except Exception as e:
        st.error(f"Не вдалося зберегти дані: {e}")