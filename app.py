import streamlit as st
import pandas as pd
import time
import threading
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import hashlib
import html
import requests
import re

# Selenium для серверного режиму (headless)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# --- ПІДКЛЮЧЕННЯ МОДУЛІВ ---
import auth  # Локальний вхід (bcrypt + Secrets)
import config  # Налаштування
import utils  # Технічні функції

# --- НАЛАШТУВАННЯ СТОРІНКИ ---
st.set_page_config(page_title="Alius Checkbox", page_icon="☑️", layout="wide")

import sheets  # Google Sheets (після set_page_config — коректна реєстрація st.cache_data у sheets)


@st.cache_data(ttl=20)
def _cached_audit_log_df():
    return sheets.read_audit_log()


@st.cache_data(ttl=30)
def _cached_up_shipments_df():
    return sheets.read_up_shipments()


def _audit_lookup_ship_cost(ttn_raw, main_df):
    ttn = str(ttn_raw).strip()
    if not ttn or ttn.lower() == "nan":
        return None
    try:
        m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
        if m.empty:
            return None
        v = m.iloc[0]["Вартість"]
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def _audit_lookup_receipt_sum(detail_raw, chk_df):
    """Сума з архіву Checkbox, якщо у «Деталі» є URL чека."""
    if chk_df is None or chk_df.empty:
        return None
    d = str(detail_raw).lower()
    for _, cr in chk_df.iterrows():
        link = str(cr.get("Посилання", "")).lower().strip()
        if link and link in d:
            try:
                return float(cr.get("Сума", 0) or 0)
            except Exception:
                continue
    return None


def _audit_num_from_cell(val):
    if val is None:
        return float("nan")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return float("nan")
    try:
        return float(s.replace(",", ".").strip())
    except (TypeError, ValueError):
        return float("nan")


def _enrich_audit_table(adf, main_df, chk_df):
    """Додає / уточнює «Вартість ТТН» та «Сума чеку»: спочатку збережені в журналі, інакше з таблиці + Checkbox."""
    out = adf.head(500).copy()
    ships, sums = [], []
    for _, r in out.iterrows():
        saved_ship = _audit_num_from_cell(r.get("Вартість ТТН"))
        saved_rcpt = _audit_num_from_cell(r.get("Сума чеку"))
        ttn = str(r.get("ТТН", "")).strip()
        detail = r.get("Деталі", "")

        if not pd.isna(saved_ship):
            ship_f = saved_ship
        else:
            sc = _audit_lookup_ship_cost(ttn, main_df)
            ship_f = float(sc) if sc is not None else float("nan")

        if not pd.isna(saved_rcpt):
            rcpt_f = saved_rcpt
        else:
            rs = _audit_lookup_receipt_sum(detail, chk_df)
            if rs is None and ttn:
                m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
                if not m.empty:
                    curl = str(m.iloc[0].get("Чек", "")).strip()
                    if curl and curl.lower() != "nan":
                        rs = _audit_lookup_receipt_sum(curl, chk_df)
            rcpt_f = float(rs) if rs is not None else float("nan")

        ships.append(ship_f)
        sums.append(rcpt_f)
    out["Вартість ТТН"] = ships
    out["Сума чеку"] = sums
    return out


def _style_audit_amounts(df):
    """Підсвічує дві останні колонки: зелений збіг, червоний розбіжність (обидва числа є)."""

    def _row_style(row):
        blank = ""
        sty = [blank] * len(row)
        if "Вартість ТТН" not in row.index or "Сума чеку" not in row.index:
            return pd.Series(sty, index=row.index)
        ok = "background-color: #c8e6c9; color: #1b5e20; font-weight: 600"
        bad = "background-color: #ffcdd2; color: #b71c1c; font-weight: 600"
        a = row["Вартість ТТН"]
        b = row["Сума чеку"]
        try:
            fa = float(a) if not pd.isna(a) else None
        except (TypeError, ValueError):
            fa = None
        try:
            fb = float(b) if not pd.isna(b) else None
        except (TypeError, ValueError):
            fb = None
        i_a = row.index.get_loc("Вартість ТТН")
        i_b = row.index.get_loc("Сума чеку")
        if fa is not None and fb is not None:
            c = ok if abs(fa - fb) < 0.01 else bad
            sty[i_a] = c
            sty[i_b] = c
        return pd.Series(sty, index=row.index)

    return df.style.apply(_row_style, axis=1)


# ==========================================
# 🔌 АВТО-ПІДКЛЮЧЕННЯ СЕКРЕТІВ
# ==========================================
def _read_st_secret(key: str) -> str:
    return config.get_secret(key)


def _up_mask_token(val: str) -> str:
    s = str(val or "").strip()
    if len(s) <= 10:
        return "✓" if s else "—"
    return f"{s[:6]}…{s[-4:]}"


_UP_CONFIG_KEYS = (
    "UP_TRACKING_TOKEN",
    "UP_BEARER_TOKEN",
    "UP_CLASSIFIER_BEARER",
    "UP_USER_TOKEN",
    "UP_UUID",
    "UP_UUID_SAND",
    "UP_COUNTERPARTY_TOKEN",
    "UP_SENDER_UUID",
    "UP_SENDER_ADDRESS_ID",
    "UP_SENDER_NAME",
    "UP_SENDER_PHONE",
    "UP_SENDER_ADDRESS",
    "UP_SENDER_POSTCODE",
    "UP_SENDER_BRANCH_INDEX",
    "UP_SENDER_TIN",
    "UP_SENDER_BANK_ACCOUNT",
    "UP_SENDER_TYPE",
    "UP_CABINET_URL",
    "API_KEY_NP",
    "CHECKBOX_LICENSE_KEY",
    "CHECKBOX_PASSWORD",
    "MEEST_API_TOKEN",
)


def _up_secrets_diag() -> dict:
    """Статус ключів УП у Secrets (для діагностики на вкладці)."""
    load_secrets_to_config()
    keys = (
        "UP_BEARER_TOKEN",
        "UP_CLASSIFIER_BEARER",
        "UP_USER_TOKEN",
        "UP_COUNTERPARTY_TOKEN",
        "UP_UUID",
        "UP_SENDER_UUID",
        "UP_TRACKING_TOKEN",
    )
    out = {}
    for k in keys:
        v = _read_st_secret(k) or str(getattr(config, k, "") or "").strip()
        out[k] = _up_mask_token(v)
    top = config.list_secret_top_keys()
    out["_sections"] = ", ".join(top[:16]) if top else "?"
    up_nested = config.list_up_keys_in_secrets()
    up_top = [k for k in top if str(k).startswith("UP_")]
    up_all = list(dict.fromkeys(up_top + up_nested))
    out["_up_keys_in_file"] = ", ".join(up_all) if up_all else "(немає ключів UP_* у файлі)"
    out["_has_inline"] = bool(config.get_secret("UP_INLINE_SECRETS"))
    out["_has_ukrposhta_section"] = "ukrposhta" in top
    missing = [k for k in keys if _up_mask_token(_read_st_secret(k)) == "—"]
    out["_missing"] = missing
    if _up_mask_token(_read_st_secret("UP_TRACKING_TOKEN")) != "—":
        src = config.secret_source("UP_TRACKING_TOKEN")
        if src:
            out["_tracking_source"] = src
    return out


def load_secrets_to_config():
    for key, val in config.load_up_inline_secrets().items():
        if val:
            setattr(config, key, val)
    for key in _UP_CONFIG_KEYS:
        val = _read_st_secret(key)
        if val:
            setattr(config, key, val)
    turbosms = _read_st_secret("TURBOSMS_TOKEN")
    if turbosms:
        setattr(config, "TURBOSMS_TOKEN", turbosms)
    turbosms_sender = _read_st_secret("TURBOSMS_SENDER")
    if turbosms_sender:
        setattr(config, "TURBOSMS_SENDER", turbosms_sender)
    elif not str(getattr(config, "TURBOSMS_SENDER", "") or "").strip():
        config.TURBOSMS_SENDER = "Zamovlenya"
    if not _read_st_secret("UP_USER_TOKEN"):
        cp = _read_st_secret("UP_COUNTERPARTY_TOKEN")
        if cp:
            config.UP_USER_TOKEN = cp

load_secrets_to_config()

# ==========================================
# 🔐 АВТОРИЗАЦІЯ
# ==========================================
def check_password():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        st.markdown("""<style>.stTextInput input {text-align: center;} div[data-testid="stForm"] {border: 1px solid #444; padding: 2rem; border-radius: 10px;}</style>""", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.header("🔒 Вхід у систему")
            with st.form("login_form"):
                username = st.text_input("Логін", placeholder="Введіть логін")
                password = st.text_input("Пароль", type="password", placeholder="Введіть пароль")
                submit = st.form_submit_button("Увійти", use_container_width=True, type="primary")

                if submit:
                    if auth.verify_credentials(username, password):
                        st.session_state.logged_in = True
                        st.session_state.auth_user = str(username).strip() or "?"
                        st.toast("Успішний вхід!", icon="✅")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ Невірний логін або пароль")
            try:
                au = dict(st.secrets["auth_users"]) if hasattr(st, "secrets") and "auth_users" in st.secrets else {}
                has_legacy = bool(getattr(config, "USERS", None))
                if not au and not has_legacy:
                    st.info(
                        "Налаштуйте вхід: у Secrets додайте секцію **[auth_users]** (логін = bcrypt-хеш). "
                        "Згенерувати хеш локально: `python auth.py 'ВашПароль'`"
                    )
            except Exception:
                pass
        return False
    return True

if not check_password():
    st.stop()


def audit_log(action, ttn="", detail="", ship_cost=None, receipt_sum=None):
    """Журнал дій (аркуш LogisticAudit у книзі Orders)."""
    u = str(st.session_state.get("auth_user", "")).strip() or "?"
    if sheets.append_audit_log(
        u, action, ttn, detail, ship_cost=ship_cost, receipt_sum=receipt_sum
    ):
        _cached_audit_log_df.clear()


# ==========================================
# Автогенерація повідомлень для черги видачі чека
# ==========================================
def ensure_messages_exist(df):
    for i, row in df.iterrows():
        if utils.row_receipt_not_required(row):
            continue
        msg_val = str(row["Повідомлення"]).strip()
        is_sent = str(row["Статус СМС"]) == "Отправлено"
        current_status = str(row["Статус"]).lower()
        link = str(row["Чек"]).strip()

        if is_sent:
            continue
        if not (link and len(link) > 5 and link.lower() != "nan"):
            continue
        if not utils.status_has_any(current_status, utils.DELIVERED_STATUS_KEYWORDS):
            continue

        short = len(msg_val) <= 5 or msg_val.lower() == "nan"
        msg_missing_current_link = link not in msg_val
        if short or msg_missing_current_link:
            df.at[i, "Повідомлення"] = _CHECK_SMS_TEXT.format(link=link)
            if len(str(row["Телефон"])) > 5:
                df.at[i, "Статус СМС"] = "Не отправлено"
    return df

# ==========================================
# 🌐 API ФУНКЦІЇ
# ==========================================

# --- CHECKBOX ---
_CHECKBOX_ARCHIVE_DAYS = 30
_CHECKBOX_PAGE_SIZE = 100
_CHECKBOX_MAX_PAGES = 100  # до ~10 000 чеків за один запит архіву


def _parse_checkbox_receipt_item(item: dict) -> dict:
    raw_date = item.get("created_at", "")
    try:
        dt = datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=3)
        f_date = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        f_date = utils.normalize_date(raw_date)
    rid = item.get("id")
    return {
        "ID": rid,
        "Дата": f_date,
        "Сума": item.get("total_sum", 0) / 100,
        "Посилання": f"https://check.checkbox.ua/{rid}",
    }


@st.cache_data(ttl=300)
def fetch_checkbox_archive():
    if not config.CHECKBOX_LOGIN or not config.CHECKBOX_LICENSE_KEY:
        return None
    auth_url = "https://api.checkbox.in.ua/api/v1/cashier/signin"
    try:
        r = utils.make_request(
            "POST",
            auth_url,
            json={"login": config.CHECKBOX_LOGIN, "password": config.CHECKBOX_PASSWORD},
        )
        if not r or r.status_code != 200:
            return None
        token = r.json().get("access_token")
        date_from = (datetime.now() - timedelta(days=_CHECKBOX_ARCHIVE_DAYS)).isoformat()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-License-Key": config.CHECKBOX_LICENSE_KEY,
        }
        url = "https://api.checkbox.in.ua/api/v1/receipts"
        all_items = []
        offset = 0
        for _ in range(_CHECKBOX_MAX_PAGES):
            r_rec = utils.make_request(
                "GET",
                url,
                headers=headers,
                params={
                    "desc": "true",
                    "limit": _CHECKBOX_PAGE_SIZE,
                    "offset": offset,
                    "from_date": date_from,
                },
            )
            if not r_rec or r_rec.status_code != 200:
                break
            data = r_rec.json()
            batch = data.get("results") or []
            if not batch:
                break
            all_items.extend(batch)
            meta = data.get("meta") or {}
            total = meta.get("total")
            if total is not None and len(all_items) >= int(total):
                break
            if len(batch) < _CHECKBOX_PAGE_SIZE:
                break
            offset += _CHECKBOX_PAGE_SIZE
        if not all_items:
            return pd.DataFrame(columns=["ID", "Дата", "Сума", "Посилання"])
        parsed = [_parse_checkbox_receipt_item(item) for item in all_items]
        return pd.DataFrame(parsed)
    except Exception:
        return None


def _checkbox_archive_table(df: pd.DataFrame, used_links: set):
    """Таблиця: дата, час, сума, посилання."""
    work = df.copy()
    if "_dt" not in work.columns:
        work["_dt"] = pd.to_datetime(work["Дата"], errors="coerce")
    disp = pd.DataFrame(
        {
            "Дата": work["_dt"].dt.strftime("%d.%m.%Y"),
            "Час": work["_dt"].dt.strftime("%H:%M"),
            "Сума": work["Сума"],
            "Посилання": work["Посилання"],
        }
    )

    def _row_style(row):
        if str(row.get("Посилання", "")).strip() in used_links:
            return ["background-color: #abf7b1; color: black"] * len(row)
        return [""] * len(row)

    st.dataframe(
        disp.style.apply(_row_style, axis=1),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Посилання": st.column_config.LinkColumn(display_text="🧾 Чек"),
            "Сума": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_checkbox_archive_tab():
    """Архів чеків Checkbox — перегляд по днях."""
    h1, h2 = st.columns([1, 3])
    with h1:
        if st.button("🔄 Оновити Архів", key="chk_arch_refresh", use_container_width=True):
            fetch_checkbox_archive.clear()
            st.cache_data.clear()
            st.rerun()
    c_df = fetch_checkbox_archive()
    if c_df is None:
        st.warning("Архів недоступний: перевір **CHECKBOX_LOGIN**, **CHECKBOX_PASSWORD**, **CHECKBOX_LICENSE_KEY** у Secrets.")
        return
    if c_df.empty:
        st.info("Чеків за останні 30 днів не знайдено.")
        return

    used = used_checkbox_links_from_df(st.session_state.df)
    c_df = c_df.copy()
    c_df["_dt"] = pd.to_datetime(c_df["Дата"], errors="coerce")
    c_df["_day"] = c_df["_dt"].dt.date
    days_sorted = sorted({d for d in c_df["_day"].dropna().unique()}, reverse=True)
    today = datetime.now().date()

    attached = sum(1 for lk in c_df["Посилання"].astype(str) if lk.strip() in used)
    st.caption(
        f"Завантажено **{len(c_df)}** чеків за {_CHECKBOX_ARCHIVE_DAYS} дн. · "
        f"прикріплено в таблиці: **{attached}** · зелений = використано"
    )

    selected = st.session_state.get("chk_arch_selected_day")
    if selected is not None and not hasattr(selected, "strftime"):
        try:
            selected = pd.to_datetime(selected).date()
        except Exception:
            selected = None
    if selected not in days_sorted:
        selected = today if today in days_sorted else days_sorted[0]
    st.session_state.chk_arch_selected_day = selected

    st.markdown("**Оберіть день**")
    per_row = 8
    for i in range(0, len(days_sorted), per_row):
        cols = st.columns(per_row)
        for j, col in enumerate(cols):
            if i + j >= len(days_sorted):
                break
            day = days_sorted[i + j]
            cnt = int((c_df["_day"] == day).sum())
            label = f"{day.strftime('%d.%m')} ({cnt})"
            with col:
                if st.button(
                    label,
                    key=f"chk_arch_day_{day}",
                    use_container_width=True,
                    type="primary" if day == selected else "secondary",
                ):
                    st.session_state.chk_arch_selected_day = day
                    st.rerun()

    chunk = c_df[c_df["_day"] == selected].sort_values("_dt", ascending=False)
    st.markdown(f"### {selected.strftime('%d.%m.%Y')} — **{len(chunk)}** чеків")
    _checkbox_archive_table(chunk, used)


def used_checkbox_links_from_df(df):
    used = set()
    for _, r in df.iterrows():
        lk = str(r.get("Чек", "")).strip()
        if lk and len(lk) > 5 and lk.lower() != "nan":
            used.add(lk)
    return used


def tab1_unattached_receipt_picker_rows(df, checkbox_df, amount):
    """Чеки з Checkbox: сума збігається з відправленням, посилання ще не в колонці «Чек»."""
    if checkbox_df is None or checkbox_df.empty:
        return []
    try:
        amt = float(str(amount).replace(",", ".").strip())
    except Exception:
        return []
    if amt <= 0:
        return []
    used = used_checkbox_links_from_df(df)
    try:
        sums = pd.to_numeric(checkbox_df["Сума"], errors="coerce")
    except Exception:
        sums = checkbox_df["Сума"]
    cand = checkbox_df.loc[(sums - amt).abs() < 0.01]
    seen = set()
    raw_rows = []
    for _, r in cand.iterrows():
        link = str(r.get("Посилання", "")).strip()
        if not link or link in used or link in seen:
            continue
        seen.add(link)
        dt_s = str(r.get("Дата", "")).strip()
        dt_obj = pd.to_datetime(dt_s, errors="coerce")
        if pd.isna(dt_obj):
            if len(dt_s) >= 16:
                dt_label = dt_s[:16].strip()
            elif len(dt_s) >= 10:
                dt_label = dt_s[:10]
            else:
                dt_label = dt_s or "—"
        else:
            dt_label = dt_obj.strftime("%Y-%m-%d %H:%M")
        try:
            sm = float(r.get("Сума", 0) or 0)
        except Exception:
            sm = 0.0
        raw_rows.append({"link": link, "dt_label": dt_label, "sm": sm, "sort_ts": dt_obj})

    def _sort_ts(x):
        ts = x["sort_ts"]
        return ts if not pd.isna(ts) else pd.Timestamp(1970, 1, 1)

    raw_rows.sort(key=_sort_ts, reverse=True)

    base_n = {}
    out = []
    for t in raw_rows:
        sum_txt = f"{t['sm']:.2f}".replace(".", ",")
        base = f"{t['dt_label']} — {sum_txt} грн"
        base_n[base] = base_n.get(base, 0) + 1
        n = base_n[base]
        label = base if n == 1 else f"{base} ({n})"
        out.append({"link": t["link"], "label": label})
    return out


# --- НОВА ПОШТА ---
def get_np_statuses_bulk(ttn_list):
    if not ttn_list: return {}
    chunks = [ttn_list[i:i + 100] for i in range(0, len(ttn_list), 100)]
    results = {}
    for chunk in chunks:
        documents = [{"DocumentNumber": ttn} for ttn in chunk]
        try:
            r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
                "apiKey": config.API_KEY_NP, "modelName": "TrackingDocument", 
                "calledMethod": "getStatusDocuments", "methodProperties": {"Documents": documents}
            })
            if r and r.json()['success']:
                for item in r.json()['data']:
                    ttn = item.get('Number')
                    if ttn:
                        results[ttn] = {
                            "Status": item.get('Status', ''),
                            "Cost": float(item.get('AnnouncedPrice') or 0),
                            "Phone": item.get('RecipientPhone', ''),
                            "ClientBarcode": item.get('ClientBarcode', '')
                        }
        except Exception: pass
    return results

def debug_np_api(ttn):
    """Показує все поля з API Novaposhta для одного ТТН"""
    documents = [{"DocumentNumber": ttn}]
    try:
        r = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
            "apiKey": config.API_KEY_NP, 
            "modelName": "TrackingDocument", 
            "calledMethod": "getStatusDocuments", 
            "methodProperties": {"Documents": documents}
        })
        if r and r.json().get('success'):
            data = r.json().get('data', [])
            return data[0] if data else {"error": "Дані не знайдені для цього ТТН"}
        return {"error": r.json().get('errors', 'Помилка API') if r else 'No response'}
    except Exception as e:
        return {"error": str(e)}


def debug_make_request(method, url, **kwargs):
    try:
        r = requests.request(method, url, **kwargs)
        return r, None
    except Exception as e:
        return None, str(e)


def debug_up_api(barcode, uuid=None, uuid_sand=None, bearer_token=None, user_token=None, tracking_token=None, custom_url=None):
    """Показує всі поля з API Укрпошти для одного баркоду"""
    if len(barcode) == 12 and barcode.isdigit():
        barcode = "0" + barcode
    result = {'uuid': uuid, 'uuid_sand': uuid_sand}

    if bearer_token and len(bearer_token) > 10 and user_token:
        url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
        headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        params = {"token": user_token}
        headers["X-COUNTERPARTY-TOKEN"] = user_token
        r, err = debug_make_request("GET", url, headers=headers, params=params)
        result['ecom_url'] = url
        result['ecom_headers'] = headers
        result['ecom_params'] = params
        result['ecom_status_code'] = r.status_code if r else None
        if r:
            try:
                result['ecom_json'] = r.json()
            except Exception:
                result['ecom_text'] = r.text
        else:
            result['ecom_error'] = err

    if tracking_token and len(tracking_token) > 10:
        url = f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}"
        headers = {"Authorization": f"Bearer {tracking_token}", "Accept": "application/json"}
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        r, err = debug_make_request("GET", url, headers=headers)
        result['tracking_url'] = url
        result['tracking_headers'] = headers
        result['tracking_status_code'] = r.status_code if r else None
        if r:
            try:
                result['tracking_json'] = r.json()
            except Exception:
                result['tracking_text'] = r.text
        else:
            result['tracking_error'] = err

    if custom_url:
        url = custom_url.strip()
        headers = {}
        params = {}
        if bearer_token and len(bearer_token) > 10:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if user_token:
            params["token"] = user_token
            headers["X-COUNTERPARTY-TOKEN"] = user_token
        if tracking_token and not headers:
            headers["Authorization"] = f"Bearer {tracking_token}"
        if uuid:
            headers["X-UUID"] = uuid
        if uuid_sand:
            headers["X-UUID-SAND"] = uuid_sand
        r, err = debug_make_request("GET", url, headers=headers or None, params=params or None)
        result['custom_url'] = url
        result['custom_headers'] = headers
        result['custom_params'] = params
        result['custom_status_code'] = r.status_code if r else None
        if r:
            try:
                result['custom_json'] = r.json()
            except Exception:
                result['custom_text'] = r.text
        else:
            result['custom_error'] = err

    if len(result) == 2 and not result.get('ecom_json') and not result.get('tracking_json') and not result.get('custom_json'):
        result['error'] = 'Не передано жодного токена або URL для перевірки'
    return result

