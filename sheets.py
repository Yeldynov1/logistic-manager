"""Google Sheets access for Orders workbook."""

import json
import re
from datetime import datetime

import gspread
import pandas as pd
import streamlit as st

import config
import utils

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
    "Післяплата",
    "Дод. інфо",
    "JSON",
    "Індекс",
    "Місто",
]

_UP_BC_COL = UP_SHIPMENTS_HEADERS.index("ШКІ") + 1
_UP_JSON_COL = UP_SHIPMENTS_HEADERS.index("JSON") + 1
_UP_LIGHT_HEADERS = [h for h in UP_SHIPMENTS_HEADERS if h != "JSON"]
_force_sheets_only = False


def set_sheets_migration_mode(enabled: bool = True) -> None:
    """Під час імпорту Sheets→Supabase завжди читати з Google."""
    global _force_sheets_only
    _force_sheets_only = bool(enabled)


def _use_supabase_backend() -> bool:
    if _force_sheets_only:
        return False
    try:
        from storage.supabase_client import use_supabase_backend

        return use_supabase_backend()
    except Exception:
        return False


def _find_up_shipment_sheet_rows(ws, bc_norm: str) -> list[int]:
    """Усі рядки (1-based) з цим ШКІ без get_all_records."""
    if not bc_norm:
        return []
    queries = [bc_norm]
    if len(bc_norm) == 13 and bc_norm.startswith("0"):
        queries.append(bc_norm[1:])
    found: set[int] = set()
    for q in queries:
        try:
            for cell in ws.findall(str(q), in_column=_UP_BC_COL):
                if cell.row > 1:
                    found.add(int(cell.row))
        except gspread.exceptions.CellNotFound:
            continue
        except Exception:
            continue
    return sorted(found)


def _find_up_shipment_sheet_row(ws, bc_norm: str) -> int | None:
    rows = _find_up_shipment_sheet_rows(ws, bc_norm)
    return rows[0] if rows else None


def _read_up_shipments_light(ws) -> list[dict]:
    """Рядки журналу без колонки JSON (менший трафік з Google)."""
    try:
        chunks = ws.batch_get(["A2:L", "N2:O"])
    except Exception:
        return []
    left = chunks[0] if chunks else []
    right = chunks[1] if len(chunks) > 1 else []
    if not left:
        return []
    headers = UP_SHIPMENTS_HEADERS[:12] + ["Індекс", "Місто"]
    records: list[dict] = []
    for i, lrow in enumerate(left):
        lrow = list(lrow or [])
        rrow = list(right[i] if i < len(right) else [])
        if len(lrow) < 12:
            lrow.extend([""] * (12 - len(lrow)))
        if len(rrow) < 2:
            rrow.extend([""] * (2 - len(rrow)))
        rec = dict(zip(headers, lrow[:12] + rrow[:2]))
        rec["JSON"] = ""
        records.append(rec)
    return records


