"""Google Sheets access for Orders workbook."""

from datetime import datetime

import gspread
import pandas as pd
import streamlit as st

import config

AUDIT_WORKSHEET_TITLE = "LogisticAudit"
AUDIT_HEADERS = ["Час", "Користувач", "Дія", "ТТН", "Деталі"]


def get_google_sheet():
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            st.error("❌ Не знайдено 'gcp_service_account' у Secrets!")
            return None
        return sh.sheet1
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


def _open_orders_spreadsheet():
    if "gcp_service_account" not in st.secrets:
        return None
    gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    return gc.open("Orders")


def append_audit_log(user, action, ttn="", detail=""):
    """Додає рядок на аркуш LogisticAudit (не ламає основний потік при помилці)."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        try:
            ws = sh.worksheet(AUDIT_WORKSHEET_TITLE)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=AUDIT_WORKSHEET_TITLE, rows=2000, cols=5)
            ws.append_row(AUDIT_HEADERS)
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user or "?")[:80],
            str(action or "")[:80],
            str(ttn or "")[:40],
            str(detail or "")[:500],
        ]
        ws.append_row(row)
        return True
    except Exception:
        return False


def read_audit_log():
    """Читає аркуш LogisticAudit (без st.cache_data — кеш у app.py після set_page_config)."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return pd.DataFrame(columns=AUDIT_HEADERS)
        ws = sh.worksheet(AUDIT_WORKSHEET_TITLE)
        rec = ws.get_all_records()
        if not rec:
            return pd.DataFrame(columns=AUDIT_HEADERS)
        df = pd.DataFrame(rec)
        for h in AUDIT_HEADERS:
            if h not in df.columns:
                df[h] = ""
        df = df[AUDIT_HEADERS]
        return df.iloc[::-1].reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=AUDIT_HEADERS)