def fetch_new_orders_np(existing_ttns):
    date_from = (datetime.now() - timedelta(days=60)).strftime("%d.%m.%Y")
    date_to = datetime.now().strftime("%d.%m.%Y")
    new_rows = []

    r_out = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getDocumentList",
        "methodProperties": {"DateFrom": date_from, "DateTo": date_to, "GetFullList": "1", "Limit": "500"}
    })
    r_in = utils.make_request("POST", "https://api.novaposhta.ua/v2.0/json/", json={
        "apiKey": config.API_KEY_NP, "modelName": "InternetDocument", "calledMethod": "getIncomingDocuments",
        "methodProperties": {"DateFrom": date_from, "DateTo": date_to, "Limit": "500"}
    })

    out_list = r_out.json().get('data', []) if r_out and r_out.json()['success'] else []
    in_list = r_in.json().get('data', []) if r_in and r_in.json()['success'] else []
    
    st.toast(f"📡 Знайдено в API: Вихідних {len(out_list)}, Вхідних {len(in_list)}", icon="🕵️")
    all_docs = out_list + in_list

    for doc in all_docs:
        ttn = utils.clean_ttn(str(doc.get('IntDocNumber') or doc.get('DocumentNumber'))) 
        client_barcode = doc.get('ClientBarcode', '')
        status = str(doc.get('StateName', ''))
        
        if ttn and ttn not in existing_ttns and not utils.status_has_any(status, utils.DELIVERED_STATUS_KEYWORDS + utils.DECLINED_STATUS_KEYWORDS):
            cost = float(doc.get('Cost') or doc.get('DeclaredCost') or 0)
            date = utils.normalize_date(doc.get('CreateTime') or doc.get('DateTime', ''))
            phone = utils.clean_phone(doc.get('RecipientContactPhone') or doc.get('SenderContactPhone', ''))

            new_rows.append({
                "ТТН": ttn, "Служба": "НП", "Статус": status, "Дата": date,
                "Телефон": phone, "Вартість": cost, "Номер накладної": utils.normalize_invoice_number(client_barcode), "Чек": "", 
                "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
            })
            existing_ttns.append(ttn)
    return new_rows

# --- УКРПОШТА ---
def extract_phone_from_data(data):
    if isinstance(data, dict):
        phone_keys = {"phone", "phoneNumber", "phone_number", "recipientPhone", "senderPhone", "contactPhone", "phoneMobile", "mobile"}
        for key, value in data.items():
            if isinstance(key, str) and key in phone_keys and value:
                return utils.clean_phone(str(value))
            if isinstance(value, dict):
                p = extract_phone_from_data(value)
                if p:
                    return p
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        p = extract_phone_from_data(item)
                        if p:
                            return p
                    elif isinstance(item, str):
                        digits = re.sub(r"\D", "", item)
                        if len(digits) >= 9:
                            return utils.clean_phone(item)
    return ""

def format_up_extra_info(data, barcode=None):
    if not isinstance(data, dict):
        return ""
    info = []
    recipient = data.get('recipient') or {}
    sender = data.get('sender') or {}
    if isinstance(recipient, dict):
        name = " ".join(filter(None, [recipient.get('fullName'), recipient.get('firstName'), recipient.get('lastName')]))
        if name:
            info.append(f"Отримувач: {name}")
        phone = extract_phone_from_data(recipient)
        if phone:
            info.append(f"Телефон отримувача: {phone}")
    if isinstance(sender, dict):
        name = " ".join(filter(None, [sender.get('fullName'), sender.get('firstName'), sender.get('lastName')]))
        if name:
            info.append(f"Відправник: {name}")
        phone = extract_phone_from_data(sender)
        if phone:
            info.append(f"Телефон відправника: {phone}")
    for key, label in [
        ('originLocationName', 'Звідки'),
        ('destinationLocationName', 'Куди'),
        ('shipmentNumber', 'Номер відправлення'),
        ('registrationDate', 'Зареєстровано'),
        ('lastModified', 'Останнє оновлення'),
        ('deliveryDate', 'Дата доставки'),
        ('status', 'Статус'),
        ('barcode', 'Barcode'),
        ('barCode', 'Barcode')
    ]:
        value = data.get(key)
        if not value:
            continue
        if key == 'shipmentNumber' and barcode and str(value) == str(barcode):
            continue
        info.append(f"{label}: {value}")
    if not info:
        return ""
    return " | ".join(info)

def build_up_headers(bearer_token=None, uuid=None, uuid_sand=None, counterparty_token=None, include_content_type=True):
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    if uuid:
        headers["X-UUID"] = uuid
    if uuid_sand:
        headers["X-UUID-SAND"] = uuid_sand
    if counterparty_token:
        headers["X-COUNTERPARTY-TOKEN"] = counterparty_token
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def get_up_status_smart(barcode):
    if len(barcode) == 12 and barcode.isdigit():
        barcode = "0" + barcode
    phone = ""
    extra = ""
    if config.UP_USER_TOKEN:
        try:
            url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/barcode/{barcode}"
            headers = build_up_headers(
                bearer_token=config.UP_BEARER_TOKEN,
                uuid=config.UP_UUID,
                uuid_sand=config.UP_UUID_SAND,
                counterparty_token=config.UP_COUNTERPARTY_TOKEN
            )
            params = {"token": config.UP_USER_TOKEN}
            r = utils.make_request("GET", url, headers=headers, params=params)
            if r and r.status_code == 200:
                data = r.json() or {}
                status_raw = data.get('lifecycle', {}).get('status')
                last_event = data.get('lifecycle', {}).get('eventName')
                final_status = last_event if last_event else (status_raw if status_raw else "В дорозі")
                date_raw = data.get('lifecycle', {}).get('date') or data.get('lastModified')
                phone = extract_phone_from_data(data)
                extra = format_up_extra_info(data, barcode)
                return final_status, utils.normalize_date(date_raw), 0.0, phone, extra
        except Exception:
            pass
    try:
        r = utils.make_request("GET", f"https://www.ukrposhta.ua/status-tracking/0.0.1/statuses?barcode={barcode}", 
                         headers={"Authorization": f"Bearer {config.UP_TRACKING_TOKEN}", "Accept": "application/json"})
        if r and r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                last = data[-1]
                phone = extract_phone_from_data(data)
                extra = format_up_extra_info(data, barcode)
                return last.get('eventName', 'В дорозі'), utils.normalize_date(last.get('date', '')), 0.0, phone, extra
    except Exception:
        pass
    return "Не знайдено", None, 0.0, phone, extra

def fetch_new_orders_up(existing_ttns):
    if not config.UP_USER_TOKEN: return []
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    d_from = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {"token": config.UP_USER_TOKEN, "lastModifiedFrom": d_from}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID,
        uuid_sand=config.UP_UUID_SAND,
        counterparty_token=config.UP_COUNTERPARTY_TOKEN
    )
    try:
        r = utils.make_request("GET", url, headers=headers, params=params)
        if not r or r.status_code != 200: return []
        new_rows = []
        data = r.json()
        shipments = data if isinstance(data, list) else data.get('shipments', [])
        for s in shipments:
            ttn = s.get('barcode')
            if ttn and ttn not in existing_ttns:
                date = utils.normalize_date(s.get('registrationDate', '') or s.get('lastModified', ''))
                cost = float(s.get('declaredPrice', 0))
                phone = ""
                if s.get('recipient'): phone = utils.clean_phone(s.get('recipient', {}).get('phoneNumber', ''))
                new_rows.append({
                    "ТТН": ttn, "Служба": "УП", "Статус": "Нове", "Дата": date,
                    "Телефон": phone, "Вартість": cost, "Номер накладної": "", "Чек": "", "Повідомлення": "", "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                })
        return new_rows
    except Exception:
        return []


def up_post_shipment_create(body: dict):
    """Створює відправлення Укрпошти (eCom POST /shipments). Повертає (response_dict|None, error_or_status)."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN у Secrets."
    if not str(getattr(config, "UP_UUID", "") or "").strip():
        return None, "Немає UP_UUID у Secrets."
    url = "https://www.ukrposhta.ua/ecom/0.0.1/shipments"
    params = {"token": ecom_token}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token,
        include_content_type=True,
    )
    try:
        r = utils.make_request("POST", url, headers=headers, params=params, json=body, timeout=60)
        if not r:
            hint = utils.get_last_request_error()
            msg = "Немає відповіді від сервера Укрпошти (eCom)."
            if hint:
                msg += f" ({hint})"
            return None, msg
        if r.status_code == 200 or r.status_code == 201:
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        try:
            err_js = r.json()
        except Exception:
            err_js = {"text": r.text[:800]}
        return None, _up_format_ecom_error(f"HTTP {r.status_code}: {err_js}")
    except Exception as e:
        return None, str(e)[:500]


def _up_normalize_bc(barcode_or_uuid: str) -> str:
    bc = str(barcode_or_uuid or "").strip()
    if len(bc) == 12 and bc.isdigit():
        bc = "0" + bc
    return bc


def _up_barcode_from_create_response(data):
    if not isinstance(data, dict):
        return None
    for key in ("barcode", "barCode", "shipmentNumber"):
        v = data.get(key)
        if v and str(v).strip():
            return _up_normalize_bc(str(v).strip())
    parcels = data.get("parcels")
    if isinstance(parcels, list):
        for p in parcels:
            if isinstance(p, dict) and p.get("barcode"):
                return _up_normalize_bc(str(p["barcode"]))
    return None


_UP_EDIT_KEEP_KEYS = frozenset(
    {
        "up_edit_seeded_uuid",
        "up_edit_shipment_uuid",
        "up_edit_parcel_uuid",
        "up_edit_barcode",
        "up_edit_delivery_type",
        "up_edit_lifecycle_status",
        "up_edit_recipient_uuid",
        "up_edit_panel_open",
    }
)


def _up_clear_edit_widgets():
    """Скинути віджети форми редагування (інакше Streamlit лишає старі значення)."""
    for key in list(st.session_state.keys()):
        if key.startswith("up_edit_") and key not in _UP_EDIT_KEEP_KEYS:
            del st.session_state[key]


def _up_recipient_address_from_shipment(data: dict) -> dict:
    """Адреса отримувача з відповіді GET /shipments."""
    out = {
        "postcode": "",
        "region": "",
        "district": "",
        "city": "",
        "street": "",
        "house": "",
        "apartment": "",
    }
    if not isinstance(data, dict):
        return out
    rec = data.get("recipient")
    addr = None
    if isinstance(rec, dict):
        addrs = rec.get("addresses")
        if isinstance(addrs, list) and addrs:
            first = addrs[0]
            if isinstance(first, dict):
                addr = first.get("address") if isinstance(first.get("address"), dict) else first
        elif isinstance(rec.get("address"), dict):
            addr = rec.get("address")
    if not isinstance(addr, dict):
        ra = data.get("recipientAddress")
        if isinstance(ra, dict):
            addr = ra
    if isinstance(addr, dict):
        out["postcode"] = str(addr.get("postcode") or "")
        out["region"] = str(addr.get("region") or "")
        out["district"] = str(addr.get("district") or "")
        out["city"] = str(addr.get("city") or "")
        out["street"] = str(addr.get("street") or "")
        out["house"] = str(addr.get("houseNumber") or "")
        out["apartment"] = str(addr.get("apartmentNumber") or "")
    return out


def _up_shipment_uuid_from_response(data: dict):
    if not isinstance(data, dict):
        return ""
    return str(data.get("uuid") or data.get("shipmentUuid") or "").strip()


def _up_lifecycle_status(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    lc = data.get("lifecycle")
    if isinstance(lc, dict):
        return str(lc.get("status") or "").strip()
    return ""


def _up_parcels_list_from_response(data: dict) -> list:
    if not isinstance(data, dict):
        return []
    parcels = data.get("parcels")
    if isinstance(parcels, list):
        return [p for p in parcels if isinstance(p, dict)]
    return []


def _up_first_parcel_from_response(data: dict) -> dict:
    parcels = _up_parcels_list_from_response(data)
    return parcels[0] if parcels else {}


def up_fetch_shipment(barcode_or_uuid: str):
    """GET відправлення за ШКІ або uuid."""
    ident = str(barcode_or_uuid or "").strip()
    if not ident:
        return None, "Вкажи ШКІ або uuid відправлення."
    if _up_is_valid_uuid(ident):
        path = f"/shipments/{ident}"
    else:
        bc = ident
        if len(bc) == 12 and bc.isdigit():
            bc = "0" + bc
        path = f"/shipments/barcode/{bc}"
    return up_ecom_request("GET", path)


def up_put_shipment_update(shipment_uuid: str, body: dict):
    """PUT /shipments/{uuid} — зміна відправлення (опис, доставка, parcels)."""
    suuid = str(shipment_uuid or "").strip()
    if not suuid:
        return None, "Немає uuid відправлення для оновлення."
    path = f"/shipments/{suuid}"
    return up_ecom_request("PUT", path, body)


def _up_client_type_label(client_type: str) -> str:
    labels = {
        "INDIVIDUAL": "фізична особа",
        "PRIVATE_ENTREPRENEUR": "ФОП",
        "COMPANY": "юридична особа",
    }
    return labels.get(str(client_type or "").strip(), str(client_type or "—"))


def _up_expect_fop_sender() -> bool:
    """Чи очікується відправник типу ФОП (PRIVATE_ENTREPRENEUR)."""
    t = str(getattr(config, "UP_SENDER_TYPE", "") or "").strip().upper()
    if t in ("INDIVIDUAL", "FO", "ФО", "PHYSICAL"):
        return False
    if t in ("FOP", "PRIVATE_ENTREPRENEUR", "ПЕ", "ФОП", "PE"):
        return True
    tin = re.sub(r"\D", "", str(getattr(config, "UP_SENDER_TIN", "") or ""))
    if len(tin) == 10:
        return True
    name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip()
    return bool(re.match(r"(?i)^фоп[\s.]", name))


def up_delete_shipment(shipment_uuid: str):
    """DELETE /shipments/{uuid} — лише поки відправлення не прийняте (статус CREATED)."""
    suuid = str(shipment_uuid or "").strip()
    if not suuid:
        return False, "Немає uuid відправлення."
    _, err = up_ecom_request("DELETE", f"/shipments/{suuid}")
    if err:
        return False, err
    return True, ""


def up_delete_shipment_by_barcode(barcode: str):
    """Видалити відправлення в eCom за ШКІ."""
    data, err = up_fetch_shipment(barcode)
    if err:
        return False, err
    if not isinstance(data, dict):
        return False, "Не вдалося завантажити відправлення."
    suuid = _up_shipment_uuid_from_response(data)
    if not suuid:
        return False, "У відповіді API немає uuid відправлення."
    status = _up_lifecycle_status(data)
    if status and status not in ("CREATED",):
        return (
            False,
            f"Укрпошта дозволяє видалити лише в статусі **CREATED** (зараз: {status}). "
            "Скасуй у кабінеті ok.ukrposhta, якщо вже передано на пошту.",
        )
    return up_delete_shipment(suuid)


def _up_seed_edit_form_from_shipment(data: dict, force: bool = False):
    """Заповнити поля форми редагування з відповіді API."""
    suuid = _up_shipment_uuid_from_response(data)
    if not suuid:
        return
    if not force and st.session_state.get("up_edit_seeded_uuid") == suuid:
        return
    _up_clear_edit_widgets()
    parcel = _up_first_parcel_from_response(data)
    bc = _up_barcode_from_create_response(data) or ""
    api_delivery = str(data.get("deliveryType") or "W2D").strip()
    inv = {v: k for k, v in _UP_DELIVERY_LABELS.items()}
    rec = data.get("recipient") if isinstance(data.get("recipient"), dict) else {}
    addr = _up_recipient_address_from_shipment(data)

    st.session_state.up_edit_shipment_uuid = suuid
    st.session_state.up_edit_parcel_uuid = str(parcel.get("uuid") or "").strip()
    st.session_state.up_edit_barcode = bc
    st.session_state.up_edit_load_barcode = bc
    st.session_state.up_edit_delivery_type = api_delivery
    st.session_state.up_edit_delivery_label_pick = inv.get(api_delivery, "склад – двері")
    st.session_state.up_edit_description = str(data.get("description") or "")
    st.session_state.up_edit_weight_g = int(parcel.get("weight") or data.get("weight") or 500)
    st.session_state.up_edit_length_cm = int(parcel.get("length") or data.get("length") or 30)
    st.session_state.up_edit_width_cm = int(parcel.get("width") or data.get("width") or 0)
    st.session_state.up_edit_height_cm = int(parcel.get("height") or data.get("height") or 0)
    st.session_state.up_edit_declared_uah = float(
        parcel.get("declaredPrice") or data.get("declaredPrice") or 0
    )
    st.session_state.up_edit_postpay_uah = float(data.get("postPay") or 0)
    st.session_state.up_edit_lifecycle_status = _up_lifecycle_status(data)
    st.session_state.up_edit_recipient_uuid = str(rec.get("uuid") or "").strip()
    _up_fill_edit_recipient_name_fields(rec)
    phone = utils.clean_phone(
        str(data.get("recipientPhone") or rec.get("phoneNumber") or "")
    )
    st.session_state.up_edit_phone = phone if phone else "+38"
    for k, v in addr.items():
        st.session_state[f"up_edit_{k}"] = v
    st.session_state.up_edit_paid_shipment_recipient = bool(data.get("paidByRecipient"))
    st.session_state.up_edit_paid_postpay_recipient = bool(
        data.get("postPayPaidByRecipient", True)
    )
    st.session_state.up_edit_transfer_postpay_iban = bool(
        data.get("transferPostPayToBankAccount")
    )
    st.session_state.up_edit_sms = bool(data.get("sms"))
    st.session_state.up_edit_check_delivery = bool(data.get("checkOnDelivery", True))
    fail = str(data.get("onFailReceiveType") or "RETURN").upper()
    st.session_state.up_edit_fail_main = (
        "не повертати" if fail == "PROCESS_AS_REFUSAL" else "повернути"
    )
    st.session_state.up_edit_seeded_uuid = suuid
    st.session_state.up_edit_panel_open = True
    _up_sync_edit_saved_address_snapshot()


def _up_fill_edit_recipient_name_fields(rec: dict):
    """ПІБ отримувача в поля редагування (з API або з поля name)."""
    last = str(rec.get("lastName") or "").strip()
    first = str(rec.get("firstName") or "").strip()
    middle = str(rec.get("middleName") or "").strip()
    if not last and not first:
        name = str(rec.get("name") or "").strip()
        if name:
            parts = name.split()
            if len(parts) >= 1:
                last = parts[0]
            if len(parts) >= 2:
                first = parts[1]
            if len(parts) >= 3:
                middle = " ".join(parts[2:])
    st.session_state.up_edit_lastname = last
    st.session_state.up_edit_firstname = first
    st.session_state.up_edit_middlename = middle


def _up_validate_edit_form() -> str:
    """Перевірка форми редагування перед збереженням."""
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
    if postpay >= 1:
        if not str(st.session_state.get("up_edit_lastname", "")).strip():
            return "Для післяплати потрібне прізвище отримувача."
        if not str(st.session_state.get("up_edit_firstname", "")).strip():
            return "Для післяплати потрібне імʼя отримувача."
        if not str(st.session_state.get("up_edit_middlename", "")).strip():
            return "Для післяплати потрібне по батькові отримувача (вимога Укрпошти)."
    return ""


def _up_post_address_from_edit_form():
    """POST /addresses для нової адреси отримувача при редагуванні."""
    postcode = str(st.session_state.get("up_edit_postcode", "")).strip()
    region = str(st.session_state.get("up_edit_region", "")).strip()
    district = str(st.session_state.get("up_edit_district", "")).strip()
    city = str(st.session_state.get("up_edit_city", "")).strip()
    street = str(st.session_state.get("up_edit_street", "")).strip()
    house = str(st.session_state.get("up_edit_house", "")).strip()
    apartment = str(st.session_state.get("up_edit_apartment", "")).strip()
    if not postcode or not region or not city:
        return None, "Заповни індекс, область і населений пункт."
    body = {
        "country": "UA",
        "postcode": postcode[:5],
        "region": region[:45],
        "city": city[:45],
    }
    if district:
        body["district"] = district[:45]
    if street:
        body["street"] = street[:255]
    if house:
        body["houseNumber"] = house[:15]
    if apartment:
        body["apartmentNumber"] = apartment[:15]
    data, err = up_ecom_request("POST", "/addresses", body, token_required=False)
    if err:
        return None, f"Адреса: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу не створено: {data}"
    return addr_id, ""


def _up_edit_address_changed() -> bool:
    fields = ("postcode", "region", "district", "city", "street", "house", "apartment")
    for f in fields:
        if str(st.session_state.get(f"up_edit_{f}", "")).strip() != str(
            st.session_state.get(f"up_edit_saved_{f}", "")
        ).strip():
            return True
    return False


def _up_sync_edit_saved_address_snapshot():
    for f in ("postcode", "region", "district", "city", "street", "house", "apartment"):
        st.session_state[f"up_edit_saved_{f}"] = str(st.session_state.get(f"up_edit_{f}", ""))


def _up_apply_recipient_updates() -> tuple[dict | None, str]:
    """Оновити клієнта-отримувача (адреса, ПІБ, телефон) перед PUT відправлення."""
    v_err = _up_validate_edit_form()
    if v_err:
        return None, v_err
    rid = str(st.session_state.get("up_edit_recipient_uuid", "")).strip()
    if not rid:
        postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
        if postpay >= 1:
            return None, "Немає uuid отримувача — спочатку натисни «Завантажити» за ШКІ."
        return {}, ""
    body_client = {}
    last = str(st.session_state.get("up_edit_lastname", "")).strip()
    first = str(st.session_state.get("up_edit_firstname", "")).strip()
    middle = str(st.session_state.get("up_edit_middlename", "")).strip()
    phone = utils.clean_phone(str(st.session_state.get("up_edit_phone", "")).strip())
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
    if postpay >= 1:
        body_client["lastName"] = last[:250]
        body_client["firstName"] = first[:250]
        body_client["middleName"] = middle[:250]
    else:
        if last:
            body_client["lastName"] = last[:250]
        if first:
            body_client["firstName"] = first[:250]
        if middle:
            body_client["middleName"] = middle[:250]
    if phone and len(phone) >= 10:
        body_client["phoneNumber"] = phone if phone.startswith("+") else f"+{phone}"

    new_addr_id = None
    if _up_edit_address_changed():
        new_addr_id, err = _up_post_address_from_edit_form()
        if err:
            return None, err
        body_client["addressId"] = str(new_addr_id)

    if body_client:
        _, err = up_ecom_request("PUT", f"/clients/{rid}", body_client)
        if err:
            return None, f"Отримувач: {err}"

    extra = {}
    if new_addr_id:
        try:
            extra["recipientAddressId"] = int(new_addr_id)
        except ValueError:
            extra["recipientAddressId"] = new_addr_id
    return extra, ""


def _up_build_shipment_update_body(extra: dict | None = None) -> dict:
    """Тіло PUT /shipments за полями форми редагування."""
    label = st.session_state.get("up_edit_delivery_label_pick", "склад – двері")
    delivery = _UP_DELIVERY_LABELS.get(label, st.session_state.get("up_edit_delivery_type", "W2D"))
    parcel = {
        "weight": max(1, _up_num_int(st.session_state.get("up_edit_weight_g", 500))),
        "length": max(1, _up_num_int(st.session_state.get("up_edit_length_cm", 30))),
    }
    puid = str(st.session_state.get("up_edit_parcel_uuid", "")).strip()
    if puid:
        parcel["uuid"] = puid
    pw = _up_num_int(st.session_state.get("up_edit_width_cm", 0))
    ph = _up_num_int(st.session_state.get("up_edit_height_cm", 0))
    if pw > 0:
        parcel["width"] = pw
    if ph > 0:
        parcel["height"] = ph
    declared = _up_num_float(st.session_state.get("up_edit_declared_uah", 0))
    if declared > 0:
        parcel["declaredPrice"] = declared

    fail_main = st.session_state.get("up_edit_fail_main", "повернути")
    on_fail = "PROCESS_AS_REFUSAL" if fail_main == "не повертати" else "RETURN"
    postpay = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))

    body = {
        "deliveryType": delivery,
        "description": str(st.session_state.get("up_edit_description", "")).strip()[:255],
        "parcels": [parcel],
        "postPay": postpay,
        "paidByRecipient": bool(st.session_state.get("up_edit_paid_shipment_recipient")),
        "postPayPaidByRecipient": bool(
            st.session_state.get("up_edit_paid_postpay_recipient", True)
        ),
        "transferPostPayToBankAccount": bool(
            st.session_state.get("up_edit_transfer_postpay_iban")
        ),
        "sms": bool(st.session_state.get("up_edit_sms")),
        "checkOnDelivery": bool(st.session_state.get("up_edit_check_delivery", True)),
        "onFailReceiveType": on_fail,
    }
    phone = utils.clean_phone(str(st.session_state.get("up_edit_phone", "")).strip())
    if phone and len(phone) >= 10:
        body["recipientPhone"] = phone if phone.startswith("+") else f"+{phone}"
    if extra:
        body.update(extra)
    return body


def _up_save_shipment_edit(suuid: str):
    extra, err = _up_apply_recipient_updates()
    if err:
        return None, err
    body = _up_build_shipment_update_body(extra)
    return up_put_shipment_update(suuid, body)


def _up_journal_row_from_response(resp: dict, user: str = "") -> dict:
    import json as _json

    bc = _up_barcode_from_create_response(resp) or ""
    suuid = _up_shipment_uuid_from_response(resp)
    st_up = _up_lifecycle_status(resp)
    recipient = ""
    phone = ""
    rec = resp.get("recipient")
    if isinstance(rec, dict):
        recipient = str(rec.get("name") or "").strip()
        if not recipient:
            parts = [rec.get("lastName"), rec.get("firstName"), rec.get("middleName")]
            recipient = " ".join(str(p).strip() for p in parts if p)
        phone = utils.clean_phone(str(rec.get("phoneNumber") or ""))
    ship_type = str(resp.get("type") or "STANDARD").upper()
    tariff = "Пріоритетний" if ship_type == "EXPRESS" else "Базовий"
    ts = (
        str(resp.get("registrationDate") or resp.get("created") or "")
        or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    if "T" in ts:
        ts = ts.replace("T", " ")[:19]
    price = resp.get("deliveryPrice")
    price_s = "" if price is None else str(price)
    try:
        snap = _json.dumps(resp, ensure_ascii=False)[:45000]
    except Exception:
        snap = ""
    u = user or str(st.session_state.get("auth_user", "") or "?")
    return {
        "Час": ts[:19],
        "Користувач": u[:80],
        "ШКІ": bc,
        "UUID": suuid,
        "Статус УП": st_up,
        "Отримувач": recipient[:120],
        "Телефон": phone,
        "Тариф": tariff,
        "Доставка": str(resp.get("deliveryType") or ""),
        "Вартість доставки": price_s,
        "JSON": snap,
    }


def up_journal_save_response(resp: dict, user: str = ""):
    if not isinstance(resp, dict):
        return False
    row = _up_journal_row_from_response(resp, user)
    if not row.get("ШКІ"):
        return False
    ok = sheets.append_up_shipment_record(row)
    if ok:
        _cached_up_shipments_df.clear()
    return ok


def up_fetch_shipments_list(days: int = 14):
    """Список відправлень з eCom API за останні N днів."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return [], "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets."
    if not config.UP_BEARER_TOKEN:
        return [], "Немає UP_BEARER_TOKEN у Secrets."
    d_from = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%dT%H:%M:%S")
    url = f"{UP_ECOM_BASE}/shipments"
    params = {"token": ecom_token, "lastModifiedFrom": d_from}
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token,
    )
    try:
        r = utils.make_request("GET", url, headers=headers, params=params, timeout=60)
        if not r:
            hint = utils.get_last_request_error()
            return [], hint or "Немає відповіді від eCom API."
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}: {(r.text or '')[:300]}"
        data = r.json()
    except Exception as e:
        return [], str(e)[:400]
    if isinstance(data, list):
        return data, ""
    if isinstance(data, dict):
        return data.get("shipments") or data.get("items") or [], ""
    return [], ""