def read_up_shipment_json(barcode: str) -> str:
    """JSON одного відправлення (лише при редагуванні / швидкому edit)."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.read_up_shipment_json(barcode)
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return ""
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(barcode)
        row_i = _find_up_shipment_sheet_row(ws, bc_norm)
        if not row_i:
            return ""
        val = ws.cell(row_i, _UP_JSON_COL).value
        return str(val or "").strip()[:45000]
    except Exception:
        return ""


def _dataframe_from_up_records(rec: list) -> pd.DataFrame:
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
    """Аркуш Orders. Сама книга кешується через @st.cache_resource для швидкості."""
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            st.error("❌ Не знайдено 'gcp_service_account' у Secrets!")
            return None
        return sh.sheet1
    except Exception as e:
        st.error(f"❌ Помилка Google Sheets: {e}")
        return None


def delete_sheet_rows(row_positions, *, silent: bool = False) -> bool:
    """Видалити рядки з аркуша Orders за 0-based позиціями DataFrame (без full resave)."""
    if not row_positions:
        return True
    try:
        sheet = get_google_sheet()
        if not sheet:
            if not silent:
                st.error("❌ Не вдалося підключитися до таблиці!")
            return False
        positions = sorted({int(p) for p in row_positions}, reverse=True)
        for pos in positions:
            sheet.delete_rows(int(pos) + 2)
        return True
    except Exception as e:
        if not silent:
            st.error(f"❌ Помилка видалення рядка: {e}")
        return False


def _sheet_data_row_count(sheet) -> int:
    """Кількість рядків даних (без заголовка)."""
    try:
        vals = sheet.get_all_values()
        if len(vals) <= 1:
            return 0
        return max(0, len(vals) - 1)
    except Exception:
        return -1


@st.cache_data(ttl=60)
def load_data_from_gsheets():
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.load_orders_df()
    sheet = get_google_sheet()
    if not sheet:
        return pd.DataFrame(columns=config.COLS)
    try:
        records = sheet.get_all_records()
        df = pd.DataFrame(records)
        if df.empty:
            if _sheet_data_row_count(sheet) > 0:
                st.warning(
                    "Google Sheets має рядки, але не вдалося їх прочитати (перевірте заголовки)."
                )
            return pd.DataFrame(columns=config.COLS)
        return df
    except Exception as e:
        st.error(f"❌ Помилка читання Google Sheets: {e}")
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
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.load_table_column_order(username)
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
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.save_table_column_order(username, column_order)
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


def save_manual(
    df_to_save, *, clear_cache: bool = True, merge_session: bool = False, silent: bool = False
):
    if _use_supabase_backend():
        from storage import supabase_repo

        try:
            n_rows = len(df_to_save.drop(columns=["Дія"], errors="ignore"))
            session_rows = 0
            if "df" in st.session_state and isinstance(st.session_state.df, pd.DataFrame):
                session_rows = len(st.session_state.df)
            if (
                n_rows > 0
                and session_rows >= 10
                and n_rows < session_rows // 2
            ):
                if not silent:
                    st.error(
                        f"⛔ Збереження скасовано: у файлі лише {n_rows} рядків, "
                        f"у сесії було {session_rows}. Оновіть дані."
                    )
                return False
            if not supabase_repo.save_orders_df(df_to_save):
                if not silent:
                    st.error("❌ Не вдалося зберегти в Supabase.")
                return False
            if merge_session and "df" in st.session_state:
                _merge_df_into_session(st.session_state.df, df_to_save)
            else:
                st.session_state.df = df_to_save
            if clear_cache:
                st.cache_data.clear()
            return True
        except Exception as e:
            if not silent:
                st.error(f"❌ Помилка збереження Supabase: {e}")
            return False
    try:
        sheet = get_google_sheet()
        if sheet:
            to_save = df_to_save.drop(columns=["Дія"], errors="ignore")
            n_rows = len(to_save)
            sheet_rows = _sheet_data_row_count(sheet)
            if n_rows == 0 and sheet_rows > 0:
                if not silent:
                    st.error(
                        "⛔ Збереження скасовано: таблиця порожня, а в Google Sheets ще є дані. "
                        "Перезавантажте сторінку."
                    )
                return False
            session_rows = 0
            if "df" in st.session_state and isinstance(st.session_state.df, pd.DataFrame):
                session_rows = len(st.session_state.df)
            if (
                n_rows > 0
                and session_rows >= 10
                and n_rows < session_rows // 2
            ):
                if not silent:
                    st.error(
                        f"⛔ Збереження скасовано: у файлі лише {n_rows} рядків, "
                        f"у сесії було {session_rows}. Оновіть дані з Google Sheets."
                    )
                return False
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
        if not silent:
            st.error("❌ Не вдалося підключитися до таблиці!")
        return False
    except Exception as e:
        if not silent:
            st.error(f"❌ Помилка збереження: {e}")
        return False


def reload_orders_from_gsheets():
    """Скинути кеш і session_state.df — перечитати аркуш Orders."""
    load_data_from_gsheets.clear()
    st.session_state.pop("df", None)
    st.session_state.pop("main", None)
    st.session_state.pop("_tab2_editor_baseline", None)


@st.cache_resource(show_spinner=False)
def _gspread_client():
    """gspread-клієнт. Кешуємо, щоб не створювати з’єднання щоразу."""
    if "gcp_service_account" not in st.secrets:
        return None
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])


@st.cache_resource(show_spinner=False)
def _open_orders_spreadsheet():
    """Книга Orders. Кеш ресурсу — щоб уникнути `gc.open()` на кожен виклик."""
    gc = _gspread_client()
    if not gc:
        return None
    return gc.open("Orders")


def append_audit_log(user, action, ttn="", detail="", ship_cost=None, receipt_sum=None):
    """Додає рядок на аркуш LogisticAudit (не ламає основний потік при помилці)."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.append_audit_log(
            user, action, ttn, detail, ship_cost=ship_cost, receipt_sum=receipt_sum
        )
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
            utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
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
        ws = sh.worksheet(UP_SHIPMENTS_WS)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=UP_SHIPMENTS_WS, rows=3000, cols=len(UP_SHIPMENTS_HEADERS))
        ws.append_row(UP_SHIPMENTS_HEADERS)
        return ws
    try:
        r1 = ws.row_values(1)
        # Відкат помилкової міграції: «Індекс» був вставлений після «Телефон» і зсунув колонки.
        if len(r1) > 7 and str(r1[7] or "").strip() == "Індекс":
            end_col = chr(ord("A") + len(UP_SHIPMENTS_HEADERS) - 1)
            ws.update(f"A1:{end_col}1", [UP_SHIPMENTS_HEADERS])
        elif len(r1) < len(UP_SHIPMENTS_HEADERS):
            end_col = chr(ord("A") + len(UP_SHIPMENTS_HEADERS) - 1)
            ws.update(f"A1:{end_col}1", [UP_SHIPMENTS_HEADERS])
    except Exception:
        pass
    return ws


