"""Prom.ua tab: import orders into CRM."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

import config
import sheets
from core.messages import ensure_messages_exist
from core.table_data import ensure_columns
from services import promua


def _prom_import_orders(orders: list[dict]) -> tuple[int, int]:
    """Import orders into main Orders table. Returns (added, updated)."""
    if "df" not in st.session_state or not isinstance(st.session_state.get("df"), pd.DataFrame):
        st.session_state.df = ensure_columns(sheets.load_data_from_gsheets())
    df = ensure_columns(st.session_state.df.copy())

    added = 0
    updated = 0
    existing_ttns = df["ТТН"].astype(str).str.strip().tolist() if "ТТН" in df.columns else []
    ttn_to_idx = {str(df.at[i, "ТТН"]).strip(): i for i in df.index} if "ТТН" in df.columns else {}

    for order in orders:
        row = promua.order_to_row(order)
        ttn = str(row.get("ТТН") or "").strip()
        if not ttn:
            continue
        if ttn in existing_ttns and ttn in ttn_to_idx:
            idx = ttn_to_idx[ttn]
            for col in ("Статус", "Дата", "Телефон", "Вартість", "Номер накладної", "Повідомлення"):
                if col in df.columns and row.get(col) not in (None, ""):
                    df.at[idx, col] = row[col]
            if "Служба" in df.columns:
                df.at[idx, "Служба"] = "PROM"
            updated += 1
        else:
            df.loc[len(df)] = row
            existing_ttns.append(ttn)
            added += 1

    st.session_state.df = ensure_messages_exist(ensure_columns(df))
    if added or updated:
        sheets.save_manual(st.session_state.df)
    return added, updated


def render_tab() -> None:
    config.apply_prom_secrets()
    st.subheader("🛍️ Prom.ua · замовлення")
    st.caption(
        "Підключення: додайте `PROM_UA_TOKEN` у Secrets (корінь файлу, без `Bearer`). "
        "Імпорт переносить замовлення Prom.ua в CRM таблицю."
    )

    if not promua.token_configured():
        diag = config.prom_secret_diagnostics()
        st.warning(
            "Токен Prom.ua не знайдено. У **Streamlit Cloud → Settings → Secrets** "
            "додайте рядок у **корінь** файлу (не всередині `[auth_users]`):\n\n"
            "```toml\nPROM_UA_TOKEN = \"ваш_api_token\"\n"
            "PROM_UA_SYNC_SEC = 300\nPROM_UA_IMPORT_LIMIT = 50\n```\n\n"
            "Після збереження натисніть **Reboot app**."
        )
        with st.expander("Діагностика Secrets"):
            st.write(f"Токен: **{diag['token']}**")
            st.write(f"Знайдені ключі: {diag['found_keys']}")
            st.write(f"Секції з «prom»: {diag['prom_sections']}")
            st.caption(diag["hint"])
        return

    limit_default = int(getattr(config, "PROM_UA_IMPORT_LIMIT", 50) or 50)
    sync_default = int(getattr(config, "PROM_UA_SYNC_SEC", 300) or 300)

    c1, c2, c3 = st.columns([1.1, 1.2, 2.2])
    with c1:
        limit = st.number_input("Ліміт", min_value=1, max_value=200, value=limit_default, step=5)
    with c2:
        page = st.number_input("Сторінка", min_value=1, max_value=500, value=1, step=1)
    with c3:
        auto = st.toggle("Авто-імпорт", key="prom_auto_import")
        sync_sec = st.number_input("Інтервал, сек", min_value=30, max_value=3600, value=sync_default, step=30)

    last_sync_ts = float(st.session_state.get("prom_last_sync_ts") or 0)
    due = auto and (time.time() - last_sync_ts) >= float(sync_sec)

    if st.button("🔄 Завантажити з Prom.ua", type="primary", use_container_width=True) or due:
        orders, meta, err = promua.fetch_orders(limit=int(limit), page=int(page))
        if err:
            st.error(err)
            return
        st.session_state.prom_last_orders = orders
        st.session_state.prom_last_meta = meta
        st.session_state.prom_last_sync_ts = time.time()
        if due:
            added, updated = _prom_import_orders(orders)
            st.toast(f"Prom авто-імпорт: +{added}, оновлено {updated}", icon="✅")

    orders = st.session_state.get("prom_last_orders") or []
    meta = st.session_state.get("prom_last_meta") or {}
    if meta:
        st.caption(
            f"Prom.ua: сторінка **{meta.get('page', 1)}** / {meta.get('pages', '?')} · "
            f"всього **{meta.get('total', len(orders))}**"
        )

    if not orders:
        st.info("Замовлення ще не завантажені.")
        return

    if st.button("📥 Імпортувати в CRM (усі завантажені)", use_container_width=True):
        added, updated = _prom_import_orders(orders)
        st.success(f"Імпорт завершено: додано {added}, оновлено {updated}.")

    preview = []
    for order in orders[:100]:
        row = promua.order_to_row(order)
        preview.append(
            {
                "ID": order.get("id"),
                "Дата": row.get("Дата"),
                "Статус": row.get("Статус"),
                "ТТН": row.get("ТТН"),
                "Телефон": row.get("Телефон"),
                "Сума": row.get("Вартість"),
            }
        )
    st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)