def up_sync_journal_from_api(days: int = 14) -> tuple[int, str]:
    items, err = up_fetch_shipments_list(days)
    if err:
        return 0, err
    user = str(st.session_state.get("auth_user", "") or "?")
    n = 0
    for item in items:
        if isinstance(item, dict) and up_journal_save_response(item, user):
            n += 1
    return n, ""


def _up_normalize_sticker_ident(barcode_or_uuid: str) -> str:
    ident = str(barcode_or_uuid or "").strip()
    if len(ident) == 12 and ident.isdigit():
        ident = "0" + ident
    return ident


def _up_sticker_query_string(hide_delivery_price: bool = False, size: str = "SIZE_10X10") -> str:
    import urllib.parse

    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    params = {"token": ecom_token}
    if size:
        params["size"] = size
    if hide_delivery_price:
        params["hideDeliveryPrice"] = "1"
    return urllib.parse.urlencode(params)


def _up_sticker_get_urls(ident: str, hide_delivery_price: bool = False, size: str = "SIZE_10X10"):
    """URL ярлика: forms API (документація УП) і запасний eCom."""
    qs = _up_sticker_query_string(hide_delivery_price, size)
    form_base = "https://www.ukrposhta.ua/forms/ecom/0.0.1"
    ecom_base = "https://www.ukrposhta.ua/ecom/0.0.1"
    paths = [
        f"{form_base}/shipments/{ident}/sticker?{qs}",
        f"{ecom_base}/shipments/{ident}/sticker?{qs}",
    ]
    if size:
        qs_plain = _up_sticker_query_string(hide_delivery_price, size="")
        paths.append(f"{form_base}/shipments/{ident}/sticker?{qs_plain}")
        paths.append(f"{ecom_base}/shipments/{ident}/sticker?{qs_plain}")
    return paths


def up_sticker_pdf_url(barcode: str, hide_delivery_price: bool = False) -> str:
    ident = _up_normalize_sticker_ident(barcode)
    return _up_sticker_get_urls(ident, hide_delivery_price)[0]


def up_fetch_sticker_pdf_bytes(barcode: str, hide_delivery_price: bool = False):
    import urllib.error
    import urllib.parse
    import urllib.request

    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN."
    ident = _up_normalize_sticker_ident(barcode)
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        counterparty_token=ecom_token,
        include_content_type=False,
    )
    last_err = ""
    for url in _up_sticker_get_urls(ident, hide_delivery_price):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if resp.status == 200 and raw.startswith(b"%PDF"):
                    return raw, ""
                last_err = f"HTTP {resp.status}: не PDF"
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                body = ""
            last_err = f"HTTP {e.code}: {body}"
        except Exception as e:
            last_err = str(e)[:300]

    # POST /shipments/stickers-by-barcodes (документація УП)
    qs = _up_sticker_query_string(hide_delivery_price, size="SIZE_10X10")
    post_url = f"https://www.ukrposhta.ua/ecom/0.0.1/shipments/stickers-by-barcodes?{qs}"
    extra = {}
    if hide_delivery_price:
        extra["hideDeliveryPrice"] = "1"
    body = {ident: extra}
    post_headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        counterparty_token=ecom_token,
        include_content_type=True,
    )
    try:
        r = utils.make_request("POST", post_url, headers=post_headers, json=body, timeout=60)
        if r and r.status_code == 200 and r.content.startswith(b"%PDF"):
            return r.content, ""
        if r:
            last_err = f"POST HTTP {r.status_code}: {(r.text or '')[:200]}"
    except Exception as e:
        last_err = str(e)[:300]

    return None, last_err or "Не вдалося отримати PDF ярлик."


def _render_up_shipments_journal():
    """Журнал створених ТТН (Google Sheet), згрупований по днях."""
    import json as _json

    st.markdown("### Журнал ТТН Укрпошти")
    j1, j2, j3 = st.columns([2, 1, 1])
    with j1:
        days = st.number_input(
            "Синхронізувати з API, днів",
            min_value=1,
            max_value=60,
            value=14,
            key="up_journal_sync_days",
        )
    with j2:
        st.write("")
        if st.button("Оновити з УП", key="up_journal_sync_btn", use_container_width=True):
            n, err = up_sync_journal_from_api(int(days))
            if err:
                st.error(err)
            else:
                st.success(f"З журналу УП: {n} записів")
                st.rerun()
    with j3:
        st.write("")
        if st.button("Оновити список", key="up_journal_refresh_btn", use_container_width=True):
            _cached_up_shipments_df.clear()
            st.rerun()

    df = _cached_up_shipments_df()
    if df is None or df.empty:
        st.info(
            "Поки немає збережених ТТН. Після **Створити** вони з’являться тут. "
            "Або натисни **Оновити з УП**, щоб підтягнути з кабінету."
        )
        return

    df = df.copy()
    df["_dt"] = pd.to_datetime(df["Час"], errors="coerce")
    df["_day"] = df["_dt"].dt.date

    labels = []
    label_to_bc = {}
    for _, row in df.iterrows():
        bc = str(row.get("ШКІ", "")).strip()
        if not bc:
            continue
        lbl = (
            f"{str(row.get('Час', ''))[:16]} · {bc} · "
            f"{str(row.get('Отримувач', '') or '—')[:40]} · {str(row.get('Статус УП', '') or '—')}"
        )
        labels.append(lbl)
        label_to_bc[lbl] = bc

    if not labels:
        return

    prev = st.session_state.get("up_journal_pick_label", labels[0])
    if prev not in labels:
        prev = labels[0]
    pick = st.selectbox("Обрати відправлення", labels, index=labels.index(prev), key="up_journal_pick_label")
    bc_sel = label_to_bc.get(pick, "")

    by_day = df.groupby("_day", sort=False)
    for day in sorted(by_day.groups.keys(), reverse=True):
        chunk = by_day.get_group(day)
        with st.expander(f"📅 {day} — {len(chunk)} шт.", expanded=(str(day) == str(datetime.now().date()))):
            show = chunk[["Час", "ШКІ", "Отримувач", "Телефон", "Статус УП", "Тариф", "Вартість доставки"]].copy()
            st.dataframe(show, use_container_width=True, hide_index=True)

    if not bc_sel:
        return

    st.markdown(f"**Обрано ШКІ:** `{bc_sel}`")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        if st.button("Відкрити для редагування", key="up_journal_open_edit", type="primary"):
            data, err = up_fetch_shipment(bc_sel)
            if err:
                st.error(err)
            else:
                st.session_state.up_last_create_response = data
                st.session_state.up_journal_edit_bc = _up_normalize_bc(bc_sel)
                st.session_state.up_journal_active_bc = bc_sel
                st.session_state.up_edit_seeded_uuid = ""
                st.session_state.up_edit_panel_open = True
                _up_clear_edit_widgets()
                st.rerun()
    with a2:
        if st.button("Завантажити PDF", key=f"up_journal_fetch_pdf_{bc_sel}", use_container_width=True):
            pdf, perr = up_fetch_sticker_pdf_bytes(
                bc_sel, hide_delivery_price=bool(st.session_state.get("up_journal_hide_price"))
            )
            if pdf:
                st.session_state[f"up_sticker_pdf_{bc_sel}"] = pdf
            else:
                st.error(perr or "Не вдалося")
        pdf_cached = st.session_state.get(f"up_sticker_pdf_{bc_sel}")
        if pdf_cached:
            st.download_button(
                "PDF ярлик (Zebra)",
                data=pdf_cached,
                file_name=f"up_sticker_{bc_sel}.pdf",
                mime="application/pdf",
                key=f"up_journal_dl_{bc_sel}",
                use_container_width=True,
            )
    with a3:
        sticker_url = up_sticker_pdf_url(bc_sel)
        st.link_button("Відкрити PDF", sticker_url, use_container_width=True)
    with a4:
        st.checkbox("Без варт. дост.", key="up_journal_hide_price")

    st.caption(
        "Друк на **Zebra**: завантаж PDF → друк на принтер 100×100 мм (або «Відкрити PDF» → Друк). "
        "У Zebra Setup Utilities обери розмір етикетки 100×100."
    )

    st.markdown("**Видалення**")
    only_local = st.checkbox(
        "Лише прибрати з журналу (не видаляти в Укрпошті)",
        key="up_journal_delete_local_only",
    )
    if st.button("Видалити ТТН", key="up_journal_delete_btn", type="secondary"):
        if not only_local:
            ok, derr = up_delete_shipment_by_barcode(bc_sel)
            if not ok:
                st.error(derr)
                st.stop()
        if sheets.delete_up_shipment_record(bc_sel):
            _cached_up_shipments_df.clear()
            if st.session_state.get("up_journal_active_bc") == bc_sel:
                st.session_state.up_last_create_response = None
                st.session_state.up_journal_active_bc = ""
            st.success(
                "Прибрано з журналу."
                if only_local
                else "Видалено в Укрпошті та прибрано з журналу."
            )
            st.rerun()
        else:
            st.warning("Запис у журналі не знайдено (можливо вже видалено).")

    bc_norm = _up_normalize_bc(bc_sel)
    show_edit = _up_normalize_bc(st.session_state.get("up_journal_edit_bc")) == bc_norm
    resp = st.session_state.get("up_last_create_response")
    if show_edit:
        if not resp or _up_normalize_bc(_up_barcode_from_create_response(resp) or "") != bc_norm:
            row_match = df[df["ШКІ"].astype(str).str.strip().apply(_up_normalize_bc) == bc_norm]
            if not row_match.empty:
                snap = str(row_match.iloc[0].get("JSON", "")).strip()
                if snap:
                    try:
                        resp = _json.loads(snap)
                        st.session_state.up_last_create_response = resp
                    except Exception:
                        resp = None
            if not resp:
                data, err = up_fetch_shipment(bc_sel)
                if not err and data:
                    resp = data
                    st.session_state.up_last_create_response = data
        if resp:
            _render_up_shipment_edit_section(resp)

    st.divider()


def _render_up_shipment_edit_section(source: dict | None):
    """Форма редагування останнього (або завантаженого) відправлення УП."""
    if not source or not isinstance(source, dict):
        return
    suuid = _up_shipment_uuid_from_response(source)
    if not suuid:
        st.caption("У відповіді API немає `uuid` відправлення — редагування недоступне.")
        return

    _up_seed_edit_form_from_shipment(source)
    status = str(st.session_state.get("up_edit_lifecycle_status", "") or _up_lifecycle_status(source))
    bc = str(st.session_state.get("up_edit_barcode", "") or "")
    expanded = bool(st.session_state.get("up_edit_panel_open")) or status in ("", "CREATED")

    with st.expander("Редагувати відправлення в Укрпошті", expanded=expanded):
        st.caption(f"UUID: `{suuid}`" + (f" · ШКІ: `{bc}`" if bc else "") + (f" · статус: **{status}**" if status else ""))
        if not str(st.session_state.get("up_edit_parcel_uuid", "")).strip():
            st.info(
                "Немає uuid місця (parcel) у відповіді — натисни **Завантажити** за ШКІ після створення ТТН."
            )
        if status and status != "CREATED":
            st.warning(
                "Зміни через API зазвичай можливі лише в статусі **CREATED** (до прийому на пошті). "
                "Якщо збереження не вдасться — редагуй у кабінеті ok.ukrposhta."
            )

        l1, l2 = st.columns([4, 1])
        with l1:
            st.text_input("ШКІ для завантаження", key="up_edit_load_barcode", placeholder="050…")
        with l2:
            st.write("")
            if st.button("Завантажити", key="up_edit_load_btn", use_container_width=True):
                ident = str(st.session_state.get("up_edit_load_barcode", "")).strip()
                data, err = up_fetch_shipment(ident)
                if err:
                    st.error(err)
                elif data:
                    st.session_state.up_last_create_response = data
                    st.session_state.up_edit_seeded_uuid = ""
                    _up_seed_edit_form_from_shipment(data, force=True)
                    st.rerun()

        st.markdown("**Адреса отримувача**")
        if st.button("Підставити індекс з УП", key="up_edit_lookup_postcode"):
            pc = str(st.session_state.get("up_edit_postcode", "")).strip()
            res, err = up_lookup_by_postcode(pc)
            if err:
                st.error(err)
            elif res:
                st.session_state.up_edit_region = res.get("region", "")
                st.session_state.up_edit_district = res.get("district", "")
                st.session_state.up_edit_city = res.get("city", "")
                st.rerun()
        a1, a2 = st.columns(2)
        with a1:
            st.text_input("Індекс *", key="up_edit_postcode", max_chars=5)
            st.text_input("Район", key="up_edit_district")
        with a2:
            st.text_input("Область *", key="up_edit_region")
            st.text_input("Населений пункт *", key="up_edit_city")
        a3, a4, a5 = st.columns(3)
        with a3:
            st.text_input("Вулиця", key="up_edit_street")
        with a4:
            st.text_input("Будинок", key="up_edit_house")
        with a5:
            st.text_input("Квартира", key="up_edit_apartment")
        r1, r2, r3 = st.columns(3)
        with r1:
            st.text_input("Прізвище", key="up_edit_lastname")
        with r2:
            st.text_input("Імʼя", key="up_edit_firstname")
        with r3:
            _pp = _up_num_float(st.session_state.get("up_edit_postpay_uah", 0))
            st.text_input(
                "По батькові" + (" *" if _pp >= 1 else ""),
                key="up_edit_middlename",
                help="Обовʼязково для післяплати (Укрпошта UPE01002).",
            )
        st.text_input("Телефон отримувача", key="up_edit_phone")
        if _up_num_float(st.session_state.get("up_edit_postpay_uah", 0)) >= 1:
            st.caption("При післяплаті Укрпошта вимагає повне ПІБ отримувача.")

        st.markdown("**Відправлення**")
        labels = list(_UP_DELIVERY_LABELS.keys())
        st.selectbox("Тип доставки", labels, key="up_edit_delivery_label_pick")
        st.text_area("Опис відправлення", key="up_edit_description", height=72)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.number_input("Вага, г", min_value=1, max_value=30000, step=50, key="up_edit_weight_g")
        with m2:
            st.number_input("Довжина, см", min_value=1, max_value=200, step=1, key="up_edit_length_cm")
        with m3:
            st.number_input("Ширина, см", min_value=0, max_value=200, step=1, key="up_edit_width_cm")
        with m4:
            st.number_input("Висота, см", min_value=0, max_value=200, step=1, key="up_edit_height_cm")
        e1, e2 = st.columns(2)
        with e1:
            st.number_input("Оголошена вартість, грн", min_value=0.0, step=1.0, key="up_edit_declared_uah")
        with e2:
            st.number_input("Післяплата, грн", min_value=0.0, step=1.0, key="up_edit_postpay_uah")
        st.checkbox("Зараховувати післяплату на IBAN", key="up_edit_transfer_postpay_iban")
        p1, p2 = st.columns(2)
        with p1:
            st.checkbox("Доставку сплачує одержувач", key="up_edit_paid_shipment_recipient")
        with p2:
            st.checkbox("Пересилання післяплати сплачує одержувач", key="up_edit_paid_postpay_recipient")
        st.checkbox("СМС", key="up_edit_sms")
        st.checkbox("Огляд при врученні", key="up_edit_check_delivery")
        st.radio(
            "У разі невручення",
            ["повернути", "не повертати"],
            key="up_edit_fail_main",
            horizontal=True,
        )

        if st.button("Зберегти зміни в Укрпошті", type="primary", key="up_edit_save_btn"):
            v_err = _up_validate_edit_form()
            if v_err:
                st.error(v_err)
            else:
                data, err = _up_save_shipment_edit(suuid)
                if err:
                    st.error(f"Редагування: {err}")
                else:
                    st.session_state.up_last_create_response = data
                    st.session_state.up_edit_seeded_uuid = ""
                    _up_seed_edit_form_from_shipment(data, force=True)
                    new_bc = _up_barcode_from_create_response(data)
                    st.success(
                        f"Зміни збережено."
                        + (f" ШКІ: `{new_bc}`" if new_bc else "")
                        + (
                            f" Вартість доставки: {data.get('deliveryPrice')} грн"
                            if isinstance(data, dict) and data.get("deliveryPrice") is not None
                            else ""
                        )
                    )
                    st.toast("Укрпошта: відправлення оновлено", icon="✅")
                    up_journal_save_response(data)

        if bc:
            p1, p2, p3 = st.columns(3)
            with p1:
                if st.button("Отримати PDF ярлик", key="up_edit_fetch_sticker", use_container_width=True):
                    pdf, perr = up_fetch_sticker_pdf_bytes(bc)
                    if pdf:
                        st.session_state.up_edit_sticker_pdf = pdf
                    else:
                        st.error(perr or "Не вдалося")
            pdf_edit = st.session_state.get("up_edit_sticker_pdf")
            if pdf_edit:
                with p2:
                    st.download_button(
                        "Завантажити PDF (Zebra)",
                        data=pdf_edit,
                        file_name=f"up_sticker_{bc}.pdf",
                        mime="application/pdf",
                        key="up_edit_dl_sticker",
                        use_container_width=True,
                    )
            with p3:
                st.link_button("Відкрити PDF", up_sticker_pdf_url(bc), use_container_width=True)


UP_ECOM_BASE = "https://www.ukrposhta.ua/ecom/0.0.1"
UP_CLASSIFIER_BASES = (
    "https://www.ukrposhta.ua/address-classifier-ws",
    "https://ukrposhta.ua/address-classifier-ws",
)
_UP_DELIVERY_LABELS = {
    "склад – склад": "W2W",
    "двері – двері": "D2D",
    "склад – двері": "W2D",
    "двері – склад": "D2W",
}
_UP_SERVICE_API = {
    "Базовий": "STANDARD",
    "Пріоритетний": "EXPRESS",
}
_UP_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _up_is_valid_uuid(val: str) -> bool:
    return bool(_UP_UUID_RE.match(str(val or "").strip()))


def _up_ecom_token() -> str:
    """PROD counterparty token для ?token= (лист менеджера УП)."""
    load_secrets_to_config()
    return (
        str(getattr(config, "UP_COUNTERPARTY_TOKEN", "") or "").strip()
        or str(getattr(config, "UP_USER_TOKEN", "") or "").strip()
    )


def _up_format_ecom_error(err: str) -> str:
    if not err:
        return err
    s = str(err)
    if "UPE05001" in s or "Counterparty mismatch" in s:
        tok = _up_ecom_token()
        uuid = str(getattr(config, "UP_UUID", "") or "").strip()
        sender = str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
        return (
            "Контрагент не збігається (UPE05001): **UP_BEARER_TOKEN**, **UP_UUID**, "
            "**UP_COUNTERPARTY_TOKEN** / **UP_USER_TOKEN** і **UP_SENDER_UUID** "
            "мають бути з **одного** PRODUCTION-набору (лист від менеджера Укрпошти).\n\n"
            f"Токен …{tok[-12:] if len(tok) > 12 else tok or '—'}, "
            f"UP_UUID …{uuid[-12:] if len(uuid) > 12 else uuid or '—'}, "
            f"відправник …{sender[-12:] if len(sender) > 12 else sender or '—'}.\n\n"
            "**UP_SENDER_UUID** — UUID **клієнта-відправника** в eCom (не плутати з UP_UUID контрагента). "
            "Його видно в кабінеті ok.ukrposhta або через «Перевірити відправника» у діагностиці.\n\n"
            f"Відповідь API: {s}"
        )
    return s


