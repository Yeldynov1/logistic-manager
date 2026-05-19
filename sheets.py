"""Google Sheets access for Orders workbook."""

import json
import re
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st

import config

AUDIT_WORKSHEET_TITLE = "LogisticAudit"
UI_SETTINGS_WS = "UISettings"
UI_SETTINGS_HEADERS = ["user", "column_order"]
AUDIT_HEADERS = ["Час", "Користувач", "Дія", "ТТН", "Деталі", "Вартість ТТН", "Сума чеку"]
UP_SHIPMENTS_WS = "UP_Shipments"
def _normalize_up_bc(barcode) -> str:
    """Єдиний ключ ШКІ для пошуку/дедуплікації (13 цифр з провідним 0)."""
    s = str(barcode or "").strip()
    if not s or s.lower() == "nan":
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return s
    if len(digits) == 12:
        digits = "0" + digits
    return digits


UP_SHIPMENTS_HEADERS = [
    "Час",
    "Користувач",
    "ШКІ",
    "UUID",
    "Статус УП",
    "Отримувач",
    "Телефон",
    "Тариф",
    "Доставка",
    "Вартість",
    "Дод. інфо",
    "JSON",
]


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


def _sheet_headers(sheet):
    """Заголовки аркуша Orders (без «Дія»)."""
    row1 = sheet.row_values(1)
    return [h for h in row1 if h and str(h).strip() and str(h).strip() != "Дія"]


def update_table_cell_edits(edited_rows: dict, extra_cells=None, *, silent: bool = False) -> bool:
    """Точкове оновлення комірок у Google Sheet (без clear/update всієї таблиці)."""
    if not edited_rows and not extra_cells:
        return True
    try:
        sheet = get_google_sheet()
        if not sheet:
            if not silent:
                st.error("❌ Не вдалося підключитися до таблиці!")
            return False
        headers = _sheet_headers(sheet)
        if not headers:
            return False
        col_to_idx = {str(h).strip(): i + 1 for i, h in enumerate(headers)}
        batch = []
        seen = set()

        def _add(row_pos, col_name, value):
            col_name = str(col_name).strip()
            if col_name not in col_to_idx or col_name == "Дія":
                return
            key = (int(row_pos), col_name)
            if key in seen:
                return
            seen.add(key)
            row_num = int(row_pos) + 2
            col_num = col_to_idx[col_name]
            a1 = gspread.utils.rowcol_to_a1(row_num, col_num)
            if value is None:
                cell_val = ""
            elif isinstance(value, bool):
                cell_val = value
            elif isinstance(value, float) and col_name == "Вартість":
                cell_val = value
            else:
                cell_val = str(value)
            batch.append({"range": a1, "values": [[cell_val]]})

        for idx, changes in (edited_rows or {}).items():
            for col, val in (changes or {}).items():
                _add(int(idx), col, val)

        for row_pos, col_name, value in extra_cells or []:
            _add(row_pos, col_name, value)

        if not batch:
            return True
        sheet.batch_update(batch, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        if not silent:
            st.error(f"❌ Помилка збереження комірки: {e}")
        return False


def _merge_df_into_session(base: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Оновлює рядки на місці — той самий DataFrame, менше «стрибків» у data_editor."""
    for idx in incoming.index:
        if idx not in base.index:
            continue
        for col in incoming.columns:
            if col in base.columns:
                base.at[idx, col] = incoming.at[idx, col]
    return base


def save_manual(df_to_save, *, clear_cache: bool = True, merge_session: bool = False):
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
            if merge_session and "df" in st.session_state:
                _merge_df_into_session(st.session_state.df, df_to_save)
            else:
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


def _ensure_up_shipments_ws(sh):
    try:
        return sh.worksheet(UP_SHIPMENTS_WS)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=UP_SHIPMENTS_WS, rows=3000, cols=len(UP_SHIPMENTS_HEADERS))
        ws.append_row(UP_SHIPMENTS_HEADERS)
        return ws


def append_up_shipment_record(row: dict) -> bool:
    """Додає або оновлює рядок у журналі UP_Shipments (за ШКІ)."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(row.get("ШКІ", ""))
        if not bc_norm:
            return False
        rec = ws.get_all_records()
        out_row = []
        for h in UP_SHIPMENTS_HEADERS:
            val = str(row.get(h, "") or "")
            if h == "ШКІ":
                val = bc_norm if len(bc_norm) == 13 else val
            out_row.append(val[:45000] if h == "JSON" else val[:500])
        match_rows = []
        for i, r in enumerate(rec, start=2):
            if _normalize_up_bc(r.get("ШКІ", "")) == bc_norm:
                match_rows.append(i)
        end_col = chr(ord("A") + len(UP_SHIPMENTS_HEADERS) - 1)
        if match_rows:
            ws.update(f"A{match_rows[0]}:{end_col}{match_rows[0]}", [out_row])
            for i in sorted(match_rows[1:], reverse=True):
                ws.delete_rows(i)
            return True
        ws.append_row(out_row)
        return True
    except Exception:
        return False


def delete_up_shipment_record(barcode: str) -> bool:
    """Видаляє рядок з журналу UP_Shipments за ШКІ."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(barcode)
        if not bc_norm:
            return False
        rec = ws.get_all_records()
        deleted = False
        for i in sorted(
            (
                row_i
                for row_i, r in enumerate(rec, start=2)
                if _normalize_up_bc(r.get("ШКІ", "")) == bc_norm
            ),
            reverse=True,
        ):
            ws.delete_rows(i)
            deleted = True
        return deleted
    except Exception:
        return False


def read_up_shipments():
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return pd.DataFrame(columns=UP_SHIPMENTS_HEADERS)
        ws = _ensure_up_shipments_ws(sh)
        rec = ws.get_all_records()
        if not rec:
            return pd.DataFrame(columns=UP_SHIPMENTS_HEADERS)
        df = pd.DataFrame(rec)
        if "Вартість" not in df.columns and "Вартість доставки" in df.columns:
            df["Вартість"] = df["Вартість доставки"]
        for h in UP_SHIPMENTS_HEADERS:
            if h not in df.columns:
                df[h] = ""
        df = df[UP_SHIPMENTS_HEADERS]
        if "Час" in df.columns:
            df = df.sort_values("Час", ascending=False)
        if "ШКІ" in df.columns and not df.empty:
            df = df.copy()
            df["_bc_norm"] = df["ШКІ"].apply(_normalize_up_bc)
            df = df[df["_bc_norm"].astype(str).str.len() > 0]
            df = df.drop_duplicates(subset=["_bc_norm"], keep="first")
            df = df.drop(columns=["_bc_norm"])
        return df.reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=UP_SHIPMENTS_HEADERS)


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
