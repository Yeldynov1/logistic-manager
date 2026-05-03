"""Google Sheets access for Orders workbook."""

import gspread
import pandas as pd
import streamlit as st

import config


def get_google_sheet():
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("❌ Не знайдено 'gcp_service_account' у Secrets!")
            return None
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc.open("Orders").sheet1
    except Exception as e:
        st.error(f"❌ Помилка Google Sheets: {e}")
        return None


@st.cache_data(ttl=60)
def load_data_from_gsheets():
    sheet = get_google_sheet()
    if not sheet:
        return pd.DataFrame(columns=config.COLS)
    try:
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(columns=config.COLS)
        return df
    except Exception:
        return pd.DataFrame(columns=config.COLS)


def save_manual(df_to_save):
    try:
        sheet = get_google_sheet()
        if sheet:
            to_save = df_to_save.drop(columns=["Дія"], errors="ignore")
            # Не замінюємо NaN на порожні значення, щоб не втрачати дані
            data = [to_save.columns.values.tolist()] + to_save.values.tolist()
            sheet.clear()
            sheet.update(data)
            st.session_state.df = df_to_save
            st.cache_data.clear()
            return True
        st.error("❌ Не вдалося підключитися до таблиці!")
        return False
    except Exception as e:
        st.error(f"❌ Помилка збереження: {e}")
        return False