def _up_verify_sender_uuid(sender_uuid: str = "") -> str:
    """Порожній рядок = OK; інакше текст помилки."""
    load_secrets_to_config()
    sender = (sender_uuid or str(getattr(config, "UP_SENDER_UUID", "") or "")).strip()
    err = _up_uuid_error(sender, "UUID відправника (UP_SENDER_UUID)")
    if err:
        return err
    data, err = up_ecom_request("GET", f"/clients/{sender}")
    if err:
        if "UPE05001" in err or "Counterparty mismatch" in err:
            return (
                f"UP_SENDER_UUID …{sender[-12:]} **чужий** — не від вашого контрагента "
                f"({str(getattr(config, 'UP_UUID', '') or '')[-12:]}). "
                "Видали рядок UP_SENDER_UUID з Secrets (залиш ключі з листа менеджера) — "
                "додаток створить відправника сам, якщо є UP_SENDER_NAME, UP_SENDER_BRANCH_INDEX "
                "та UP_SENDER_PHONE. Або вкажи правильний UUID з ok.ukrposhta → eCom."
            )
        if "UPE02001" in err or "not found" in err.lower():
            return (
                f"Відправника {sender} не знайдено для вашого токена eCom. "
                "Вкажи правильний UP_SENDER_UUID з кабінету ok.ukrposhta (клієнт-відправник)."
            )
        return _up_format_ecom_error(err)
    cp = str((data or {}).get("counterpartyUuid", "")).strip()
    expected = str(getattr(config, "UP_UUID", "") or "").strip()
    if expected and cp and cp.lower() != expected.lower():
        return (
            f"UP_SENDER_UUID належить контрагенту {cp}, а UP_UUID у Secrets — {expected}. "
            "Усі ключі мають бути з одного листа PRODUCTION."
        )
    ctype = str((data or {}).get("type") or "").strip()
    if _up_expect_fop_sender() and ctype and ctype != "PRIVATE_ENTREPRENEUR":
        return (
            f"UP_SENDER_UUID — це **{_up_client_type_label(ctype)}**, а не ФОП. "
            "Видали рядок **UP_SENDER_UUID** з Secrets, додай **UP_SENDER_TIN** (ІПН) — "
            "додаток створить клієнта типу ФОП автоматично."
        )
    return ""


def _up_uuid_error(val: str, label: str) -> str:
    """Порожній рядок = OK; інакше текст помилки."""
    s = str(val or "").strip()
    if not s:
        return f"Немає {label}."
    low = s.lower()
    if "твій-uuid" in low or "xxxxxxxx-xxxx" in low or low.startswith("твій "):
        return (
            f"{label} — це приклад із інструкції, не справжній UUID. "
            f"Візьми UUID відправника з кабінету eCom Укрпошти (ok.ukrposhta) і вкажи в Secrets як UP_SENDER_UUID."
        )
    if not _up_is_valid_uuid(s):
        return (
            f"{label} некоректний: «{s[:40]}…». "
            "Потрібен UUID у форматі 8-4-4-4-12 (36 символів, латиниця та цифри)."
        )
    return ""


def _up_num_float(val, default=0.0):
    try:
        return float(str(val).replace(",", ".").strip() or default)
    except Exception:
        return default


def _up_num_int(val, default=0):
    try:
        return int(round(_up_num_float(val, default)))
    except Exception:
        return default


def _up_section_title(text: str):
    st.markdown(
        f'<p class="up-section-title">{html.escape(text)}</p>',
        unsafe_allow_html=True,
    )


def _up_inject_form_css():
    st.markdown(
        """
<style>
.up-section-title {
  color: #0057b7;
  font-weight: 700;
  border-bottom: 3px solid #ffcc00;
  padding-bottom: 6px;
  margin: 18px 0 12px 0;
  font-size: 1.05rem;
}
.up-sender-box {
  background: #f7f7f7;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 8px;
  line-height: 1.5;
  font-size: 0.95rem;
}
.up-parcel-box {
  background: #f3f3f3;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 12px 14px 4px 14px;
  margin: 8px 0 12px 0;
}
.up-parcel-sub {
  color: #0057b7;
  font-weight: 600;
  margin: 0 0 10px 0;
}
div[data-testid="stHorizontalBlock"] .up-action-cancel button {
  background: #c0392b !important;
  color: #fff !important;
  border: none !important;
}
div[data-testid="stHorizontalBlock"] .up-action-calc button {
  background: #f1c40f !important;
  color: #222 !important;
  border: none !important;
}
div[data-testid="stHorizontalBlock"] .up-action-create button {
  background: #27ae60 !important;
  color: #fff !important;
  border: none !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def _up_classifier_entries(data):
    if not isinstance(data, dict):
        return []
    entries = data.get("Entries") or data.get("entries") or {}
    if not isinstance(entries, dict):
        return []
    entry = entries.get("Entry") or entries.get("entry")
    if entry is None:
        return []
    if isinstance(entry, list):
        return [e for e in entry if isinstance(e, dict)]
    if isinstance(entry, dict):
        return [entry]
    return []


def _up_classifier_pick(entry: dict, *keys: str) -> str:
    for key in keys:
        val = entry.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in ("0", "null", "None"):
            return s
    return ""


def _up_classifier_bearer():
    load_secrets_to_config()
    for key in ("UP_CLASSIFIER_BEARER", "UP_BEARER_TOKEN"):
        val = _read_st_secret(key) or str(getattr(config, key, "") or "").strip()
        if val:
            return val
    return ""


def _up_classifier_xml_to_dict(raw: bytes):
    """Парсить XML-відповідь класифікатора (без Accept: application/json)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw)
    entries = []
    for entry_el in root.iter():
        tag = entry_el.tag.split("}")[-1] if "}" in entry_el.tag else entry_el.tag
        if tag != "Entry":
            continue
        row = {}
        for child in entry_el:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child.text:
                row[ctag] = child.text.strip()
        if row:
            entries.append(row)
    if not entries:
        return None
    return {"Entries": {"Entry": entries if len(entries) > 1 else entries[0]}}


def _up_classifier_fetch_json(path: str, params: dict, bearer: str):
    """GET класифікатора: спочатку urllib (стабільно на Streamlit Cloud), потім requests."""
    import json as _json
    import urllib.error
    import urllib.parse
    import urllib.request

    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
        "User-Agent": "logistic-manager/1.0",
    }
    qs = urllib.parse.urlencode(params or {})
    last_err = ""

    for base in UP_CLASSIFIER_BASES:
        url = f"{base}{path}"
        full_url = f"{url}?{qs}" if qs else url
        try:
            req = urllib.request.Request(full_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
                if resp.status != 200:
                    last_err = f"HTTP {resp.status} ({base})"
                    continue
                text = raw.decode("utf-8", errors="replace").lstrip()
                if text.startswith("<"):
                    parsed = _up_classifier_xml_to_dict(raw)
                    if parsed:
                        return parsed, ""
                try:
                    return _json.loads(text), ""
                except Exception:
                    parsed = _up_classifier_xml_to_dict(raw)
                    if parsed:
                        return parsed, ""
                    return {"raw": text[:800]}, ""
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                body = ""
            last_err = f"HTTP {e.code} ({base}): {body}"
        except Exception as e:
            last_err = f"{base}: {e}"

    try:
        url = f"{UP_CLASSIFIER_BASES[0]}{path}"
        r = utils.std_requests.get(url, headers=headers, params=params, timeout=25)
        if r is not None and r.status_code == 200:
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        if r is not None:
            last_err = f"requests HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        last_err = last_err or str(e)[:300]

    return None, last_err or "немає відповіді"


def up_classifier_get(endpoint: str, params: dict):
    """GET адресного класифікатора Укрпошти. Повертає (data|None, error)."""
    bearer = _up_classifier_bearer()
    if not bearer:
        return None, (
            "Немає UP_BEARER_TOKEN у Secrets (PRODUCTION BEARER eCom). "
            "Додай рядок UP_BEARER_TOKEN = \"…\" у Streamlit → Secrets і зроби Reboot app."
        )
    path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    data, err = _up_classifier_fetch_json(path, params, bearer)
    if data is None:
        hint = f" ({err})" if err else ""
        return None, f"Немає відповіді від класифікатора адрес.{hint}"
    return data, ""


def _up_parse_classifier_entry(e: dict, pc: str):
    region = _up_classifier_pick(e, "REGION_UA", "REGION_NAME", "region_ua", "region_name")
    district = _up_classifier_pick(
        e,
        "DISTRICT_UA",
        "DISTRICT_NAME",
        "NEW_DISTRICT_UA",
        "NEW_DISTRICT_NAME",
        "district_ua",
    )
    city = _up_classifier_pick(e, "CITY_UA", "CITY_NAME", "city_ua", "CITYNAME_UA")
    citytype = _up_classifier_pick(e, "CITYTYPE_UA", "CITYTYPE_NAME", "SHORTCITYTYPE_UA")
    if citytype and city and not str(city).lower().startswith(str(citytype).lower()):
        city = f"{citytype} {city}".strip()
    elif not city:
        city = " ".join(
            p
            for p in (
                citytype,
                _up_classifier_pick(e, "CITYNAME_UA"),
            )
            if p
        ).strip()
    if region or district or city:
        return {"region": region, "district": district, "city": city, "postcode": pc}
    return None


def up_lookup_by_postcode(postcode: str):
    """Область / район / населений пункт за індексом (режим «Знаю індекс»)."""
    pc = re.sub(r"\D", "", str(postcode or ""))[:5]
    if len(pc) != 5:
        return None, "Індекс має містити 5 цифр."
    last_err = ""
    params = {"postcode": pc, "lang": "UA"}
    for endpoint in ("/get_city_details_by_postcode", "/get_address_by_postcode"):
        data, err = up_classifier_get(endpoint, params)
        if err:
            last_err = err
            continue
        for e in _up_classifier_entries(data):
            parsed = _up_parse_classifier_entry(e, pc)
            if parsed:
                return parsed, ""

    data, err = up_classifier_get("/get_postoffices_by_postindex", {"pi": pc})
    if not err:
        for e in _up_classifier_entries(data):
            parsed = _up_parse_classifier_entry(e, pc)
            if parsed:
                return parsed, ""
        if last_err:
            last_err = f"{last_err} (відділення за індексом теж без адреси)"
    elif not last_err:
        last_err = err

    if last_err:
        return None, last_err
    return None, f"За індексом {pc} нічого не знайдено."


def _up_postcode_on_change():
    _up_on_postcode_lookup(force=False)


def _up_postcode_lookup_click():
    _up_on_postcode_lookup(force=True)


def _up_on_postcode_lookup(force: bool = False):
    """Callback: підтягнути область/район/місто за індексом."""
    if st.session_state.get("upwiz_index_mode") != "Знаю індекс":
        return
    pc = re.sub(r"\D", "", str(st.session_state.get("upwiz_postcode", "")).strip())[:5]
    if len(pc) != 5:
        st.session_state.upwiz_lookup_error = "Введи 5 цифр індексу."
        st.session_state.upwiz_postcode_lookup_ok = False
        return
    if not force and st.session_state.get("upwiz_postcode_lookup_last") == pc:
        return
    result, err = up_lookup_by_postcode(pc)
    st.session_state.upwiz_postcode_lookup_last = pc
    if err:
        st.session_state.upwiz_lookup_error = err
        st.session_state.upwiz_postcode_lookup_ok = False
        return
    st.session_state.upwiz_lookup_error = ""
    st.session_state.upwiz_postcode_lookup_ok = True
    # Не змінюємо upwiz_postcode — це key віджета; лише область/район/місто (віджети нижче).
    st.session_state.upwiz_region = result.get("region", "")
    st.session_state.upwiz_district = result.get("district", "")
    st.session_state.upwiz_city = result.get("city", "")


def up_ecom_request(method: str, path: str, body=None, token_required=True):
    """Універсальний запит до eCom API. Повертає (data|None, error)."""
    load_secrets_to_config()
    ecom_token = _up_ecom_token()
    if token_required and not ecom_token:
        return None, "Немає UP_COUNTERPARTY_TOKEN / UP_USER_TOKEN у Secrets (PROD token eCom)."
    if not config.UP_BEARER_TOKEN:
        return None, "Немає UP_BEARER_TOKEN у Secrets."
    if not str(getattr(config, "UP_UUID", "") or "").strip():
        return None, "Немає UP_UUID у Secrets (обовʼязковий для eCom API)."
    url = f"{UP_ECOM_BASE}{path}"
    params = {"token": ecom_token} if token_required else None
    headers = build_up_headers(
        bearer_token=config.UP_BEARER_TOKEN,
        uuid=config.UP_UUID or None,
        uuid_sand=config.UP_UUID_SAND or None,
        counterparty_token=ecom_token or None,
        include_content_type=True,
    )
    try:
        timeout = (
            60
            if method.upper() in ("POST", "PUT") and "/shipments" in path
            else 30
        )
        r = utils.make_request(
            method, url, headers=headers, params=params, json=body, timeout=timeout
        )
        if not r:
            hint = utils.get_last_request_error()
            msg = "Немає відповіді від сервера Укрпошти (eCom)."
            if hint:
                msg += f" ({hint})"
            return None, msg
        if r.status_code in (200, 201, 204):
            if method.upper() == "DELETE" or not (r.text or "").strip():
                return {}, ""
            try:
                return r.json(), ""
            except Exception:
                return {"raw": r.text}, ""
        try:
            err_js = r.json()
        except Exception:
            err_js = {"text": r.text[:800]}
        return None, _up_format_ecom_error(f"HTTP {r.status_code}: {err_js}")
    except Exception as e:
        return None, str(e)[:500]


def up_post_address_from_form():
    """POST /addresses — адреса отримувача з полів форми."""
    postcode = str(st.session_state.get("upwiz_postcode", "")).strip()
    region = str(st.session_state.get("upwiz_region", "")).strip()
    district = str(st.session_state.get("upwiz_district", "")).strip()
    city = str(st.session_state.get("upwiz_city", "")).strip()
    street = str(st.session_state.get("upwiz_street", "")).strip()
    house = str(st.session_state.get("upwiz_house", "")).strip()
    apartment = str(st.session_state.get("upwiz_apartment", "")).strip()
    if not postcode or not region or not city:
        return None, "Заповни індекс, область і населений пункт."
    body = {
        "country": "UA",
        "postcode": postcode,
        "region": region[:45],
        "city": city[:45],
    }
    if district:
        body["district"] = district[:45]
    if street:
        body["street"] = street[:255]
    if house:
        body["houseNumber"] = house[:15]
    if apartment:
        body["apartmentNumber"] = apartment[:15]
    # foreignStreetHouseApartment — лише для країн ≠ UA; для України API UPE01002 забороняє це поле.
    if not street and not house:
        desc = str(st.session_state.get("upwiz_address_note", "") or "").strip()
        if desc:
            body["description"] = desc[:255]
    data, err = up_ecom_request("POST", "/addresses", body, token_required=False)
    if err:
        return None, f"Адреса отримувача: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу не створено: {data}"
    return addr_id, ""


def up_post_client_from_form(address_id):
    """POST /clients — фізособа-отримувач."""
    last = str(st.session_state.get("upwiz_lastname", "")).strip()
    first = str(st.session_state.get("upwiz_firstname", "")).strip()
    middle = str(st.session_state.get("upwiz_middlename", "")).strip()
    phone = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
    if not last or not first:
        return None, "Заповни прізвище та імʼя отримувача."
    if not phone or len(phone) < 10:
        return None, "Заповни коректний телефон отримувача."
    body = {
        "type": "INDIVIDUAL",
        "lastName": last,
        "firstName": first,
        "phoneNumber": phone if phone.startswith("+") else f"+{phone}",
        "addressId": str(address_id),
    }
    if middle:
        body["middleName"] = middle
    data, err = up_ecom_request("POST", "/clients", body)
    if err:
        return None, f"Клієнт отримувача: {err}"
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if not uuid:
        return None, f"Клієнта не створено: {data}"
    return str(uuid).strip(), ""


def _up_get_recipient_uuid() -> str:
    """UUID отримувача: вручну з поля або збережений після створення через API."""
    manual = str(st.session_state.get("upwiz_recipient_uuid", "")).strip()
    if manual:
        return manual
    return str(st.session_state.get("upwiz_recipient_uuid_created", "")).strip()


def up_create_sender_client_from_secrets():
    """Створити клієнта-відправника в eCom за даними з Secrets."""
    load_secrets_to_config()
    name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip()
    if not name:
        return None, "Додай UP_SENDER_NAME у Secrets (ПІБ або «ФОП Прізвище Імʼя»)."
    phone = utils.clean_phone(str(getattr(config, "UP_SENDER_PHONE", "") or "").strip())
    if not phone or len(phone) < 10:
        return None, "Додай UP_SENDER_PHONE у Secrets (телефон відправника, 380…)."
    postcode = re.sub(
        r"\D",
        "",
        str(
            getattr(config, "UP_SENDER_BRANCH_INDEX", "")
            or getattr(config, "UP_SENDER_POSTCODE", "")
            or ""
        ),
    )[:5]
    if len(postcode) != 5:
        return None, "Вкажи UP_SENDER_BRANCH_INDEX або UP_SENDER_POSTCODE (5 цифр) у Secrets."

    loc, loc_err = up_lookup_by_postcode(postcode)
    if not loc:
        return None, f"Індекс відправника {postcode}: {loc_err or 'не знайдено в класифікаторі'}."

    body_addr = {
        "country": "UA",
        "postcode": postcode,
        "region": str(loc.get("region", ""))[:45],
        "city": str(loc.get("city", ""))[:45],
    }
    if loc.get("district"):
        body_addr["district"] = str(loc.get("district", ""))[:45]
    addr_text = str(getattr(config, "UP_SENDER_ADDRESS", "") or "").strip()
    if addr_text:
        body_addr["street"] = addr_text[:255]
    else:
        body_addr["street"] = "вул."

    data, err = up_ecom_request("POST", "/addresses", body_addr, token_required=False)
    if err:
        return None, f"Адреса відправника: {err}"
    addr_id = data.get("id") if isinstance(data, dict) else None
    if not addr_id:
        return None, f"Адресу відправника не створено: {data}"

    phone_fmt = phone if phone.startswith("+") else f"+{phone}"

    if _up_expect_fop_sender():
        tin = re.sub(r"\D", "", str(getattr(config, "UP_SENDER_TIN", "") or ""))[:10]
        if len(tin) != 10:
            return None, (
                "Для відправника **ФОП** додай **UP_SENDER_TIN** (ІПН, 10 цифр) у Secrets. "
                "Або вкажи UP_SENDER_TYPE = INDIVIDUAL, якщо це фізособа без ФОП."
            )
        display_name = name if re.match(r"(?i)^фоп", name) else f"ФОП {name}"
        body_client = {
            "type": "PRIVATE_ENTREPRENEUR",
            "name": display_name[:60],
            "phoneNumber": phone_fmt,
            "addressId": str(addr_id),
            "tin": tin,
        }
        bank = str(getattr(config, "UP_SENDER_BANK_ACCOUNT", "") or "").strip()
        if bank:
            body_client["bankAccount"] = bank[:34]
    else:
        clean_name = re.sub(r"(?i)^фоп\s+", "", name).strip()
        parts = clean_name.split()
        if len(parts) >= 2:
            last, first = parts[0], parts[1]
            middle = " ".join(parts[2:]) if len(parts) > 2 else ""
        else:
            last, first, middle = clean_name, clean_name, ""
        body_client = {
            "type": "INDIVIDUAL",
            "lastName": last[:250],
            "firstName": first[:250],
            "phoneNumber": phone_fmt,
            "addressId": str(addr_id),
        }
        if middle:
            body_client["middleName"] = middle[:250]

    data, err = up_ecom_request("POST", "/clients", body_client)
    if err:
        return None, f"Клієнт-відправник: {err}"
    uuid = data.get("uuid") if isinstance(data, dict) else None
    if not uuid:
        return None, f"Відправника не створено: {data}"
    return str(uuid).strip(), ""


def _up_ensure_sender_uuid():
    """UUID відправника: з Secrets, кешу або автостворення під вашим токеном."""
    load_secrets_to_config()
    cached = str(st.session_state.get("upwiz_sender_uuid_created", "")).strip()
    if cached and not _up_verify_sender_uuid(cached):
        return cached, ""

    configured = str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
    if configured:
        err = _up_verify_sender_uuid(configured)
        if not err:
            return configured, ""
        uid, cerr = up_create_sender_client_from_secrets()
        if uid:
            st.session_state.upwiz_sender_uuid_created = uid
            return uid, ""
        return None, f"{err}\n\nАвтостворення: {cerr}"

    uid, cerr = up_create_sender_client_from_secrets()
    if cerr:
        return None, cerr
    st.session_state.upwiz_sender_uuid_created = uid
    return uid, ""


def _up_ensure_recipient_uuid():
    """UUID отримувача: з поля або створення через API."""
    uid = _up_get_recipient_uuid()
    if uid:
        return uid, ""
    addr_id, err = up_post_address_from_form()
    if err:
        return None, err
    uid, err = up_post_client_from_form(addr_id)
    if err:
        return None, err
    # Не писати в upwiz_recipient_uuid — це key text_input; лише окремий ключ.
    st.session_state.upwiz_recipient_uuid_created = uid
    return uid, ""


def _up_validate_wizard_form():
    """Перевірка обовʼязкових полів форми."""
    missing = []
    if not str(st.session_state.get("upwiz_lastname", "")).strip():
        missing.append("прізвище")
    if not str(st.session_state.get("upwiz_firstname", "")).strip():
        missing.append("імʼя")
    if not utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip()):
        missing.append("телефон")
    if not str(st.session_state.get("upwiz_postcode", "")).strip():
        missing.append("індекс")
    if not str(st.session_state.get("upwiz_region", "")).strip():
        missing.append("область")
    if not str(st.session_state.get("upwiz_city", "")).strip():
        missing.append("населений пункт")
    if _up_num_int(st.session_state.get("upwiz_weight_g", 0)) < 1:
        missing.append("вага")
    if _up_num_int(st.session_state.get("upwiz_length_cm", 0)) < 1:
        missing.append("довжина")
    if missing:
        return f"Заповни обовʼязкові поля: {', '.join(missing)}."
    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    if postpay >= 1 and not str(st.session_state.get("upwiz_middlename", "")).strip():
        return "Для післяплати потрібне по батькові отримувача."
    return ""