def patch_up_shipment_description(barcode: str, description: str) -> bool:
    """Оновити лише колонку «Дод. інфо» в журналі за ШКІ."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.patch_up_shipment_description(barcode, description)
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(barcode)
        if not bc_norm:
            return False
        if "Дод. інфо" not in UP_SHIPMENTS_HEADERS:
            return False
        col = UP_SHIPMENTS_HEADERS.index("Дод. інфо") + 1
        val = utils.normalize_invoice_number(str(description or "").strip())[:500]
        # В Google Sheets цифрові значення можуть втратити leading zero.
        # Для «Дод. інфо» з накладною форсуємо текстовий тип.
        if val.isdigit():
            val = f"'{val}"
        row_i = _find_up_shipment_sheet_row(ws, bc_norm)
        if row_i:
            ws.update_cell(row_i, col, val)
            return True
        return False
    except Exception:
        return False


def append_up_shipment_record(row: dict) -> bool:
    """Додає або оновлює рядок у журналі UP_Shipments (за ШКІ)."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.append_up_shipment_record(row)
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(row.get("ШКІ", ""))
        if not bc_norm:
            return False
        out_row = []
        desc_col = UP_SHIPMENTS_HEADERS.index("Дод. інфо") if "Дод. інфо" in UP_SHIPMENTS_HEADERS else -1
        for h in UP_SHIPMENTS_HEADERS:
            val = str(row.get(h, "") or "")
            if h == "ШКІ":
                val = bc_norm if len(bc_norm) == 13 else val
            if h == "Дод. інфо":
                val = utils.normalize_invoice_number(val.strip())
                if val.isdigit():
                    val = f"'{val}"
            out_row.append(val[:45000] if h == "JSON" else val[:500])
        match_rows = _find_up_shipment_sheet_rows(ws, bc_norm)
        row_i = match_rows[0] if match_rows else None
        old_desc = ""
        if row_i and desc_col >= 0:
            try:
                old_desc = str(ws.cell(row_i, desc_col + 1).value or "").strip()
            except Exception:
                old_desc = ""
        if desc_col >= 0 and not str(out_row[desc_col] or "").strip() and old_desc:
            out_row[desc_col] = old_desc[:500]
        end_col = chr(ord("A") + len(UP_SHIPMENTS_HEADERS) - 1)
        if row_i:
            ws.update(f"A{row_i}:{end_col}{row_i}", [out_row])
            for dup_i in sorted(match_rows[1:], reverse=True):
                ws.delete_rows(dup_i)
            return True
        ws.append_row(out_row)
        return True
    except Exception:
        return False


def delete_up_shipment_record(barcode: str) -> bool:
    """Видаляє рядок з журналу UP_Shipments за ШКІ."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.delete_up_shipment_record(barcode)
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return False
        ws = _ensure_up_shipments_ws(sh)
        bc_norm = _normalize_up_bc(barcode)
        if not bc_norm:
            return False
        row_i = _find_up_shipment_sheet_row(ws, bc_norm)
        if row_i:
            ws.delete_rows(row_i)
            return True
        return False
    except Exception:
        return False


def read_up_shipments(*, include_json: bool = False):
    """Журнал UP_Shipments. За замовчуванням без JSON (швидше для списку)."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.read_up_shipments_df(include_json=include_json)
    try:
        sh = _open_orders_spreadsheet()
        if not sh:
            return pd.DataFrame(columns=UP_SHIPMENTS_HEADERS)
        ws = _ensure_up_shipments_ws(sh)
        if include_json:
            rec = ws.get_all_records()
        else:
            rec = _read_up_shipments_light(ws)
        return _dataframe_from_up_records(rec)
    except Exception:
        return pd.DataFrame(columns=UP_SHIPMENTS_HEADERS)


def read_audit_log():
    """Читає аркуш LogisticAudit (без st.cache_data — кеш у app.py після set_page_config)."""
    if _use_supabase_backend():
        from storage import supabase_repo

        return supabase_repo.read_audit_log_df()
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
