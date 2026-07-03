"""Архів чеків Checkbox (API + підбір для tab1)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

import config
import utils

ARCHIVE_DAYS = 30
_CHECKBOX_ARCHIVE_DAYS = ARCHIVE_DAYS
_CHECKBOX_PAGE_SIZE = 100
_CHECKBOX_MAX_PAGES = 100


def archive_shift_day(days_sorted: list, current, step: int):
    """days_sorted — від нових до старих; step +1 = попередній день, -1 = наступний."""
    if not days_sorted:
        return current
    try:
        idx = days_sorted.index(current)
    except ValueError:
        idx = 0
    new_idx = max(0, min(len(days_sorted) - 1, idx + step))
    return days_sorted[new_idx]


def _parse_checkbox_receipt_item(item: dict) -> dict:
    raw_date = item.get("created_at", "")
    try:
        dt = utils.utc_naive_to_kyiv_naive(
            datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S")
        )
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
        date_from = (
            utils.now_kyiv_naive() - timedelta(days=_CHECKBOX_ARCHIVE_DAYS)
        ).isoformat()
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


def tab1_freshest_today_unattached_receipt(df, checkbox_df, amount):
    """Найновіший вільний чек за сьогодні (Київ) із сумою = вартість відправлення.

    Повертає ({"link", "receipt_sum", "dt_label"} | None, повідомлення_помилки).
    """
    if checkbox_df is None or checkbox_df.empty:
        return None, "Архів Checkbox недоступний — перевір логін / ліцензію у Secrets."
    try:
        amt = round(float(str(amount).replace(",", ".").strip()), 2)
    except Exception:
        return None, "Некоректна вартість у рядку."
    if amt <= 0:
        return None, "Потрібна **вартість** відправлення в таблиці."

    used = used_checkbox_links_from_df(df)
    today = utils.today_kyiv()
    best = None
    best_ts = None

    for _, r in checkbox_df.iterrows():
        link = str(r.get("Посилання", "")).strip()
        if not link or link in used:
            continue
        try:
            sm = round(float(r.get("Сума", 0) or 0), 2)
        except Exception:
            continue
        if abs(sm - amt) >= 0.01:
            continue
        dt_s = str(r.get("Дата", "")).strip()
        dt_obj = pd.to_datetime(dt_s, errors="coerce")
        if pd.isna(dt_obj) or dt_obj.date() != today:
            continue
        if best is None or dt_obj > best_ts:
            best = {
                "link": link,
                "receipt_sum": sm,
                "dt_label": dt_obj.strftime("%Y-%m-%d %H:%M"),
            }
            best_ts = dt_obj

    if best is None:
        sum_txt = f"{amt:.2f}".replace(".", ",")
        return None, (
            f"Немає вільного чека на **{sum_txt} грн** за сьогодні. "
            "Якщо чек щойно пробили — натисніть ще раз."
        )
    return best, ""
