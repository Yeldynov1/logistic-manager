"""Google Sheets access for Orders workbook."""

import json
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st

import config

AUDIT_WORKSHEET_TITLE = "LogisticAudit"
UI_SETTINGS_WS = "UISettings"
UI_SETTINGS_HEADERS = ["user", "column_order"]
AUDIT_HEADERS = ["Час", "Користувач", "Дія", "ТТН", "Деталі", "Вартість ТТН", "Сума чеку"]


def _ensure_audit_header_row(ws):
    """Розширює заголовок аркуша до 7 колонок (міграція зі старого формату)."""
    try:
        r1 = ws.row_values(1)
        if len(r1) < len(AUDIT_HEADERS):
            ws.update("A1:G1", [AUDIT_HEADERS])
    except Exception:
        pass


def _fmt_audit_cell(val):
    if val is None:
        return ""
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return ""


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


def _get_or_create_ui_settings_ws():
    sh = _open_orders_spreadsheet()
    if not sh:
        return None
    try:
        ws = sh.worksheet(UI_SETTINGS_WS)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=UI_SETTINGS_WS, rows=200, cols=3)
        ws.update("A1:B1", [UI_SETTINGS_HEADERS])
    try:
        r1 = ws.row_values(1)
        if not r1 or r1[0] != UI_SETTINGS_HEADERS[0]:
            ws.update("A1:B1", [UI_SETTINGS_HEADERS])
    except Exception:
        pass
    return ws


def load_table_column_order(username: str):
    """Порядок колонок таблиці для користувача (список назв) або None."""
    user = str(username or "").strip().lower()
    if not user:
        return None
    try:
        ws = _get_or_create_ui_settings_ws()
        if not ws:
            return None
        for row in ws.get_all_records():
            if str(row.get("user", "")).strip().lower() == user:
                raw = str(row.get("column_order", "")).strip()
                if not raw:
                    return None
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    return [str(c) for c in parsed]
                return None
    except Exception:
        return None
    return None


def save_table_column_order(username: str, column_order: list) -> bool:
    user = str(username or "").strip().lower()
    if not user or not column_order:
        return False
    try:
        ws = _get_or_create_ui_settings_ws()
        if not ws:
            return False
        payload = json.dumps(column_order, ensure_ascii=False)
        records = ws.get_all_records()
        row_idx = None
        for i, row in enumerate(records, start=2):
            if str(row.get("user", "")).strip().lower() == user:
                row_idx = i
                break
        if row_idx:
            ws.update(f"B{row_idx}", [[payload]])
        else:
            ws.append_row([user, payload])
        return True
    except Exception:
        return False


def save_manual(df_to_save, *, clear_cache: bool = True):
    try:
        sheet = get_google_sheet()
        if sheet:
            to_save = df_to_save.drop(columns=["Дія"], errors="ignore")
            order = st.session_state.get("table_column_order")
            if isinstance(order, list) and order:
                cols = [c for c in order if c in to_save.columns]
                rest = [c for c in to_save.columns if c not in cols]
                to_save = to_save[cols + rest]
            # Не замінюємо NaN на порожні значення, щоб не втрачати дані
            data = [to_save.columns.values.tolist()] + to_save.values.tolist()
            sheet.clear()
            sheet.update(data)
            st.session_state.df = df_to_save
            if clear_cache:
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


def append_audit_log(user, action, ttn="", detail="", ship_cost=None, receipt_sum=None):
    """Додає рядок на аркуш LogisticAudit (не ламає основний потік при помилці)."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        try:
            ws = sh.worksheet(AUDIT_WORKSHEET_TITLE)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=AUDIT_WORKSHEET_TITLE, rows=2000, cols=7)
            ws.append_row(AUDIT_HEADERS)
        _ensure_audit_header_row(ws)
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(user or "?")[:80],
            str(action or "")[:80],
            str(ttn or "")[:40],
            str(detail or "")[:500],
            _fmt_audit_cell(ship_cost),
            _fmt_audit_cell(receipt_sum),
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
        _ensure_audit_header_row(ws)
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