def _up_build_shipment_dict_from_wizard(recipient_uuid=None, sender_uuid=None):
    """Збір тіла POST /shipments з полів форми (кабінет ok.ukrposhta)."""
    sender = (
        sender_uuid
        or str(st.session_state.get("upwiz_sender_uuid_created", "")).strip()
        or str(getattr(config, "UP_SENDER_UUID", "") or "").strip()
    )
    recipient = recipient_uuid or _up_get_recipient_uuid()
    err = _up_uuid_error(sender, "UUID відправника")
    if err:
        return None, err
    err = _up_uuid_error(recipient, "UUID отримувача")
    if err:
        return None, err

    service_label = st.session_state.get("upwiz_service", "Базовий")
    ship_type = _UP_SERVICE_API.get(service_label, "STANDARD")
    delivery_label = st.session_state.get("upwiz_delivery_label", "склад – двері")
    delivery = _UP_DELIVERY_LABELS.get(delivery_label, "W2D")

    grams = max(1, _up_num_int(st.session_state.get("upwiz_weight_g", 500)))
    length = max(1, min(_up_num_int(st.session_state.get("upwiz_length_cm", 30)), 200))
    width = max(0, _up_num_int(st.session_state.get("upwiz_width_cm", 0)))
    height = max(0, _up_num_int(st.session_state.get("upwiz_height_cm", 0)))

    parcel = {"weight": grams, "length": length, "width": width, "height": height}
    declared = _up_num_float(st.session_state.get("upwiz_declared_uah", 0))
    if declared > 0:
        parcel["declaredPrice"] = declared

    fail_main = st.session_state.get("upwiz_fail_main", "повернути")
    on_fail = "PROCESS_AS_REFUSAL" if fail_main == "не повертати" else "RETURN"

    body = {
        "type": ship_type,
        "sender": {"uuid": sender},
        "recipient": {"uuid": recipient},
        "deliveryType": delivery,
        "paidByRecipient": bool(st.session_state.get("upwiz_paid_shipment_recipient", False)),
        "postPayPaidByRecipient": bool(st.session_state.get("upwiz_paid_postpay_recipient", True)),
        "onFailReceiveType": on_fail,
        "nonCashPayment": False,
        "parcels": [parcel],
        "sms": bool(st.session_state.get("upwiz_sms", False)),
        "checkOnDelivery": bool(st.session_state.get("upwiz_check_delivery", True)),
    }

    sender_addr = str(getattr(config, "UP_SENDER_ADDRESS_ID", "") or "").strip()
    if sender_addr:
        try:
            body["senderAddressId"] = int(sender_addr)
        except ValueError:
            body["senderAddressId"] = sender_addr

    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
    if postpay >= 1:
        body["postPay"] = postpay
    if st.session_state.get("upwiz_transfer_postpay_iban"):
        body["transferPostpayToBankAccount"] = True

    desc = str(st.session_state.get("upwiz_description", "")).strip()
    if desc:
        body["description"] = desc[:255]

    phone = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
    if phone:
        body["recipientPhone"] = phone if phone.startswith("+") else f"+{phone}"

    return body, ""


def _up_reset_wizard_form():
    keep = {
        "upwiz_service",
        "upwiz_sender_uuid",
        "upwiz_delivery_label",
        "upwiz_paid_shipment_recipient",
        "upwiz_paid_postpay_recipient",
        "upwiz_fail_main",
        "upwiz_fail_return_service",
        "upwiz_check_delivery",
        "upwiz_form_open",
    }
    for key in list(st.session_state.keys()):
        if key.startswith("upwiz_") and key not in keep:
            del st.session_state[key]


def render_up_shipments_tab():
    """Оформлення ТТН Укрпошти — макет як у кабінеті ok.ukrposhta."""
    import json as _json

    load_secrets_to_config()
    _up_inject_form_css()

    if "upwiz_sender_uuid" not in st.session_state:
        st.session_state.upwiz_sender_uuid = str(getattr(config, "UP_SENDER_UUID", "") or "")
    if "upwiz_service" not in st.session_state:
        st.session_state.upwiz_service = "Базовий"
    if "upwiz_delivery_label" not in st.session_state:
        st.session_state.upwiz_delivery_label = "склад – двері"
    if "upwiz_check_delivery" not in st.session_state:
        st.session_state.upwiz_check_delivery = True
    if "upwiz_fail_main" not in st.session_state:
        st.session_state.upwiz_fail_main = "повернути"
    if "upwiz_fail_return_service" not in st.session_state:
        st.session_state.upwiz_fail_return_service = "Базовий"
    if "upwiz_phone" not in st.session_state:
        st.session_state.upwiz_phone = "+38"
    if "upwiz_index_mode" not in st.session_state:
        st.session_state.upwiz_index_mode = "Знаю індекс"

    st.markdown(
        '<div style="color:#0057b7;font-weight:800;font-size:1.35rem;margin-bottom:4px;">'
        "Створення відправлення Укрпошти"
        "</div>",
        unsafe_allow_html=True,
    )

    _render_up_shipments_journal()

    st.radio(
        "Тариф",
        ["Базовий", "Пріоритетний"],
        horizontal=True,
        key="upwiz_service",
        label_visibility="collapsed",
    )

    if st.button("Створити", type="primary", key="upwiz_show_form_btn"):
        st.session_state.upwiz_form_open = True

    diag = _up_secrets_diag()
    with st.expander("Діагностика підключення УП", expanded=not _up_classifier_bearer()):
        st.caption(f"Усі ключі у Secrets: {diag.get('_sections', '—')}")
        st.caption(f"Ключі UP_* у файлі: **{diag.get('_up_keys_in_file', '—')}**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write(f"UP_BEARER_TOKEN: **{diag.get('UP_BEARER_TOKEN', '—')}**")
            st.write(f"UP_USER_TOKEN: **{diag.get('UP_USER_TOKEN', '—')}**")
        with c2:
            st.write(f"UP_COUNTERPARTY: **{diag.get('UP_COUNTERPARTY_TOKEN', '—')}**")
            st.write(f"UP_UUID: **{diag.get('UP_UUID', '—')}**")
        with c3:
            st.write(f"UP_SENDER_UUID: **{diag.get('UP_SENDER_UUID', '—')}**")
            st.write(f"UP_TRACKING: **{diag.get('UP_TRACKING_TOKEN', '—')}**")
        missing = diag.get("_missing") or []
        if missing:
            st.warning(
                "Не знайдено в Secrets: **"
                + ", ".join(missing)
                + "**. Якщо ти їх уже вписав — натисни **Save** у вікні Secrets "
                "(без помилки знизу), потім **Manage app → Reboot**."
            )
            if diag.get("UP_TRACKING_TOKEN", "—") != "—" and diag.get("UP_BEARER_TOKEN", "—") == "—":
                st.error(
                    "Є лише **UP_TRACKING_TOKEN**, а **UP_BEARER_TOKEN** немає в збереженому файлі. "
                    "Часто це через **перенос рядка всередині лапок** UUID — кожне значення має бути "
                    "в **одному рядку** між `\"` і `\"`."
                )
        if diag.get("_tracking_source"):
            st.caption(f"UP_TRACKING_TOKEN зчитано з: {diag['_tracking_source']}")
        with st.expander("Як виправити Secrets (обери один варіант)"):
            st.markdown(
                "**Варіант A** — додай **один** ключ `UP_INLINE_SECRETS` (найпростіше, якщо окремі рядки не зберігаються):"
            )
            st.code(
                '''UP_INLINE_SECRETS = """
UP_BEARER_TOKEN = "afa51d96-ac05-3fe8-8654-68956e5f1b06"
UP_UUID = "b15a87ed-036d-4a3c-8a0c-f8f894480cd2"
UP_USER_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_COUNTERPARTY_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_SENDER_NAME = "ФОП Прізвище Імʼя"
UP_SENDER_TIN = "1234567890"
UP_SENDER_PHONE = "380501234567"
UP_SENDER_BRANCH_INDEX = "78301"
UP_SENDER_ADDRESS = "вул. …, буд. …"
# UP_SENDER_BANK_ACCOUNT = "UA…"  # опційно, для післяплати на рахунок
# UP_SENDER_UUID — не обовʼязково; якщо чужий або не ФОП — видали, створиться ФОП автоматично
"""''',
                language="toml",
            )
            st.markdown("**Варіант B** — секція `[ukrposhta]`:")
            st.code(
                """[ukrposhta]
UP_BEARER_TOKEN = "afa51d96-ac05-3fe8-8654-68956e5f1b06"
UP_UUID = "b15a87ed-036d-4a3c-8a0c-f8f894480cd2"
UP_USER_TOKEN = "9a199b93-07ce-426b-801f-bf99b427c598"
UP_SENDER_UUID = "uuid-відправника-з-кабінету-eCom"
""",
                language="toml",
            )
            st.caption(
                "UP_SENDER_UUID — не приклад «твій-uuid…», а реальний UUID з кабінету ok.ukrposhta → eCom → ваш відправник."
            )
            st.markdown(
                "**Варіант C** — окремі рядки в корені (кожен UUID **в один рядок**, потім **Save** → **Reboot**). "
                "Після Save у списку ключів зверху має з’явитись **UP_BEARER_TOKEN**, не лише UP_TRACKING_TOKEN."
            )
        ctest1, ctest2 = st.columns(2)
        with ctest1:
            if st.button("Тест індексу 78301", key="upwiz_test_index_btn"):
                load_secrets_to_config()
                res, err = up_lookup_by_postcode("78301")
                if err:
                    st.error(err)
                else:
                    st.success(
                        f"{res.get('region', '')}, {res.get('district', '')}, {res.get('city', '')}"
                    )
        with ctest2:
            if st.button("Перевірити відправника", key="upwiz_test_sender_btn"):
                load_secrets_to_config()
                sid, err = _up_ensure_sender_uuid()
                if err:
                    st.error(err)
                else:
                    cdata, _ = up_ecom_request("GET", f"/clients/{sid}")
                    ctype = str((cdata or {}).get("type") or "")
                    cname = str((cdata or {}).get("name") or "")
                    st.success(
                        f"Відправник OK: `{sid}` · **{_up_client_type_label(ctype)}**"
                        + (f" · {cname}" if cname else "")
                    )
                    if _up_expect_fop_sender() and ctype != "PRIVATE_ENTREPRENEUR":
                        st.warning(
                            "Очікується **ФОП**, але цей UUID — інший тип. "
                            "Видали UP_SENDER_UUID і додай UP_SENDER_TIN."
                        )
            if st.button("Тест eCom (адреса)", key="upwiz_test_ecom_btn"):
                load_secrets_to_config()
                if not config.UP_BEARER_TOKEN or not config.UP_UUID:
                    st.error("Потрібні UP_BEARER_TOKEN та UP_UUID у Secrets.")
                else:
                    probe = {
                        "country": "UA",
                        "postcode": "78301",
                        "region": "Закарпатська",
                        "city": "Ужгород",
                        "street": "test",
                        "houseNumber": "1",
                    }
                    data, err = up_ecom_request("POST", "/addresses", probe, token_required=False)
                    if err:
                        st.error(err)
                    else:
                        st.success(f"eCom OK, address id={data.get('id', '?')}")

    if not _up_classifier_bearer():
        st.error(
            "У Secrets не зчитується **UP_BEARER_TOKEN** (додаток бачить лише те, що збережено після **Save**). "
            "Перевір TOML: кожен UUID в один рядок → Save → **Reboot app**."
        )

    if not st.session_state.get("upwiz_form_open"):
        st.info("Оберіть тариф і натисніть **Створити**, щоб відкрити форму оформлення.")
        _cabinet_default = (
            "https://ok.ukrposhta.ua/ua/lk_old/standart/add/c0e7298c-f821-4879-8d04-efe1be943123#/know-index"
        )
        cabinet_url = str(getattr(config, "UP_CABINET_URL", "") or "").strip() or _cabinet_default
        st.link_button("Відкрити кабінет Укрпошти", cabinet_url)
        st.caption("Потрібні UP_BEARER_TOKEN, UP_USER_TOKEN, UP_SENDER_UUID; опційно UP_SENDER_NAME, UP_SENDER_ADDRESS.")
        return

    sender_name = str(getattr(config, "UP_SENDER_NAME", "") or "").strip() or "Відправник (UP_SENDER_NAME у Secrets)"
    sender_addr = str(getattr(config, "UP_SENDER_ADDRESS", "") or "").strip()
    branch_idx = str(
        getattr(config, "UP_SENDER_BRANCH_INDEX", "") or getattr(config, "UP_SENDER_POSTCODE", "") or ""
    ).strip()

    _up_section_title("Відправник:")
    fop_hint = "ФОП (PRIVATE_ENTREPRENEUR)" if _up_expect_fop_sender() else "фізична особа (INDIVIDUAL)"
    st.markdown(
        f'<div class="up-sender-box"><strong>{html.escape(sender_name)}</strong>'
        + (f"<br/>{html.escape(sender_addr)}" if sender_addr else "")
        + f"<br/><span style='opacity:0.85;font-size:0.9em'>Тип у API: {html.escape(fop_hint)}</span>"
        + "</div>",
        unsafe_allow_html=True,
    )
    if branch_idx and "upwiz_branch_index" not in st.session_state:
        st.session_state.upwiz_branch_index = branch_idx
    st.text_input(
        "Індекс відділення подачі відправлення:",
        disabled=bool(branch_idx),
        key="upwiz_branch_index",
        placeholder="78301",
    )

    _up_section_title("Одержувач:")
    st.radio(
        "Тип одержувача",
        ["Фізична особа", "Юридична особа"],
        horizontal=True,
        key="upwiz_recipient_kind",
        label_visibility="collapsed",
    )
    if st.session_state.get("upwiz_recipient_kind") == "Юридична особа":
        st.warning("Юридична особа через API потребує ЄДРПОУ — поки використовуй фізособу або UUID у «Розширено».")

    r1, r2 = st.columns(2)
    with r1:
        st.text_input("Прізвище: *", key="upwiz_lastname", placeholder="Прізвище")
    with r2:
        st.text_input("Імʼя: *", key="upwiz_firstname", placeholder="Імʼя")
    r3, r4 = st.columns(2)
    with r3:
        st.text_input(
            "По-батькові (обовʼязкове, якщо є післяплата):",
            key="upwiz_middlename",
            placeholder="По-батькові",
        )
    with r4:
        st.text_input("Телефон: *", key="upwiz_phone", placeholder="+380…")

    _up_section_title("Спосіб відправки:")
    st.selectbox(
        "Спосіб відправки",
        list(_UP_DELIVERY_LABELS.keys()),
        key="upwiz_delivery_label",
        label_visibility="collapsed",
    )

    _up_section_title("Адреса одержувача")
    st.radio(
        "Режим адреси",
        ["Знаю індекс", "Знайти індекс"],
        horizontal=True,
        key="upwiz_index_mode",
        label_visibility="collapsed",
    )
    know_index = st.session_state.get("upwiz_index_mode") == "Знаю індекс"
    if not know_index and st.session_state.get("upwiz_postcode_lookup_last"):
        st.session_state.upwiz_postcode_lookup_last = ""
        st.session_state.upwiz_postcode_lookup_ok = False
        st.session_state.upwiz_lookup_error = ""

    if know_index:
        pc_col, btn_col = st.columns([4, 1])
        with pc_col:
            st.text_input(
                "Індекс: *",
                key="upwiz_postcode",
                placeholder="Індекс (5 цифр)",
                max_chars=5,
                on_change=_up_postcode_on_change,
            )
        with btn_col:
            st.write("")
            st.button(
                "Підтягнути",
                key="upwiz_lookup_btn",
                use_container_width=True,
                on_click=_up_postcode_lookup_click,
            )
        lookup_err = str(st.session_state.get("upwiz_lookup_error", "")).strip()
        if lookup_err:
            st.warning(lookup_err)
        elif st.session_state.get("upwiz_postcode_lookup_ok"):
            st.caption("Область, район і населений пункт заповнено за індексом Укрпошти.")

    a1, a2 = st.columns(2)
    with a1:
        if not know_index:
            st.text_input("Індекс: *", key="upwiz_postcode", placeholder="Індекс", max_chars=5)
        st.text_input("Район:", key="upwiz_district", placeholder="Район")
    with a2:
        st.text_input("Область: *", key="upwiz_region", placeholder="Область")
        st.text_input("Населений пункт: *", key="upwiz_city", placeholder="Населений пункт")
    a3, a4, a5 = st.columns(3)
    with a3:
        st.text_input("Вулиця", key="upwiz_street", placeholder="Вулиця")
    with a4:
        st.text_input("Будинок", key="upwiz_house", placeholder="Буд.")
    with a5:
        st.text_input("Квартира", key="upwiz_apartment", placeholder="Кв.")

    _up_section_title("Інформація про відправлення")
    st.markdown('<div class="up-parcel-box"><p class="up-parcel-sub">Інформація про місце №1</p></div>', unsafe_allow_html=True)
    p1, p2 = st.columns(2)
    with p1:
        st.number_input("Вага, г: *", min_value=1, max_value=30000, value=500, step=50, key="upwiz_weight_g")
        st.number_input("Ширина, см: *", min_value=0, max_value=200, value=0, step=1, key="upwiz_width_cm")
        st.number_input("Оголошена цінність, грн", min_value=0.0, value=0.0, step=1.0, key="upwiz_declared_uah")
    with p2:
        st.number_input("Найбільша сторона (довжина), см: *", min_value=1, max_value=200, value=30, step=1, key="upwiz_length_cm")
        st.number_input("Висота, см: *", min_value=0, max_value=200, value=0, step=1, key="upwiz_height_cm")
        st.number_input("Післяплата, грн", min_value=0.0, value=0.0, step=1.0, key="upwiz_postpay_uah")
    st.text_area("Додаткова інформація", key="upwiz_description", placeholder="Додаткова інформація", height=80)

    _up_section_title("У разі невручення:")
    f1, f2 = st.columns(2)
    with f1:
        st.radio(
            "Дія",
            ["повернути", "не повертати"],
            key="upwiz_fail_main",
            label_visibility="collapsed",
        )
    with f2:
        st.radio(
            "Послуга повернення",
            ["Базовий", "Пріоритетний"],
            key="upwiz_fail_return_service",
            label_visibility="collapsed",
            disabled=st.session_state.get("upwiz_fail_main") == "не повертати",
        )

    _up_section_title("Додаткові послуги:")
    s1, s2 = st.columns(2)
    with s1:
        st.checkbox("СМС-повідомлення", key="upwiz_sms")
        st.checkbox("Email-повідомлення", key="upwiz_email_notify")
        st.checkbox("Повідомлення про вручення ф. 119", key="upwiz_form119")
        st.checkbox("Опис вкладення", key="upwiz_contents_desc")
    with s2:
        st.checkbox("Зараховувати післяплату на IBAN", key="upwiz_transfer_postpay_iban")
        st.checkbox("Огляд під час вручення", key="upwiz_check_delivery")

    pay1, pay2 = st.columns(2)
    with pay1:
        st.radio(
            "Сплачує плату за відправлення:",
            ["Відправник", "Одержувач"],
            horizontal=True,
            key="upwiz_paid_shipment_who",
            index=0,
        )
    with pay2:
        st.radio(
            "Сплачує плату за пересилання післяплати:",
            ["Одержувач", "Відправник"],
            horizontal=True,
            key="upwiz_paid_postpay_who",
            index=0,
        )
    st.session_state.upwiz_paid_shipment_recipient = (
        st.session_state.get("upwiz_paid_shipment_who") == "Одержувач"
    )
    st.session_state.upwiz_paid_postpay_recipient = (
        st.session_state.get("upwiz_paid_postpay_who") == "Одержувач"
    )

    with st.expander("Розширено: UUID отримувача / JSON"):
        st.text_input(
            "UUID отримувача (якщо вже є в кабінеті)",
            key="upwiz_recipient_uuid",
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        )
        _created_rid = str(st.session_state.get("upwiz_recipient_uuid_created", "")).strip()
        if _created_rid:
            st.caption(f"UUID створено через API (для цієї форми): `{_created_rid}`")
        if st.button("Показати JSON запиту", key="upwiz_preview_json"):
            v_err = _up_validate_wizard_form()
            if v_err:
                st.warning(v_err)
            else:
                rid, r_err = _up_ensure_recipient_uuid()
                if r_err:
                    st.error(r_err)
                else:
                    body, b_err = _up_build_shipment_dict_from_wizard(rid)
                    if b_err:
                        st.error(b_err)
                    else:
                        st.code(_json.dumps(body, indent=2, ensure_ascii=False), language="json")

    st.divider()
    st.markdown("**Після створення ТТН** — додати рядок у Google-таблицю:")
    cph, cco = st.columns(2)
    with cph:
        st.text_input("Телефон у таблицю", key="tab_up_new_phone", placeholder="380…")
    with cco:
        st.text_input("Вартість у таблицю", key="tab_up_new_cost", placeholder="0")

    b_cancel, b_calc, b_create = st.columns(3)
    with b_cancel:
        st.markdown('<div class="up-action-cancel">', unsafe_allow_html=True)
        if st.button("Скасувати", key="upwiz_btn_cancel", use_container_width=True):
            st.session_state.upwiz_form_open = False
            _up_reset_wizard_form()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    with b_calc:
        st.markdown('<div class="up-action-calc">', unsafe_allow_html=True)
        if st.button("Розрахувати", key="upwiz_btn_calc", use_container_width=True):
            v_err = _up_validate_wizard_form()
            if v_err:
                st.error(v_err)
            else:
                rid = _up_get_recipient_uuid()
                body, b_err = _up_build_shipment_dict_from_wizard(rid or None)
                if b_err and not rid:
                    st.session_state.up_calc_preview = None
                    st.warning(f"{b_err} Для розрахунку вкажи UUID отримувача або натисни «Створити» внизу.")
                elif b_err:
                    st.error(b_err)
                else:
                    st.session_state.up_calc_preview = body
                    st.info(
                        "JSON зібрано. Точну вартість Укрпошта повертає після «Створити» (поле deliveryPrice)."
                    )
        st.markdown("</div>", unsafe_allow_html=True)
    with b_create:
        st.markdown('<div class="up-action-create">', unsafe_allow_html=True)
        if st.button("Створити", key="upwiz_btn_create", type="primary", use_container_width=True):
            v_err = _up_validate_wizard_form()
            if v_err:
                st.error(v_err)
            else:
                sid, s_err = _up_ensure_sender_uuid()
                if s_err:
                    st.error(s_err)
                else:
                    rid, r_err = _up_ensure_recipient_uuid()
                    if r_err:
                        st.error(r_err)
                    else:
                        body, b_err = _up_build_shipment_dict_from_wizard(
                            rid, sender_uuid=sid
                        )
                        if b_err:
                            st.error(b_err)
                        else:
                            data, err = up_post_shipment_create(body)
                            if err:
                                st.error(f"Створення ТТН: {err}")
                            else:
                                st.session_state.up_last_create_response = data
                                up_journal_save_response(data)
                                bc_new = _up_barcode_from_create_response(data)
                                if bc_new:
                                    st.session_state.up_journal_active_bc = bc_new
                                price = (
                                    data.get("deliveryPrice")
                                    if isinstance(data, dict)
                                    else None
                                )
                                if price is not None:
                                    st.success(
                                        f"Відправлення створено. Вартість доставки: {price} грн"
                                    )
                                else:
                                    st.success("Відправлення створено.")
                                st.toast("Укрпошта: ТТН створено", icon="✅")
        st.markdown("</div>", unsafe_allow_html=True)

    preview = st.session_state.get("up_calc_preview")
    if preview:
        with st.expander("Попередній JSON (розрахунок)", expanded=False):
            st.json(preview)

    resp = st.session_state.get("up_last_create_response")
    if resp is not None:
        with st.expander("Остання відповідь API", expanded=False):
            st.json(resp)
        bc = _up_barcode_from_create_response(resp)
        if bc:
            if len(bc) == 12 and bc.isdigit():
                bc = "0" + bc
            st.markdown(f"**ТТН:** `{bc}`")
        st.caption("Редагування та друк — у блоці **Журнал ТТН Укрпошти** зверху.")

    if st.button("Додати ТТН у таблицю Orders", key="tab_up_add_row_btn"):
        resp = st.session_state.get("up_last_create_response")
        if not resp:
            st.warning("Спочатку успішно створи відправлення.")
        else:
            bc = _up_barcode_from_create_response(resp)
            if not bc:
                st.error("У відповіді немає barcode — додай ТТН вручну у «Таблиця».")
            else:
                if len(bc) == 12 and bc.isdigit():
                    bc = "0" + bc
                existing = st.session_state.df["ТТН"].astype(str).str.strip().tolist()
                if bc in existing:
                    st.warning("Такий ТТН уже є в таблиці.")
                else:
                    phone_w = utils.clean_phone(str(st.session_state.get("upwiz_phone", "")).strip())
                    phone_t = utils.clean_phone(str(st.session_state.get("tab_up_new_phone", "")).strip())
                    phone = phone_t or phone_w
                    c_w = _up_num_float(st.session_state.get("upwiz_declared_uah", 0))
                    try:
                        c_t = float(
                            str(st.session_state.get("tab_up_new_cost", "")).replace(",", ".").strip() or -1
                        )
                    except Exception:
                        c_t = -1.0
                    cost_v = c_t if c_t >= 0 else c_w
                    postpay = _up_num_float(st.session_state.get("upwiz_postpay_uah", 0))
                    if postpay >= 1 and cost_v <= 0:
                        cost_v = postpay
                    st.session_state.df.loc[len(st.session_state.df)] = {
                        "ТТН": bc,
                        "Служба": "УП",
                        "Статус": "Нове",
                        "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Телефон": phone,
                        "Вартість": cost_v,
                        "Номер накладної": "",
                        "Чек": "",
                        "Повідомлення": "",
                        "Статус СМС": "",
                        "Статус Нагадування": "",
                        "Дія": False,
                    }
                    st.session_state.df = ensure_messages_exist(st.session_state.df)
                    if sheets.save_manual(st.session_state.df):
                        audit_log("уп_нова_ттн", bc[:40], _json.dumps(resp, ensure_ascii=False)[:200])
                        st.toast("Рядок додано в Google Sheet", icon="✅")
                    else:
                        st.error("Не вдалося зберегти таблицю.")


# --- MEEST: SELENIUM (ПРАВИЛЬНА ВЕРСІЯ ДЛЯ СЕРВЕРА) ---
def get_meest_status(ttn):
    chrome_options = Options()
    
    # Налаштування для сервера (ОБОВ'ЯЗКОВО ТАКІ)
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Маскування
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Шлях до Chromium (встановлюється з packages.txt)
    chrome_options.binary_location = "/usr/bin/chromium"
    
    driver = None
    status_result = "Не знайдено"
    
    try:
        # Вказуємо шлях до драйвера
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        url = f"https://meestposhta.com.ua/search?query={ttn}"
        driver.get(url)
        
        time.sleep(8) 
        
        content = driver.execute_script("return document.body.innerText")
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        
        for i in range(len(lines)):
            current_line = lines[i]
            
            if "Поточний статус:" in current_line or "Статус:" in current_line:
                if len(current_line) > 17:
                    status_result = current_line.replace("Поточний статус:", "").strip()
                elif i + 1 < len(lines):
                    status_result = lines[i+1]
                else:
                    status_result = current_line
                break
                
            if any(word in current_line for word in ["Відправлено", "Прибуло", "Митне", "оформлення", "отримано", "у відділенні"]):
                status_result = current_line
                break
                
        res_low = status_result.lower()
        if "отримано" in res_low: return "Отримано", "", "", 0.0
        if "у відділенні" in res_low: return "У відділенні", "", "", 0.0
        if "в дорозі" in res_low: return "В дорозі", "", "", 0.0
        
        return status_result[:60], "", "", 0.0

    except Exception as e:
        return f"Error: {str(e)[:50]}", "", "", 0.0
    finally:
        if driver:
            driver.quit()

def fetch_new_orders_meest(existing_ttns):
    return []

# ==========================================
# 📊 ЛОГІКА ДАНИХ
# ==========================================

def ensure_columns(df):
    for c in config.COLS:
        if c not in df.columns:
            if c == "Дія": df[c] = False
            elif c == "Вартість": df[c] = 0.0
            else: df[c] = ""
    return df

def restore_leading_zero(val):
    s = str(val).replace("'", "").strip()
    if len(s) == 12 and s.isdigit(): return "0" + s
    return s


def normalize_table_column_order(order):
    if not order:
        return list(config.COLS)
    seen = []
    for c in order:
        if c in config.COLS and c not in seen:
            seen.append(c)
    for c in config.COLS:
        if c not in seen:
            seen.append(c)
    return seen


def get_table_column_order():
    if "table_column_order" in st.session_state:
        return normalize_table_column_order(st.session_state.table_column_order)
    user = str(st.session_state.get("auth_user", "")).strip()
    loaded = sheets.load_table_column_order(user) if user else None
    order = normalize_table_column_order(loaded or config.COLS)
    st.session_state.table_column_order = order
    return order


def persist_table_column_order(order):
    order = normalize_table_column_order(order)
    st.session_state.table_column_order = order
    user = str(st.session_state.get("auth_user", "")).strip()
    if user:
        sheets.save_table_column_order(user, order)
    return order


def apply_table_column_order(df, order=None):
    order = order or get_table_column_order()
    cols = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    return df[cols + rest]


def _coalesce_edited_table(editor_value, base: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """Повертає повну таблицю з data_editor (return value або session_state з edited_rows)."""
    base = (base if base is not None else st.session_state.get("df")).copy()
    if editor_value is None:
        return None
    if isinstance(editor_value, pd.DataFrame):
        return editor_value.copy()
    if not isinstance(editor_value, dict):
        return None
    df = base.copy()
    for idx, changes in (editor_value.get("edited_rows") or {}).items():
        i = int(idx)
        if i not in df.index:
            continue
        for col, val in (changes or {}).items():
            if col in df.columns:
                df.at[i, col] = val
    for idx in sorted((editor_value.get("deleted_rows") or []), reverse=True):
        i = int(idx)
        if i in df.index:
            df = df.drop(index=i)
    added = editor_value.get("added_rows") or []
    if added:
        df = pd.concat([df, pd.DataFrame(added)], ignore_index=True)
    return df.reset_index(drop=True)


def _prepare_table_df_for_save(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df.copy())
    df = apply_table_column_order(df)
    if "ТТН" in df.columns:
        df["ТТН"] = df["ТТН"].apply(restore_leading_zero)
    text_cols = [
        "ТТН",
        "Служба",
        "Статус",
        "Дата",
        "Телефон",
        "Чек",
        "Повідомлення",
        "Статус СМС",
        "Статус Нагадування",
        "Номер накладної",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", "").str.strip()
    if "Номер накладної" in df.columns:
        df["Номер накладної"] = df["Номер накладної"].apply(utils.normalize_invoice_number)
    if "Вартість" in df.columns:
        df["Вартість"] = (
            df["Вартість"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace(r"\s+", "", regex=True)
        )
        df["Вартість"] = pd.to_numeric(df["Вартість"], errors="coerce").fillna(0.0)
    if "Дія" in df.columns:
        df["Дія"] = (
            df["Дія"]
            .replace({"True": True, "False": False, "": False, "FALSE": False, "TRUE": True, 1: True, 0: False})
            .infer_objects(copy=False)
            .fillna(False)
            .astype(bool)
        )
    if "Дата" in df.columns:
        df["Дата"] = df["Дата"].apply(utils.normalize_date)
    return ensure_messages_exist(df)


def _table_data_changed(candidate: pd.DataFrame, baseline: pd.DataFrame) -> bool:
    a = _prepare_table_df_for_save(candidate)
    b = _prepare_table_df_for_save(baseline)
    if len(a) != len(b):
        return True
    cols = [c for c in config.COLS if c in a.columns and c in b.columns]
    a = a[cols].reset_index(drop=True)
    b = b[cols].reset_index(drop=True)
    for col in cols:
        if col == "Вартість":
            if not pd.to_numeric(a[col], errors="coerce").fillna(0).equals(
                pd.to_numeric(b[col], errors="coerce").fillna(0)
            ):
                return True
        elif col == "Дія":
            if not a[col].astype(bool).equals(b[col].astype(bool)):
                return True
        else:
            if not a[col].astype(str).equals(b[col].astype(str)):
                return True
    return False


def _resolve_row_index(df: pd.DataFrame, pos: int):
    """Індекс рядка в df за позицією в таблиці (0, 1, 2…)."""
    if pos in df.index:
        return pos
    if 0 <= pos < len(df):
        return df.index[pos]
    return None


def _normalize_table_cell(col: str, val):
    if val is None:
        return ""
    if col == "ТТН":
        return restore_leading_zero(str(val))
    if col == "Номер накладної":
        return utils.normalize_invoice_number(str(val))
    if col == "Вартість":
        s = str(val).replace(",", ".").strip()
        return float(pd.to_numeric(s, errors="coerce") or 0.0)
    if col == "Дія":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "так")
    if col == "Дата":
        return utils.normalize_date(str(val))
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def _refresh_row_message_if_needed(df: pd.DataFrame, row_key) -> bool:
    """Оновлює «Повідомлення» для одного рядка після зміни чека."""
    if row_key is None or "Чек" not in df.columns or "Повідомлення" not in df.columns:
        return False
    row = df.loc[row_key]
    if utils.row_receipt_not_required(row):
        return False
    if str(row.get("Статус СМС", "")).strip() == "Отправлено":
        return False
    link = str(row.get("Чек", "")).strip()
    if not link or len(link) < 5 or link.lower() == "nan":
        return False
    if not utils.status_has_any(str(row.get("Статус", "")).lower(), utils.DELIVERED_STATUS_KEYWORDS):
        return False
    msg_val = str(row.get("Повідомлення", "")).strip()
    if len(msg_val) > 5 and msg_val.lower() != "nan" and link in msg_val:
        return False
    new_msg = _CHECK_SMS_TEXT.format(link=link)
    df.at[row_key, "Повідомлення"] = new_msg
    if "Статус СМС" in df.columns and len(str(row.get("Телефон", "")).strip()) > 5:
        df.at[row_key, "Статус СМС"] = "Не отправлено"
    return True


def _tab2_display_dataframe(col_order):
    """Таблиця з session_state (після autosave значення вже в тому ж рядку)."""
    return apply_table_column_order(st.session_state.df, col_order)


def _render_tab2_scroll_preserve():
    """Зберігає прокрутку сторінки між rerun; ніколи не викликає scrollTo(0,0)."""
    components.html(
        """
<script>
(function () {
  const win = window.parent;
  const KEY = "logistic_tab2_page_y";
  try {
    const y = parseInt(sessionStorage.getItem(KEY) || "0", 10) || 0;
    if (y > 40) win.scrollTo(0, y);
  } catch (e) {}
  if (!win._logisticTab2Preserve) {
    win._logisticTab2Preserve = true;
    win.addEventListener(
      "scroll",
      function () {
        if ((win.scrollY || 0) > 40) {
          try { sessionStorage.setItem(KEY, String(win.scrollY)); } catch (e) {}
        }
      },
      { passive: true }
    );
  }
})();
</script>
        """,
        height=0,
        width=0,
    )


def _cell_values_equal(col: str, a, b) -> bool:
    return str(_normalize_table_cell(col, a)) == str(_normalize_table_cell(col, b))


def _tab2_editor_baseline() -> pd.DataFrame:
    b = st.session_state.get("_tab2_editor_baseline")
    if b is None or not isinstance(b, pd.DataFrame):
        b = st.session_state.df.copy()
        st.session_state._tab2_editor_baseline = b
    return b


def _tab2_reset_baseline():
    st.session_state._tab2_editor_baseline = st.session_state.df.copy()


def _edited_rows_from_main(main_state) -> dict:
    if not isinstance(main_state, dict):
        return {}
    return {int(k): dict(v) for k, v in (main_state.get("edited_rows") or {}).items()}


def _filter_rows_vs_baseline(edited_rows: dict) -> dict:
    if not edited_rows:
        return {}
    base = apply_table_column_order(_tab2_editor_baseline()).reset_index(drop=True)
    out = {}
    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        if row_pos < 0 or row_pos >= len(base):
            continue
        real = {}
        for col, val in (changes or {}).items():
            if col not in base.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, val, base.at[row_pos, col]):
                real[col] = val
        if real:
            out[row_pos] = real
    return out


def _editor_df_from_value(value) -> pd.DataFrame | None:
    if isinstance(value, pd.DataFrame):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, pd.DataFrame):
        return data
    return None


def _diff_edited_rows(baseline: pd.DataFrame, current: pd.DataFrame) -> dict:
    """Порівняння таблиці з редактором і baseline — зміни з останнього збереження."""
    b = apply_table_column_order(baseline).reset_index(drop=True)
    c = apply_table_column_order(current).reset_index(drop=True)
    n = min(len(b), len(c))
    edited_rows = {}
    for i in range(n):
        changes = {}
        for col in config.COLS:
            if col not in b.columns or col not in c.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, b.at[i, col], c.at[i, col]):
                changes[col] = c.at[i, col]
        if changes:
            edited_rows[i] = changes
    return edited_rows


def _apply_partial_edits(edited_rows: dict) -> bool:
    if not edited_rows:
        return False
    df = st.session_state.df
    extra_sheet_cells = []
    norm_for_sheet = {}

    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        row_key = _resolve_row_index(df, row_pos)
        if row_key is None:
            continue
        norm_for_sheet[row_pos] = {}
        for col, val in (changes or {}).items():
            if col not in df.columns or col == "Дія":
                continue
            norm = _normalize_table_cell(col, val)
            df.at[row_key, col] = norm
            norm_for_sheet[row_pos][col] = norm
        if "Чек" in (changes or {}) and _refresh_row_message_if_needed(df, row_key):
            extra_sheet_cells.append(
                (row_pos, "Повідомлення", df.at[row_key, "Повідомлення"])
            )
            if "Статус СМС" in df.columns:
                extra_sheet_cells.append(
                    (row_pos, "Статус СМС", df.at[row_key, "Статус СМС"])
                )

    if not sheets.update_table_cell_edits(norm_for_sheet, extra_sheet_cells):
        return False
    _tab2_reset_baseline()
    return True


def _autosave_table_edits_partial(editor_value=None, edited_df=None) -> bool:
    """Зберігає лише змінені комірки."""
    if isinstance(editor_value, dict) and (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        return _autosave_table_if_changed(editor_value, show_toast=False)

    baseline = _tab2_editor_baseline()
    from_main = _edited_rows_from_main(editor_value)
    current = _editor_df_from_value(edited_df)
    from_diff = _diff_edited_rows(baseline, current) if current is not None else {}
    merged = dict(from_main)
    for row, cols in from_diff.items():
        merged.setdefault(int(row), {}).update(cols)
    edited_rows = _filter_rows_vs_baseline(merged)

    return _apply_partial_edits(edited_rows)


def _autosave_table_from_editor(edited_df) -> bool:
    """Fallback autosave після data_editor."""
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)
    return _autosave_table_edits_partial(editor_value=main, edited_df=edited_df)


def _autosave_table_if_changed(editor_value=None, *, show_toast: bool = False) -> bool:
    if isinstance(editor_value, dict) and editor_value.get("edited_rows") and not (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        if _autosave_table_edits_partial(editor_value):
            if show_toast:
                st.session_state._tab2_autosave_ok = True
            return True
        return False
    edited = _coalesce_edited_table(editor_value)
    if edited is None:
        return False
    prepared = _prepare_table_df_for_save(edited)
    if not _table_data_changed(prepared, st.session_state.df):
        return False
    if sheets.save_manual(prepared, clear_cache=False, merge_session=True):
        if show_toast:
            st.session_state._tab2_autosave_ok = True
        return True
    return False


def _try_sync_column_order_from_editor(editor_df: pd.DataFrame | None = None):
    """Порядок колонок — лише drag у dict-стані (не з return DataFrame — інакше «оновлює все»)."""
    main = st.session_state.get("main")
    if not isinstance(main, dict):
        return
    cols = [str(c) for c in (main.get("column_order") or []) if c in config.COLS]
    if not cols:
        return
    norm = normalize_table_column_order(cols)
    if norm != get_table_column_order():
        persist_table_column_order(norm)
        st.session_state.df = apply_table_column_order(st.session_state.df, norm)


def load_data():
    if 'df' not in st.session_state:
        df = sheets.load_data_from_gsheets()
        if "Номер ТТН" in df.columns: df = df.rename(columns={"Номер ТТН": "ТТН", "Статус НП": "Статус"})
        df = ensure_columns(df)
        df = apply_table_column_order(df, get_table_column_order())
        # Залишаємо leading_zero
        df['ТТН'] = df['ТТН'].apply(restore_leading_zero)
        
        text_cols = ["ТТН", "Служба", "Статус", "Дата", "Телефон", "Чек", "Повідомлення", "Статус СМС", "Статус Нагадування", "Номер накладної"]
        for col in text_cols:
            df[col] = df[col].astype(str).replace('nan', '')

        df["Номер накладної"] = df["Номер накладної"].apply(utils.normalize_invoice_number)

        if 'Вартість' in df.columns:
            df['Вартість'] = df['Вартість'].astype(str).str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
            df['Вартість'] = pd.to_numeric(df['Вартість'], errors='coerce').fillna(0.0)

        df['Дія'] = df['Дія'].replace({'True': True, 'False': False, '': False, 'FALSE': False, 'TRUE': True, 1: True, 0: False}).infer_objects(copy=False).fillna(False).astype(bool)
        df['Дата'] = df['Дата'].apply(utils.normalize_date)
        
        if utils.apply_no_receipt_auto_sent(df):
            sheets.save_manual(df)
        df = ensure_messages_exist(df)
        st.session_state.df = df
    else:
        st.session_state.df = ensure_columns(st.session_state.df)
        if "Номер накладної" in st.session_state.df.columns:
            st.session_state.df["Номер накладної"] = st.session_state.df["Номер накладної"].apply(
                utils.normalize_invoice_number
            )
        if utils.apply_no_receipt_auto_sent(st.session_state.df):
            sheets.save_manual(st.session_state.df)

def run_auto_linking(silent=False):
    """Автопідбір чека з Checkbox: **лише** дві умови — без інших евристик.

    1. Сума чека після округлення до копійки **дорівнює** «Вартість» рядка (так само до копійки).
    2. |Дата відправлення в рядку − дата/час чека| ≤ **120 с** (2 хв).

    Серед допустимих пар вибір за **найменшою** різницею в часі; один URL чека — максимум один рядок.
    """
    # Суворо 2 хвилини; сума — тільки точний збіг у гривнях з копійками (round 2), не «майже».
    max_dt_sec = 2 * 60

    checkbox_df = fetch_checkbox_archive()
    if checkbox_df is None or checkbox_df.empty:
        return 0
    checkbox_df = checkbox_df.copy()
    checkbox_df["dt_obj"] = pd.to_datetime(checkbox_df["Дата"], errors="coerce")
    sums = pd.to_numeric(checkbox_df["Сума"], errors="coerce").round(2)

    df = st.session_state.df.copy()
    for col in df.columns:
        df[col] = df[col].astype(object)

    used_links = set()
    for _, r in df.iterrows():
        lk = str(r.get("Чек", "")).strip()
        if lk and len(lk) > 5 and lk.lower() != "nan":
            used_links.add(lk)

    def _link_row_meta(row):
        try:
            c = float(str(row.get("Вартість", 0)).replace(",", ".").strip())
            ds = str(row.get("Дата", "")).strip()
            if c <= 0 or len(ds) < 10:
                return None
            return round(c, 2), pd.to_datetime(ds)
        except Exception:
            return None

    to_link = []
    for idx, row in df.iterrows():
        cur = str(row.get("Чек", "")).strip()
        if cur and len(cur) > 5 and cur.lower() != "nan":
            continue
        meta = _link_row_meta(row)
        if not meta:
            continue
        cost_kop, np_dt = meta
        to_link.append((idx, np_dt, cost_kop))

    # Усі допустимі пари (рядок, чек): та сама сума до копійки + Δчас ≤ 2 хв; далі — за зростанням Δ
    edges = []
    for idx, np_dt, cost_kop in to_link:
        cand_mask = (sums == cost_kop) & sums.notna()
        for _, check in checkbox_df.loc[cand_mask].iterrows():
            link = str(check.get("Посилання", "")).strip()
            if not link or link in used_links:
                continue
            cdt = check["dt_obj"]
            if pd.isna(cdt):
                continue
            delta_sec = abs((np_dt - cdt).total_seconds())
            if delta_sec > max_dt_sec:
                continue
            edges.append((delta_sec, idx, link))

    edges.sort(key=lambda e: e[0])
    rows_done = set()
    matches = 0
    for delta_sec, idx, link in edges:
        if idx in rows_done:
            continue
        if link in used_links:
            continue
        df.at[idx, "Чек"] = link
        rows_done.add(idx)
        used_links.add(link)
        matches += 1
        try:
            sc_auto = float(
                str(df.at[idx, "Вартість"]).replace(",", ".").strip()
            )
        except Exception:
            sc_auto = None
        rs_auto = None
        try:
            mchk = checkbox_df[
                checkbox_df["Посилання"].astype(str).str.strip() == str(link).strip()
            ]
            if not mchk.empty:
                rs_auto = float(
                    str(mchk.iloc[0].get("Сума", 0)).replace(",", ".").strip() or 0
                )
        except Exception:
            pass
        audit_log(
            "чек_авто",
            str(df.at[idx, "ТТН"]).strip()[:40],
            link[:120],
            ship_cost=sc_auto,
            receipt_sum=rs_auto,
        )

    if matches > 0:
        st.session_state.df = df
        if sheets.save_manual(df):
            if not silent:
                st.success(f"✅ Знайдено {matches} чеків!")
                time.sleep(1.5)
                st.rerun()
    return matches

def process_status_updates(show_ui=True, services=None):
    """Оновлення статусів у таблиці.

    Parameters
    ----------
    show_ui : bool
        Показати progress і підпис поточної ТТН.
    services : None | tuple[str, ...]
        ``None`` — усі служби (НП, УП, Meest). Інакше лише вказані, напр.
        ``("НП", "УП")`` для швидкого режиму без Selenium Meest.
    """
    allowed = None if services is None else frozenset(str(s) for s in services)

    work_df = st.session_state.df.copy()
    # Переводимо колонки в object, щоб уникнути TypeError при присвоєнні
    for col in work_df.columns:
        work_df[col] = work_df[col].astype(object)
    count_sms = 0
    progress_bar = st.progress(0) if show_ui else None
    status_text = st.empty() if show_ui else None

    for i, row in work_df.iterrows():
        # Для Meest (721-...) не застосовуємо чистку, щоб не ламати пошук
        raw_ttn = str(work_df.loc[i, 'ТТН']).strip()
        svc = row['Служба']
        if not svc or svc == "Інше": svc = utils.identify_service(raw_ttn)
        
        if svc == "Meest":
            ttn = raw_ttn 
        else:
            ttn = utils.clean_ttn(raw_ttn)
        
        work_df.loc[i, 'ТТН'] = ttn 
        work_df.loc[i, 'Служба'] = svc

    rows_list = list(work_df.iterrows())
    total = len(rows_list)
    # Batch НП checks (лише якщо НП у вибраних службах)
    if allowed is None or "НП" in allowed:
        np_ttns = [
            str(row["ТТН"])
            for _, row in work_df.iterrows()
            if row["Служба"] == "НП" and len(str(row["ТТН"])) > 5
        ]
        np_statuses = get_np_statuses_bulk(np_ttns) if np_ttns else {}
    else:
        np_statuses = {}

    for step, (i, row) in enumerate(rows_list):
        if show_ui:
            progress_bar.progress((step + 1) / max(total, 1))
        ttn = str(work_df.loc[i, 'ТТН'])
        if len(ttn) < 5: continue
        
        svc = work_df.loc[i, 'Служба']
        current = str(work_df.loc[i, 'Статус']).lower()
        
        s, d, cost, phone, extra = "", None, 0.0, "", ""
        
        if (
            svc == "НП"
            and (allowed is None or "НП" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if ttn in np_statuses:
                info = np_statuses[ttn]
                s = info.get('Status', '')
                cost = info.get('Cost', 0.0)
                phone = info.get('Phone', '')
                invoice = info.get('ClientBarcode', '')
                if invoice:
                    work_df.loc[i, 'Номер накладної'] = utils.normalize_invoice_number(invoice)
        
        elif (
            svc == "УП"
            and (allowed is None or "УП" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if show_ui: status_text.text(f"Перевірка УП: {ttn}")
            s, d, cost, phone, extra = get_up_status_smart(ttn)
            if phone and len(str(work_df.loc[i, 'Телефон'])) < 10:
                work_df.loc[i, 'Телефон'] = str(phone)
        
        elif (
            svc == "Meest"
            and (allowed is None or "Meest" in allowed)
            and not utils.status_has_any(current, utils.STOP_TRACKING_STATUS_KEYWORDS)
        ):
            if show_ui: status_text.text(f"Перевірка Meest: {ttn}")
            s, p, d, cost = get_meest_status(ttn)
            
        if s and not s.startswith("Error") and s != "Не знайдено":
            work_df.loc[i, 'Статус'] = str(s)
        if d: work_df.loc[i, 'Дата'] = str(d)
        try:
            cost_value = float(str(cost).replace(',', '.').strip())
        except Exception:
            cost_value = 0.0
        if cost_value > 0:
            work_df.loc[i, 'Вартість'] = cost_value
        if phone and len(str(work_df.loc[i, 'Телефон'])) < 10:
            work_df.loc[i, 'Телефон'] = str(phone)
        
    utils.apply_no_receipt_auto_sent(work_df)
    work_df = ensure_messages_exist(work_df)
    st.session_state.df = work_df
    saved = sheets.save_manual(st.session_state.df)
    if show_ui: status_text.empty(); progress_bar.empty()
    return count_sms, saved

st.markdown(
    """<style>
button[data-baseweb="tab"] { font-size: 24px !important; font-weight: 700 !important; }
div.stButton > button { font-size: 16px !important; font-weight: 500 !important; }
section[data-testid="stSidebar"] div.stButton > button { width: 100% !important; border: 1px solid #4CAF50 !important; }
/* Червона кнопка «Вибрати чек зі списку» (черга видачі чека) */
button[data-testid="baseButton-secondary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="baseButton-primary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="stBaseButton-secondary"][aria-label*="Вибрати чек зі списку"],
button[data-testid="stBaseButton-primary"][aria-label*="Вибрати чек зі списку"] {
  background-color: #c62828 !important;
  color: #ffffff !important;
  border: 1px solid #8e0000 !important;
}
button[data-testid="baseButton-secondary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="baseButton-primary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="stBaseButton-secondary"][aria-label*="Вибрати чек зі списку"]:hover,
button[data-testid="stBaseButton-primary"][aria-label*="Вибрати чек зі списку"]:hover {
  background-color: #b71c1c !important;
  border-color: #5c0000 !important;
}
</style>""",
    unsafe_allow_html=True,
)

def render_smart_buttons(phone, message, row_key=None):
    if not phone or len(str(phone)) < 10: st.caption("Невірний телефон"); return
    raw_phone = str(phone); digits = ''.join(filter(str.isdigit, raw_phone))
    if len(digits) == 10 and digits.startswith('0'): digits = '38' + digits
    if len(digits) != 12: st.caption(f"Формат? {raw_phone}"); return
    msg_safe = str(message).replace("\\", "\\\\").replace('\n', '\\n').replace('\r', '').replace("'", "\\'")
    token_raw = f"{digits}_{row_key if row_key is not None else 'default'}"
    token = re.sub(r"[^0-9A-Za-z_]", "_", token_raw)
    js_code = f"""<script>function clickHandler_{token}(type) {{ const text = '{msg_safe}'; const url = type === 'viber' ? 'viber://chat?number=%2B{digits}' : 'sms:+{digits}'; const el = document.createElement('textarea'); el.value = text; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el); const link = document.createElement('a'); link.href = url; document.body.appendChild(link); link.click(); document.body.removeChild(link); }}</script><div style="display: flex; flex-direction: column; gap: 8px;"><button onclick="clickHandler_{token}('viber')" style="background-color: #7360f2; color: white; border: none; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">💬 Viber</button><button onclick="clickHandler_{token}('sms')" style="background-color: #f0f2f6; color: #31333F; border: 1px solid #ccc; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">📩 SMS</button></div>"""
    st.components.v1.html(js_code, height=100)


def render_copyable_invoice(invoice_num, row_key):
    inv = utils.normalize_invoice_number(invoice_num)
    if not inv or inv.lower() == 'nan':
        return
    inv_safe = html.escape(inv).replace("\\", "\\\\").replace("'", "\\'")
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"invoice_{row_key}")
    js_code = f"""
<script>
function showCopied_{token}() {{
  const el = document.getElementById('copied_{token}');
  if (!el) return;
  el.style.opacity = '1';
  setTimeout(() => {{ el.style.opacity = '0'; }}, 1200);
}}
function copyInvoice_{token}() {{
  const text = '{inv_safe}';
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text);
    showCopied_{token}();
    return;
  }}
  const el = document.createElement('textarea');
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  showCopied_{token}();
}}
</script>
<div style="margin-top: 4px; display: flex; align-items: center; gap: 8px;">
  <button onclick="copyInvoice_{token}()"
          title="Натисніть, щоб скопіювати номер"
          style="background: transparent; border: none; color: #1f77b4; cursor: pointer; padding: 0; font: inherit; text-decoration: underline; white-space: nowrap; line-height: 1.35;">
    📄 Накладна: {inv_safe}
  </button>
  <span id="copied_{token}" style="opacity: 0; transition: opacity .2s ease; color: #2e7d32; font-size: 13px; font-weight: 600;">✅ Скопійовано</span>
</div>
"""
    st.components.v1.html(js_code, height=42)


_CHECKBOX_RECEIPT_HOST = "check.checkbox.ua/"
_CHECK_SMS_TEXT = "Magazin Alius. Vash chek: {link}"


def tab1_default_sms_text(row) -> str:
    """Текст СМС: колонка «Чек» — джерело правди; без неї не показуємо «леві» URL з «Повідомлення»."""
    if utils.row_receipt_not_required(row):
        return ""
    msg = str(row.get("Повідомлення", "")).strip()
    link = str(row.get("Чек", "")).strip()
    has_link = link and len(link) > 5 and link.lower() != "nan"
    if has_link:
        if len(msg) > 5 and msg.lower() != "nan" and link in msg:
            return msg
        return _CHECK_SMS_TEXT.format(link=link)
    if len(msg) > 5 and msg.lower() != "nan":
        if _CHECKBOX_RECEIPT_HOST in msg.lower():
            return ""
        return msg
    return ""


def tab1_row_widget_id(row) -> str:
    """Стабільний id для ключів Streamlit (індекс DataFrame змінюється після reset_index)."""
    raw = f"{str(row.get('ТТН', '')).strip()}|{str(row.get('Телефон', '')).strip()}"
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _dataframe_row_pos(df: pd.DataFrame, idx) -> int:
    try:
        loc = df.index.get_loc(idx)
        if isinstance(loc, slice):
            return int(loc.start)
        if hasattr(loc, "__iter__"):
            return int(list(loc)[0])
        return int(loc)
    except Exception:
        return int(idx)


def _tab1_sms_text_for_send(row) -> str:
    """Текст для TurboSMS: «Повідомлення» або шаблон з колонки «Чек»."""
    txt = str(row.get("Повідомлення", "")).strip()
    if len(txt) <= 5 or txt.lower() == "nan":
        txt = tab1_default_sms_text(row)
    else:
        link = str(row.get("Чек", "")).strip()
        if link and link not in txt:
            filled = tab1_default_sms_text(row)
            if filled:
                txt = filled
    return txt.strip()


def _tab1_ready_for_turbosms(row) -> bool:
    if utils.row_receipt_not_required(row):
        return False
    chk = str(row.get("Чек", "")).strip()
    if not chk or len(chk) < 5 or chk.lower() == "nan":
        return False
    if len(_tab1_sms_text_for_send(row)) < 2:
        return False
    ph = utils.clean_phone(row.get("Телефон"))
    return len(ph) == 12 and ph.startswith("380")


def _tab1_send_turbosms_row(idx, row) -> tuple[bool, str]:
    """Одна відправка TurboSMS + журнал + «Отправлено»."""
    txt = _tab1_sms_text_for_send(row)
    st.session_state.df.at[idx, "Повідомлення"] = txt
    ok, mid, terr = utils.turbosms_send(row["Телефон"], txt)
    if not ok:
        return False, terr or "Не вдалося надіслати SMS"
    detail = str(st.session_state.df.at[idx, "Чек"]).strip()[:120]
    if mid:
        detail = f"{detail} · id={mid}" if detail else f"id={mid}"
    try:
        sc_t = float(str(row.get("Вартість", 0)).replace(",", ".").strip() or 0)
    except Exception:
        sc_t = None
    audit_log(
        "смс_turbosms",
        str(row.get("ТТН", "")).strip()[:40],
        detail,
        ship_cost=sc_t,
        receipt_sum=None,
    )
    _tab1_mark_done(idx, row)
    return True, ""


def _tab1_bulk_send_turbosms(ready_rows: list) -> tuple[int, list]:
    """ready_rows: [(idx, row, text), ...]. Повертає (успішно, [(ttn, err), ...])."""
    ok_count = 0
    errors = []
    for idx, row, txt in ready_rows:
        st.session_state.df.at[idx, "Повідомлення"] = txt
        ok, mid, terr = utils.turbosms_send(row["Телефон"], txt)
        ttn = str(row.get("ТТН", "")).strip()[:40]
        if not ok:
            errors.append((ttn, terr or "Помилка TurboSMS"))
            continue
        detail = str(st.session_state.df.at[idx, "Чек"]).strip()[:120]
        if mid:
            detail = f"{detail} · id={mid}" if detail else f"id={mid}"
        try:
            sc_t = float(str(row.get("Вартість", 0)).replace(",", ".").strip() or 0)
        except Exception:
            sc_t = None
        audit_log("смс_turbosms", ttn, detail, ship_cost=sc_t, receipt_sum=None)
        st.session_state.df.at[idx, "Статус СМС"] = "Отправлено"
        ok_count += 1
        time.sleep(0.35)
    if ok_count:
        sheets.save_manual(st.session_state.df)
    return ok_count, errors


def _tab1_mark_done(idx, row) -> None:
    """Миттєво прибрати з черги; Google + журнал — у фоні (не чекати ~5 с API)."""
    st.session_state.df.at[idx, "Статус СМС"] = "Отправлено"
    row_pos = _dataframe_row_pos(st.session_state.df, idx)
    chk = str(st.session_state.df.at[idx, "Чек"]).strip()
    msg = str(st.session_state.df.at[idx, "Повідомлення"]).strip()
    cells = {row_pos: {"Статус СМС": "Отправлено"}}
    if msg and msg.lower() != "nan":
        cells[row_pos]["Повідомлення"] = msg
    if chk and len(chk) > 5 and chk.lower() != "nan":
        cells[row_pos]["Чек"] = chk

    try:
        sc_done = float(
            str(st.session_state.df.at[idx, "Вартість"]).replace(",", ".").strip()
        )
    except Exception:
        sc_done = None
    if utils.row_receipt_not_required(row):
        detail = "ЧЕК НЕ ПОТРІБЕН (*)"
    else:
        detail = chk[:120] if chk else "(без посилання на чек)"
    ttn = str(row.get("ТТН", "")).strip()[:40]
    cells_copy = {k: dict(v) for k, v in cells.items()}

    def _persist_async():
        try:
            if not sheets.update_table_cell_edits(cells_copy, silent=True):
                st.session_state["_tab1_save_failed"] = ttn
            audit_log("смс_готово", ttn, detail, ship_cost=sc_done, receipt_sum=None)
        except Exception:
            st.session_state["_tab1_save_failed"] = ttn

    threading.Thread(target=_persist_async, daemon=True).start()


st.title("Alius Checkbox")
load_data()

if 'auto_refresh' not in st.session_state: st.session_state.auto_refresh = False
if 'last_status_update' not in st.session_state: st.session_state.last_status_update = 0
if '_deferred_save' not in st.session_state: st.session_state._deferred_save = False
st.sidebar.toggle("🔄 Авто-пошук (ВКЛ/ВИКЛ)", key="auto_refresh")

if st.session_state.auto_refresh:
    with st.spinner("⏳ Авто: Пошук нових..."):
        st.cache_data.clear() 
        existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
        n_np = fetch_new_orders_np(existing)
        n_up = fetch_new_orders_up(existing)
        n_meest = fetch_new_orders_meest(existing)
        all_new = n_np + n_up + n_meest
        if all_new:
            new_df = pd.DataFrame(all_new)
            for c in config.COLS:
                if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
            st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
            sheets.save_manual(st.session_state.df)
            
            # Автопідбір чеків для щойно доданих відправлень
            run_auto_linking(silent=True)

    sms_count = 0
    if time.time() - st.session_state.last_status_update > 300:
        with st.spinner("⏳ Авто: Глибока перевірка статусів..."):
            # Без Meest: Selenium на кожну ТТН дуже повільний у фоні.
            sms_count, _ = process_status_updates(
                show_ui=False, services=("НП", "УП")
            )
            run_auto_linking(silent=True)
            st.session_state.last_status_update = time.time()
    msg = []
    if all_new: msg.append(f"+{len(all_new)} нових")
    if sms_count > 0: msg.append(f"+{sms_count} SMS")
    if msg:
        st.toast(f"Оновлено: {', '.join(msg)}", icon="🔔")
        ts = int(time.time()); components.html(f"""<audio autoplay><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3?t={ts}"></audio>""", height=0)
    time.sleep(60); st.rerun()

with st.sidebar:
    st.header("🎮 Пульт")
    
    # Імпорт файлу з фільтрацією за статусом
    with st.expander("📂 Імпорт з файлу", expanded=False):
        st.caption(
            "Формат: колонка **A** ТТН, **B** телефон, **C** вартість, **D** накладна. Перший рядок файлу — заголовки."
        )
        uploaded_file = st.file_uploader(
            "Оберіть файл (XLSX/CSV)", type=["xlsx", "csv"], key="import_uploader"
        )
        if uploaded_file:
            if st.button("📥 Завантажити файл"):
                try:
                    df_upload = utils.read_uploaded_table(
                        uploaded_file,
                        min_columns=1,
                        require_non_empty=True,
                        csv_encodings=['utf-8', 'cp1251', 'latin1'],
                        csv_separators=[',', ';', '\t', '|']
                    )
                    if df_upload is None:
                        st.error("❌ Не вдалось прочитати файл імпорту. Перевірте формат CSV/XLSX.")
                        st.info("💡 Спробуйте: \n1. Зберегти файл як UTF-8 \n2. Переконайтесь що роздільник `,` або `;` \n3. Завантажити як XLSX")
                        st.stop()
                    
                    # 1. Фіксований формат імпорту:
                    #    кол.A ТТН, кол.B Телефон, кол.C Вартість, кол.D Номер накладної
                    #    У Excel/CSV: перший рядок файлу = заголовки колонок (pandas не показує його як рядок даних),
                    #    перший рядок даних у файлі = другий візуально рядок → це df.iloc[0].
                    if len(df_upload.columns) < 4:
                        st.error("❌ Для імпорту потрібно мінімум 4 колонки: ТТН, Телефон, Вартість, Номер накладної.")
                        st.stop()

                    import_rows = df_upload.iloc[0:]
                    if import_rows.empty:
                        st.warning("⚠️ У файлі немає рядків із даними після рядка заголовків.")
                        st.stop()

                    # 2. Збір усіх ТТН для перевірки
                    raw_ttns = []
                    rows_map = {}
                    for _, row in import_rows.iterrows():
                        raw_t = str(row.iloc[0]).strip()
                        raw_phone = str(row.iloc[1]).strip()
                        raw_cost = str(row.iloc[2]).strip()
                        raw_invoice = str(row.iloc[3]).strip()

                        try:
                            parsed_cost = float(raw_cost.replace(",", ".")) if raw_cost and raw_cost.lower() != 'nan' else 0.0
                        except Exception:
                            parsed_cost = 0.0

                        # Якщо це Meest-номер із тире, не чистимо його
                        if "721-" in raw_t:
                            clean_t = raw_t.strip()
                        else:
                            clean_t = utils.clean_ttn(raw_t)
                            
                        if len(clean_t) == 12 and clean_t.isdigit(): clean_t = "0" + clean_t
                        if len(clean_t) > 5:
                            raw_ttns.append(clean_t)
                            rows_map[clean_t] = {
                                "phone": raw_phone,
                                "cost": parsed_cost,
                                "invoice": ""
                                if raw_invoice.lower() == "nan"
                                else utils.normalize_invoice_number(raw_invoice),
                            }

                    # 3. МАСОВА ПЕРЕВІРКА СТАТУСІВ (Нова Пошта)
                    st.toast("🕵️ Перевіряємо статуси ТТН...")
                    np_statuses = get_np_statuses_bulk(raw_ttns)

                    # 4. Фільтрація і додавання
                    added_count = 0
                    existing_ttns = [str(x) for x in st.session_state.df['ТТН'].tolist()]
                    
                    for ttn in raw_ttns:
                        if ttn in existing_ttns: continue
                        
                        # Отримуємо дані з API (якщо є)
                        info = np_statuses.get(ttn, {})
                        status = info.get('Status', 'Нове')
                        src = rows_map.get(ttn, {})
                        file_cost = float(src.get("cost", 0.0) or 0.0)
                        cost = info.get('Cost', 0.0) or file_cost
                        
                        # Пропускаємо завершені та відхилені відправлення
                        if utils.status_has_any(status, utils.DELIVERED_STATUS_KEYWORDS + utils.DECLINED_STATUS_KEYWORDS): continue
                        
                        # Визначаємо службу без зміни формату Meest
                        if "721-" in ttn:
                            svc = "Meest"
                        else:
                            svc = utils.identify_service(ttn)
                            
                        ph = utils.clean_phone(src.get("phone", ""))
                        if info.get('Phone'): ph = info['Phone']
                        invoice_num = utils.normalize_invoice_number(src.get("invoice", ""))

                        st.session_state.df.loc[len(st.session_state.df)] = {
                            "ТТН": ttn, "Служба": svc, "Статус": status, 
                            "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "Телефон": ph, "Вартість": cost, "Номер накладної": invoice_num, "Чек": "", "Повідомлення": "", 
                            "Статус СМС": "", "Статус Нагадування": "", "Дія": False
                        }
                        added_count += 1
                        existing_ttns.append(ttn)
                    
                    if added_count > 0:
                        sheets.save_manual(st.session_state.df)
                        run_auto_linking(silent=True)
                        st.success(f"✅ Імпортовано {added_count} активних посилок!")
                        time.sleep(1.5); st.rerun()
                    else:
                        st.warning("Нових активних посилок не знайдено.")
                        
                except Exception as e:
                    st.error(f"Помилка: {e}")

    with st.expander("📝 Оновити номера накладних з файлу", expanded=False):
        invoice_file = st.file_uploader("Оберіть файл (XLSX/CSV) - 1 колонка: ТТН, 2 колонка: номер накладної", type=['xlsx', 'csv'], key="invoice_uploader")
        if invoice_file:
            try:
                invoice_df = utils.read_uploaded_table(
                    invoice_file,
                    min_columns=2,
                    require_non_empty=True
                )

                if invoice_df is None:
                    st.error("❌ Не вдалось прочитати CSV. Файл може бути пошкоджений або мати неправильний формат.")
                    st.info("💡 Спробуйте: \n1. Зберегти файл як UTF-8 \n2. Переконайтесь що роздільник `,` або `;` \n3. Завантажити як XLSX")
                
                if invoice_df is not None:
                    # Очищуємо пробіли в назвах колонок
                    invoice_df.columns = invoice_df.columns.str.strip()
                    invoice_df = invoice_df.dropna(how='all')  # Видаляємо абсолютно пусті рядки
                    
                    st.info(f"📋 Прочитано {len(invoice_df)} рядків, {len(invoice_df.columns)} колонок")
                    st.write(f"**Колонки:** {list(invoice_df.columns)}")
                    
                    if len(invoice_df.columns) < 2:
                        st.error(f"❌ Файл містить тільки {len(invoice_df.columns)} колонку/колонок. Потрібно мінімум 2!")
                        st.warning("Переконайтесь що файл має правильний формат (ТТН | Накладна)")
                    elif len(invoice_df) == 0:
                        st.error("❌ Файл порожній або не містить даних!")
                    else:
                        with st.expander("👀 Попередній перегляд даних"):
                            st.dataframe(invoice_df.head(5), use_container_width=True)
                        
                        if st.button("🔄 Оновити накладні", key="btn_update_invoices"):
                            # Беремо перший і другий стовпці
                            ttn_col = invoice_df.columns[0]
                            invoice_num_col = invoice_df.columns[1]
                            
                            st.info(f"🔍 Оновлення: **{ttn_col}** → ТТН, **{invoice_num_col}** → Накладна")
                            
                            updated = 0
                            skipped = 0
                            found_count = 0
                            
                            for idx, row in invoice_df.iterrows():
                                ttn_raw = str(row[ttn_col]).strip()
                                invoice_num = utils.normalize_invoice_number(
                                    str(row[invoice_num_col]).strip()
                                )
                                
                                if not ttn_raw or ttn_raw.lower() == 'nan':
                                    skipped += 1
                                    continue
                                
                                if not invoice_num or invoice_num.lower() == 'nan':
                                    skipped += 1
                                    continue
                                
                                # Чистимо ТТН
                                if "721-" in ttn_raw:
                                    ttn_clean = ttn_raw
                                else:
                                    ttn_clean = utils.clean_ttn(ttn_raw)
                                
                                # Шукаємо в таблиці
                                for i, df_row in st.session_state.df.iterrows():
                                    if str(df_row['ТТН']).strip() == ttn_clean:
                                        st.session_state.df.at[i, 'Номер накладної'] = invoice_num
                                        updated += 1
                                        found_count += 1
                                        break
                                else:
                                    skipped += 1
                            
                            sheets.save_manual(st.session_state.df)
                            st.success(f"✅ Обновлено {updated} накладних! (Знайдено ТТН: {found_count}, Пропущено: {skipped})")
                            if updated > 0:
                                time.sleep(1); st.rerun()
            except Exception as e:
                st.error(f"❌ Помилка: {str(e)}")
                import traceback
                st.error(traceback.format_exc())

    with st.expander("➕ Додати ТТН вручну", expanded=True):
        with st.form("manual_add_form", clear_on_submit=True):
            manual_ttn = st.text_input("ТТН *")
            manual_phone = st.text_input("Телефон *")
            manual_cost = st.text_input("Вартість (грн) *")
            manual_invoice = st.text_input("Номер накладної *")
            submitted = st.form_submit_button("Додати")
            if submitted:
                ttn_raw = (manual_ttn or "").strip()
                phone_raw = (manual_phone or "").strip()
                cost_raw = (manual_cost or "").strip()
                invoice_raw = (manual_invoice or "").strip()
                missing = []
                if not ttn_raw:
                    missing.append("ТТН")
                if not phone_raw:
                    missing.append("Телефон")
                if not cost_raw:
                    missing.append("Вартість")
                if not invoice_raw:
                    missing.append("Номер накладної")
                if missing:
                    st.error(f"Заповніть обов'язкові поля: {', '.join(missing)}")
                else:
                    phone_clean = utils.clean_phone(phone_raw)
                    if len(phone_clean) <= 5:
                        st.error("Некоректний телефон.")
                    else:
                        try:
                            cost_value = float(cost_raw.replace(",", "."))
                        except ValueError:
                            st.error("Некоректна вартість — введіть число.")
                        else:
                            invoice_norm = utils.normalize_invoice_number(invoice_raw)
                            if not str(invoice_norm).strip():
                                st.error("Некоректний номер накладної.")
                            else:
                                parts = [p for p in ttn_raw.replace(",", " ").split() if p.strip()]
                                if len(parts) > 1:
                                    st.error("Додавайте лише один ТТН за раз.")
                                else:
                                    t = ttn_raw.strip()
                                    if "721-" in t:
                                        t_clean = t
                                        svc = "Meest"
                                    else:
                                        t_clean = utils.clean_ttn(t)
                                        svc = utils.identify_service(t_clean)
                                    if not t_clean:
                                        st.error("Не вдалось розпізнати ТТН.")
                                    elif t_clean in st.session_state.df["ТТН"].astype(str).str.strip().tolist():
                                        st.warning("Такий ТТН уже є в базі.")
                                    else:
                                        st.session_state.df.loc[len(st.session_state.df)] = {
                                            "ТТН": t_clean,
                                            "Служба": svc,
                                            "Статус": "Нове",
                                            "Дата": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "Телефон": phone_clean,
                                            "Вартість": cost_value,
                                            "Номер накладної": invoice_norm,
                                            "Чек": "",
                                            "Повідомлення": "",
                                            "Статус СМС": "",
                                            "Статус Нагадування": "",
                                            "Дія": False,
                                        }
                                        if sheets.save_manual(st.session_state.df):
                                            st.success("Додано накладну!")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error("Помилка збереження! Перевір права.")
    if st.button("📥 Завантажити нові", type="primary"):
        with st.status("Завантаження...", expanded=True):
            existing = [utils.clean_ttn(x) for x in st.session_state.df['ТТН'].tolist() if x]
            n_np = fetch_new_orders_np(existing)
            n_up = fetch_new_orders_up(existing)
            n_meest = fetch_new_orders_meest(existing)
            all_new = n_np + n_up + n_meest
            if all_new:
                new_df = pd.DataFrame(all_new)
                for c in config.COLS:
                    if c not in new_df.columns: new_df[c] = "" if c != "Дія" else False
                st.session_state.df = pd.concat([st.session_state.df, new_df], ignore_index=True)
                sheets.save_manual(st.session_state.df); 
                # Автопідбір чеків після додавання нових відправлень
                run_auto_linking(silent=True)
                st.success(f"✅ Додано {len(all_new)} нових!"); time.sleep(1); st.rerun()
            else: st.info("Нових немає")
    st.divider()
    if st.button(
        "🔗 Авто-підбір чеків",
        help="Лише якщо сума чека = «Вартість» до копійки і різниця між датою відправлення та датою чека не більше 2 хв. Інших умов немає.",
    ):
        run_auto_linking(silent=False)
    st.divider()
    if st.button(
        "🔄 Оновити НП та УП",
        help="Швидко: пакетна Нова пошта + запити Укрпошти. Meest тут не оновлюється.",
    ):
        _, saved = process_status_updates(show_ui=True, services=("НП", "УП"))
        if saved:
            st.success("Статуси НП та УП оновлено.")
            time.sleep(0.8)
            st.rerun()
    if st.button(
        "🐢 Оновити Meest",
        help="Повільно: для кожної ТТН Meest відкривається Chromium (Selenium) і очікування сторінки ~8 с.",
    ):
        _, saved = process_status_updates(show_ui=True, services=("Meest",))
        if saved:
            st.success("Статуси Meest оновлено.")
            time.sleep(0.8)
            st.rerun()
    st.caption(
        "Потрібні обидві? Спочатку **НП та УП**, потім **Meest** — так швидше, ніж все в одному проході."
    )
    with st.expander("Усі служби одним запуском (довго)"):
        st.caption("НП + УП + Meest підряд. Meest через Selenium — на кожну ТТН ~8+ с.")
        if st.button("🔄 Оновити все (НП + УП + Meest)", key="status_all_services"):
            _, saved = process_status_updates(show_ui=True, services=None)
            if saved:
                st.success("Усі статуси оновлено.")
                time.sleep(0.8)
                st.rerun()
    st.divider()
    if st.button("🗑️ Видалити відправлені", type="secondary"): new_df = st.session_state.df[st.session_state.df['Статус СМС'] != 'Отправлено'].reset_index(drop=True); sheets.save_manual(new_df); st.success("✅ Очищено!"); time.sleep(1); st.rerun()
    if st.button("🚪 Вийти", type="secondary"): st.session_state.logged_in = False; st.session_state.pop("auth_user", None); st.rerun()


def _autosave_table_on_edit():
    """Зберегти в callback, поки edited_rows ще в session_state (2-ге редагування)."""
    st.session_state.pop("_tab2_saved_in_callback", None)
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        st.session_state["_tab2_pending_save"] = "full"
        return
    to_save = _filter_rows_vs_baseline(_edited_rows_from_main(main))
    if to_save and _apply_partial_edits(to_save):
        st.session_state["_tab2_saved_in_callback"] = True
        return
    st.session_state["_tab2_pending_save"] = True


def _mark_tab2_saved():
    try:
        st.toast("Збережено", icon="✅")
    except Exception:
        pass


def _save_table_from_editor(edited_df=None) -> bool:
    """Зберегти таблицю вручну: частково або повністю."""
    if isinstance(edited_df, pd.DataFrame):
        if _autosave_table_from_editor(edited_df):
            return True
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)
    if isinstance(main, dict) and main.get("edited_rows"):
        if _autosave_table_edits_partial(editor_value=main, edited_df=edited_df):
            return True
    src = _coalesce_edited_table(main) if main else None
    if src is None and isinstance(edited_df, pd.DataFrame):
        src = edited_df
    if src is None:
        src = st.session_state.df
    prepared = _prepare_table_df_for_save(src)
    return sheets.save_manual(prepared, clear_cache=False, merge_session=True)


@st.fragment
def tab2_main_fragment():
    """Окремий фрагмент: автозбереження після редагування (без окремої кнопки)."""
    _tab2_editor_baseline()
    _render_tab2_scroll_preserve()
    col_order = get_table_column_order()
    display_df = _tab2_display_dataframe(col_order)

    with st.expander("↔️ Порядок колонок", expanded=False):
        order = list(col_order)
        for i, col in enumerate(order):
            c1, c2, c3 = st.columns([6, 1, 1])
            with c1:
                st.markdown(f"**{i + 1}.** {col}")
            with c2:
                if st.button("↑", key=f"tab2_col_up_{col}", disabled=(i == 0)):
                    new_order = list(order)
                    new_order[i], new_order[i - 1] = new_order[i - 1], new_order[i]
                    persist_table_column_order(new_order)
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
            with c3:
                if st.button("↓", key=f"tab2_col_dn_{col}", disabled=(i == len(order) - 1)):
                    new_order = list(order)
                    new_order[i], new_order[i + 1] = new_order[i + 1], new_order[i]
                    persist_table_column_order(new_order)
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
        if st.button("Скинути порядок колонок", key="tab2_col_reset"):
            persist_table_column_order(list(config.COLS))
            st.session_state.df = apply_table_column_order(st.session_state.df, config.COLS)
            st.rerun()

    edited_df = st.data_editor(
        display_df.style.map(utils.color_status, subset=["Статус"]),
        key="main",
        height=600,
        use_container_width=True,
        hide_index=True,
        column_order=col_order,
        on_change=_autosave_table_on_edit,
        column_config={
            "Дія": None,
            "Статус": st.column_config.TextColumn(width="large", disabled=True),
            "Чек": st.column_config.LinkColumn(display_text="🧾"),
            "Статус СМС": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "Статус Нагадування": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "ТТН": st.column_config.TextColumn(help="Meest, НП, УП"),
        },
    )
    if st.session_state.pop("_tab2_saved_in_callback", False):
        _mark_tab2_saved()
    pending = st.session_state.pop("_tab2_pending_save", False)
    if pending:
        ok = False
        if pending == "full":
            main = st.session_state.get("main")
            ok = _autosave_table_if_changed(main, show_toast=False)
        else:
            ok = _autosave_table_from_editor(edited_df)
        if ok:
            _mark_tab2_saved()

    if st.button(
        "💾 Зберегти",
        type="primary",
        use_container_width=True,
        key="tab2_manual_save",
    ):
        if _save_table_from_editor(edited_df):
            _mark_tab2_saved()
        else:
            st.error("Не вдалося зберегти таблицю.")

    st.caption(
        "Зміни зберігаються автоматично після Enter або кліку поза коміркою. "
        "Кнопка «Зберегти» — на всяк випадок, якщо автозбереження не спрацювало."
    )


_auth_lc = str(st.session_state.get("auth_user", "")).strip().lower()
_is_manager = _auth_lc == "manager"
# Вкладка «УП ТТН» (eCom / майстер) — лише для admin; менеджер її не бачить.
_show_up_ttn_tab = _auth_lc == "admin"

_tab_names = [
    "📨 Видати чек",
    "📊 Таблиця",
]
if _show_up_ttn_tab:
    _tab_names.append("📮 УП ТТН")
_tab_names.extend(
    [
        "❌ Відмови",
        "🧾 Архів чеків",
        "⏳ Нагадування",
    ]
)
# Менеджеру не показуємо журнал дій (вкладка «Контроль»).
if not _is_manager:
    _tab_names.append("📋 Контроль")
_tabs = st.tabs(_tab_names)
_i = 0
tab1 = _tabs[_i]
_i += 1
tab2 = _tabs[_i]
_i += 1
if _show_up_ttn_tab:
    tab_up = _tabs[_i]
    _i += 1
tab3 = _tabs[_i]
_i += 1
tab4 = _tabs[_i]
_i += 1
tab5 = _tabs[_i]
_i += 1
@st.fragment
def tab1_checkout_fragment():
    if utils.apply_no_receipt_auto_sent(st.session_state.df):
        sheets.save_manual(st.session_state.df)

    failed_ttn = st.session_state.pop("_tab1_save_failed", None)
    if failed_ttn:
        st.warning(
            f"Рядок `{failed_ttn}` прибрано з черги, але запис у Google не вдався — "
            "перевір інтернет і натисни «Зберегти» на вкладці «Таблиця» за потреби."
        )

    # 1. Створюємо список статусів, при яких нам потенційно потрібно додати чек вручну
    target_statuses = utils.DELIVERED_STATUS_KEYWORDS
    
    # 2. Оновлена маска: показуємо, якщо СМС ще не відправлено І (вже є текст АБО статус підходить для видачі чека)
    no_receipt_mask = ~st.session_state.df.apply(utils.row_receipt_not_required, axis=1)
    mask = (
        no_receipt_mask
        & (st.session_state.df['Статус СМС'] != 'Отправлено')
        & (
            (st.session_state.df['Повідомлення'].str.len() > 5)
            | (st.session_state.df['Статус'].str.lower().str.contains('|'.join(target_statuses)))
        )
    )
    
    pending = st.session_state.df[mask]

    bulk_res = st.session_state.pop("_tab1_bulk_result", None)
    if bulk_res:
        st.success(f"TurboSMS: надіслано **{bulk_res['ok']}**")
        if bulk_res.get("errors"):
            with st.expander(f"Помилки ({len(bulk_res['errors'])})"):
                for ttn, err in bulk_res["errors"]:
                    st.markdown(f"`{ttn}` — {err}")

    if pending.empty:
        st.success("🎉 Черга пуста!")
    else:
        ready_rows = []
        for idx, row in pending.iterrows():
            if not _tab1_ready_for_turbosms(row):
                continue
            ready_rows.append((idx, row, _tab1_sms_text_for_send(row)))

        if utils.turbosms_configured():
            import config as _cfg_bulk

            n_ready = len(ready_rows)
            n_pending = len(pending)
            st.caption(
                f"У черзі **{n_pending}** · готові до TurboSMS (є чек + телефон): **{n_ready}** · "
                f"відправник **{_cfg_bulk.TURBOSMS_SENDER}**"
            )
            if n_ready > 0:
                if st.button(
                    f"📨 Видати готові чеки — TurboSMS ({n_ready})",
                    type="primary",
                    key="tab1_bulk_turbosms",
                    use_container_width=True,
                ):
                    with st.spinner(f"Відправка {n_ready} SMS через TurboSMS…"):
                        sent, errors = _tab1_bulk_send_turbosms(ready_rows)
                    st.session_state["_tab1_bulk_result"] = {"ok": sent, "errors": errors}
                    st.rerun()
            else:
                st.info("Немає рядків з чеком і телефоном — спочатку прикріпіть чек Checkbox.")
        else:
            st.caption("Масова відправка: додай **TURBOSMS_TOKEN** у Secrets.")

        for idx, row in pending.iterrows():
            wid = tab1_row_widget_id(row)
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                
                with c1: 
                    st.markdown(f"**{row['Служба']}** `{row['ТТН']}`")
                    st.caption(row['Статус'])
                    st.markdown(f"📞 **{row['Телефон']}**")
                    invoice_num = str(row.get('Номер накладної', '')).strip()
                    if invoice_num and invoice_num.lower() != 'nan':
                        render_copyable_invoice(invoice_num, row_key=f"tab1_{wid}")
                    if float(row.get('Вартість', 0)) > 0: 
                        st.markdown(f"💰 **{row['Вартість']} грн**")
                
                with c2:
                    current_link = str(row.get('Чек', ''))
                    # Якщо чека ще немає - показуємо поле вводу
                    if len(current_link) < 5 or current_link.lower() == 'nan':
                        new_link = st.text_input("➕ Додати чек вручну:", key=f"add_link_{wid}", placeholder="https://...")
                        if new_link:
                            st.session_state[f"tab1_pick_open_{wid}"] = False
                            st.session_state.df.at[idx, 'Чек'] = new_link
                            new_msg = _CHECK_SMS_TEXT.format(link=new_link)
                            st.session_state.df.at[idx, 'Повідомлення'] = new_msg
                            st.session_state[f"tab1_sms_{wid}"] = new_msg
                            st.session_state[f"_tab1_last_ck_{wid}"] = new_link
                            try:
                                sc_m = float(
                                    str(row.get("Вартість", 0))
                                    .replace(",", ".")
                                    .strip()
                                    or 0
                                )
                            except Exception:
                                sc_m = None
                            arch_m = fetch_checkbox_archive()
                            rs_m = (
                                _audit_lookup_receipt_sum(new_link, arch_m)
                                if arch_m is not None and not arch_m.empty
                                else None
                            )
                            audit_log(
                                "чек_посилання",
                                str(row.get("ТТН", "")).strip()[:40],
                                new_link[:120],
                                ship_cost=sc_m,
                                receipt_sum=rs_m,
                            )
                            st.session_state._deferred_save = True
                            st.rerun()

                        pick_key = f"tab1_pick_open_{wid}"
                        if not st.session_state.get(pick_key):
                            if st.button(
                                "📋 Вибрати чек зі списку",
                                key=f"open_pick_{wid}",
                                help="Оновлює чеки з Checkbox і показує варіанти з твоєю сумою",
                                type="primary",
                                use_container_width=True,
                            ):
                                fetch_checkbox_archive.clear()
                                st.session_state[pick_key] = True
                                st.rerun()
                        else:
                            st.markdown("**Чеки з Checkbox**")
                            try:
                                row_cost = float(
                                    str(row.get("Вартість", 0)).replace(",", ".").strip() or 0
                                )
                            except Exception:
                                row_cost = 0.0

                            arch = fetch_checkbox_archive()
                            pick_rows = tab1_unattached_receipt_picker_rows(
                                st.session_state.df, arch, row.get("Вартість", 0)
                            )

                            if arch is None:
                                st.caption("Архів недоступний: перевір логін / ліцензію Checkbox у Secrets.")
                            elif row_cost <= 0:
                                st.caption("Потрібна **вартість** відправлення в таблиці.")
                            elif not pick_rows:
                                st.caption(
                                    "Немає вільних чеків на цю суму в архіві Checkbox. "
                                    "Якщо чек щойно створили — онови запит."
                                )
                                if st.button(
                                    "🔄 Спробувати ще раз",
                                    key=f"retry_pick_{wid}",
                                    use_container_width=True,
                                ):
                                    fetch_checkbox_archive.clear()
                                    st.rerun()
                            else:
                                sum_show = f"{row_cost:.2f}".replace(".", ",")
                                st.caption(
                                    f"Обери рядок (дата, год:хв, сума). Новіші зверху. **{sum_show} грн**."
                                )
                                labels = [p["label"] for p in pick_rows]
                                label_to_link = {p["label"]: p["link"] for p in pick_rows}
                                rk = f"tab1_rcpt_{wid}"
                                st.radio(
                                    "Чек",
                                    labels,
                                    key=rk,
                                    label_visibility="collapsed",
                                )
                                if st.button(
                                    "Прикріпити",
                                    key=f"apply_chk_{wid}",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    choice = st.session_state.get(rk)
                                    sel_link = label_to_link.get(choice)
                                    if sel_link:
                                        fetch_checkbox_archive.clear()
                                        st.session_state[pick_key] = False
                                        st.session_state.df.at[idx, "Чек"] = sel_link
                                        new_msg = _CHECK_SMS_TEXT.format(link=sel_link)
                                        st.session_state.df.at[idx, "Повідомлення"] = new_msg
                                        st.session_state[f"tab1_sms_{wid}"] = new_msg
                                        st.session_state[f"_tab1_last_ck_{wid}"] = sel_link
                                        rs_p = (
                                            _audit_lookup_receipt_sum(sel_link, arch)
                                            if arch is not None and not arch.empty
                                            else None
                                        )
                                        audit_log(
                                            "чек_список",
                                            str(row.get("ТТН", "")).strip()[:40],
                                            sel_link[:120],
                                            ship_cost=row_cost if row_cost > 0 else None,
                                            receipt_sum=rs_p,
                                        )
                                        st.session_state._deferred_save = True
                                        st.rerun()

                            if st.button(
                                "Закрити список",
                                key=f"close_pick_{wid}",
                                use_container_width=True,
                            ):
                                st.session_state[pick_key] = False
                                st.rerun()

                    wk = f"tab1_sms_{wid}"
                    ck = str(row.get("Чек", "")).strip()
                    syn_ck = f"_tab1_last_ck_{wid}"
                    loc_row = st.session_state.df.loc[idx]
                    valid_ck = ck and len(ck) > 5 and ck.lower() != "nan"
                    if syn_ck not in st.session_state:
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                        st.session_state[syn_ck] = ck
                    elif st.session_state[syn_ck] != ck:
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                        st.session_state[syn_ck] = ck
                    elif not str(st.session_state.get(wk, "")).strip():
                        filled = tab1_default_sms_text(loc_row)
                        if len(filled) > 5:
                            st.session_state[wk] = filled
                    elif (
                        valid_ck
                        and ck
                        not in str(st.session_state.df.at[idx, "Повідомлення"])
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                    elif (
                        not valid_ck
                        and _CHECKBOX_RECEIPT_HOST
                        in str(st.session_state.get(wk, "")).lower()
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)
                    elif (
                        not valid_ck
                        and _CHECKBOX_RECEIPT_HOST
                        in str(st.session_state.df.at[idx, "Повідомлення"]).lower()
                    ):
                        st.session_state[wk] = tab1_default_sms_text(loc_row)

                    txt = st.text_area(
                        "Текст СМС",
                        height=100,
                        key=wk,
                        label_visibility="collapsed",
                    )
                    st.session_state.df.at[idx, "Повідомлення"] = txt

                with c3:
                    if utils.turbosms_configured():
                        import config as _cfg

                        st.caption(f"SMS: **{_cfg.TURBOSMS_SENDER}**")
                        if st.button(
                            "📨 Надіслати TurboSMS",
                            key=f"turbo_sms_{wid}",
                            type="primary",
                            use_container_width=True,
                        ):
                            ok, terr = _tab1_send_turbosms_row(idx, row)
                            if ok:
                                st.toast("SMS надіслано через TurboSMS", icon="📨")
                                st.rerun()
                            else:
                                st.error(terr)
                    else:
                        st.caption("TurboSMS: додай TURBOSMS_TOKEN у Secrets")

                    render_smart_buttons(
                        row["Телефон"],
                        st.session_state.df.at[idx, "Повідомлення"],
                        row_key=f"tab1_{wid}",
                    )
                    if st.button("✅ Готово", key=f"done_{wid}", use_container_width=True):
                        _tab1_mark_done(idx, row)
                        st.rerun()
with tab1:
    tab1_checkout_fragment()
with tab2:
    tab2_main_fragment()
if _show_up_ttn_tab:
    with tab_up:
        render_up_shipments_tab()
with tab3: mask = st.session_state.df['Статус'].str.lower().str.contains('відмова|повернення|denied', na=False); st.dataframe(st.session_state.df[mask].style.map(utils.color_status, subset=['Статус']), use_container_width=True, hide_index=True)
with tab4:
    render_checkbox_archive_tab()
with tab5:
    st.subheader("⏳ Посилки, що чекають > 5 днів"); today = datetime.now(); found_rem = False
    for idx, row in st.session_state.df.iterrows():
        s_low = str(row['Статус']).lower()
        if any(x in s_low for x in ['прибув', 'прибуло', 'відділенні']) and not any(
            x in s_low
            for x in [
                "отримано",
                "отримане",
                "отримані",
                "отриманий",
                "отримана",
                "відмова",
            ]
        ):
            try:
                d_str = utils.normalize_date(str(row['Дата'])); 
                if not d_str: continue
                delta = today - datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")
                if delta.days >= 5:
                    found_rem = True; svc_map = {"НП": "Нова пошта", "УП": "Укрпошта", "Meest": "Meest Пошта"}; msg = f"Добрий день! Ваше замовлення вже у відділенні {svc_map.get(row['Служба'], row['Служба'])} {row['ТТН']}. Прохання забрати посилку."; is_sent = str(row.get('Статус Нагадування', '')) == 'Отправлено'
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([1.5, 3, 1.5])
                        with c1: st.markdown(f"**{row['Служба']}** `{row['ТТН']}`"); st.caption(f"Чекає: {delta.days} днів"); st.markdown(f"📞 **{row['Телефон']}**"); 
                        if is_sent: st.success("✅ Відправлено")
                        with c2: st.text_area("Текст", msg, height=80, key=f"rt_{idx}", label_visibility="collapsed")
                        with c3: render_smart_buttons(row['Телефон'], msg, row_key=f"tab5_{idx}"); 
                        if st.button("✅ Вже нагадав", key=f"rem_done_{idx}", use_container_width=True): st.session_state.df.at[idx, 'Статус Нагадування'] = 'Отправлено'; sheets.save_manual(st.session_state.df); st.rerun()
            except Exception: continue
    if not found_rem: st.info("👍 Боржників немає.")

if not _is_manager:
    with _tabs[-1]:
        st.subheader("📋 Хто що зробив")
        st.caption(
            "Журнал: Google **Orders** → **LogisticAudit**. "
            "**чек_посилання** — URL вручну; **чек_список** — з Checkbox; **чек_авто** — авто; **смс_готово** — «Готово». "
            "**Вартість ТТН** / **Сума чеку** зберігаються в аркуші на момент події; у таблиці нижче спочатку показуються вони, далі — підстановка з таблиці замовлень і архіву Checkbox. "
            "**Зелений** = збіг сум (±0,01 грн), **червоний** = розбіжність, коли обидва числа відомі."
        )
        if st.button("Оновити журнал", key="audit_refresh"):
            _cached_audit_log_df.clear()
            st.rerun()
        adf = _cached_audit_log_df()
        if adf.empty:
            st.info("Поки немає записів — після дій з’являться тут і в таблиці LogisticAudit.")
        else:
            chk_df = fetch_checkbox_archive()
            disp = _enrich_audit_table(adf, st.session_state.df, chk_df)
            styled = (
                _style_audit_amounts(disp).format(
                    {"Вартість ТТН": "{:.2f}", "Сума чеку": "{:.2f}"},
                    na_rep="—",
                )
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

if st.session_state.get('_deferred_save'):
    st.session_state._deferred_save = False
    if not sheets.save_manual(st.session_state.df):
        st.error("❌ Не вдалося зберегти зміни після позначення 'Готово'.")
