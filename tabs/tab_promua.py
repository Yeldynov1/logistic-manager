"""Prom.ua tab: orders list (Rozetka-style cards) + CRM import."""
from __future__ import annotations

import time
from html import escape

import pandas as pd
import streamlit as st

import config
import sheets
from core.messages import ensure_messages_exist
from core.table_data import ensure_columns
from services import promua
from ui import delivery_logos


def _prom_import_orders(orders: list[dict], *, ttn_overrides: dict[int, str] | None = None) -> tuple[int, int]:
    """Import orders into main Orders table. Returns (added, updated)."""
    if "df" not in st.session_state or not isinstance(st.session_state.get("df"), pd.DataFrame):
        st.session_state.df = ensure_columns(sheets.load_data_from_gsheets())
    df = ensure_columns(st.session_state.df.copy())

    added = 0
    updated = 0
    existing_ttns = df["ТТН"].astype(str).str.strip().tolist() if "ТТН" in df.columns else []
    ttn_to_idx = {str(df.at[i, "ТТН"]).strip(): i for i in df.index} if "ТТН" in df.columns else {}
    overrides = ttn_overrides or {}

    for order in orders:
        oid = promua.order_id(order)
        override = overrides.get(oid, "") if oid is not None else ""
        row = promua.order_to_row(order, ttn_override=override)
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


def _prom_order_cache() -> dict:
    cache = st.session_state.get("prom_order_detail_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.prom_order_detail_cache = cache
    return cache


def _prom_get_order_cached(oid: int) -> tuple[dict | None, str]:
    cache = _prom_order_cache()
    key = str(int(oid))
    if key in cache:
        val = cache.get(key)
        if isinstance(val, dict):
            return val, ""
    full, err = promua.fetch_order(oid)
    if err:
        return None, err
    if not full:
        return None, "Не вдалося завантажити замовлення"
    cache[key] = full
    return full, ""


def _prom_ttn_overrides_from_session(orders: list[dict]) -> dict[int, str]:
    out: dict[int, str] = {}
    for order in orders:
        oid = promua.order_id(order)
        if oid is None:
            continue
        key = f"prom_ttn_input_{oid}"
        val = str(st.session_state.get(key, "") or "").strip()
        if val:
            out[oid] = val
    return out


def render_tab() -> None:
    config.apply_prom_secrets()
    st.subheader("🛍️ Prom.ua · замовлення")
    st.caption(
        "Підключення: `PROM_UA_TOKEN` у Secrets. Список у форматі як на Rozetka; "
        "імпорт переносить замовлення в CRM таблицю."
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

    col_r, col_s = st.columns([1, 3])
    with col_r:
        if st.button("🔄 Оновити список", key="prom_refresh", use_container_width=True):
            st.session_state.pop("prom_orders_cache", None)
            st.session_state.pop("prom_orders_meta", None)
            st.session_state.pop("prom_orders_err", None)
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
    with col_s:
        auto = st.toggle("Авто-імпорт у CRM", key="prom_auto_import")
        sync_sec = st.number_input(
            "Інтервал авто-імпорту, сек",
            min_value=30,
            max_value=3600,
            value=sync_default,
            step=30,
            label_visibility="collapsed",
        )
        st.caption(
            "На картці — **логотип служби доставки**. "
            "ТТН можна ввести вручну перед імпортом у CRM."
        )

    page = int(st.session_state.get("prom_page", 1))
    if "prom_orders_cache" not in st.session_state:
        orders, meta, err = promua.fetch_orders(limit=limit_default, page=page)
        if err:
            st.session_state.prom_orders_err = err
            st.session_state.prom_orders_cache = []
            st.session_state.prom_orders_meta = {}
        else:
            st.session_state.prom_orders_cache = orders
            st.session_state.prom_orders_meta = meta
            st.session_state.prom_orders_err = ""

    err = str(st.session_state.get("prom_orders_err") or "")
    if err:
        st.error(f"Prom.ua API: {err}")
        return

    orders = st.session_state.get("prom_orders_cache") or []
    meta = st.session_state.get("prom_orders_meta") or {}
    if meta:
        st.caption(
            f"Сторінка **{meta.get('page', page)}** / {meta.get('pages', '?')} · "
            f"всього **{meta.get('total', len(orders))}**"
        )

    last_sync_ts = float(st.session_state.get("prom_last_sync_ts") or 0)
    due = auto and orders and (time.time() - last_sync_ts) >= float(sync_sec)
    if due:
        added, updated = _prom_import_orders(orders, ttn_overrides=_prom_ttn_overrides_from_session(orders))
        st.session_state.prom_last_sync_ts = time.time()
        st.toast(f"Prom авто-імпорт: +{added}, оновлено {updated}", icon="✅")

    if not orders:
        st.info("Немає замовлень або список порожній. Натисніть «Оновити список».")
        return

    if st.button("📥 Імпортувати в CRM (усі на сторінці)", use_container_width=True):
        added, updated = _prom_import_orders(
            orders, ttn_overrides=_prom_ttn_overrides_from_session(orders)
        )
        st.success(f"Імпорт завершено: додано {added}, оновлено {updated}.")

    delivery_logos.inject_rozetka_delivery_css()

    order_items: list[tuple[int, dict]] = []
    for order in orders:
        oid = promua.order_id(order)
        if oid is None:
            continue
        order_items.append((oid, order))

    for card_n, (oid, order) in enumerate(order_items):
        status = promua.status_label(order)
        phone = promua.phone(order) or "—"
        ttn = promua.order_ttn(order)
        amount = promua.order_amount_display(order)
        created = promua.order_created_display(order)
        recipient = promua.recipient_name(order)
        pay_form = promua.payment_label(order)
        if promua.is_cod_payment_order(order):
            pay_form = f"{pay_form} (при отриманні)".strip()
        pay_status = promua.payment_status_label(order)
        title = promua.product_title(order)
        svc_logo = delivery_logos.badge_html_for_prom_order(order)
        place_hint = promua.delivery_place_hint(order)
        is_up = promua.is_ukrposhta_order(order)

        kind = promua.delivery_service_kind(order)
        card_slug = {"УП": "up", "НП": "np", "Meest": "meest", "Rozetka": "rz"}.get(kind, "other")

        status_line = escape(status)
        if ttn:
            status_line += f' · ТТН <code class="rz-ttn-code">{escape(ttn)}</code>'

        cap = f"📞 {phone}"
        if place_hint:
            cap += f" · {place_hint}"
        if title:
            cap += f" · {title}"

        with st.container(border=True):
            st.markdown(
                f'<div class="rz-order-card rz-card-{card_slug}" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="rz-order-head">'
                f'<div class="rz-order-meta">#{oid} · {escape(created)}</div>'
                f"{svc_logo}"
                f"</div>"
                f'<div class="rz-order-status">{status_line}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:1.45rem;font-weight:800;line-height:1.2;color:#16A34A;'>"
                f"Замовлення #{oid}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Отримувач:** {recipient}")
            st.markdown(
                f"**Сума:** `{amount}` грн · **Форма оплати:** {pay_form}"
                + (f" · **Статус оплати:** {pay_status}" if pay_status else "")
            )
            st.caption(cap)

            ttn_key = f"prom_ttn_input_{oid}"
            if ttn_key not in st.session_state and ttn:
                st.session_state[ttn_key] = ttn

            c1, c2 = st.columns(2)
            with c1:
                if st.button("📋 Деталі", key=f"prom_det_{oid}", use_container_width=True):
                    st.session_state[f"prom_show_{oid}"] = not st.session_state.get(f"prom_show_{oid}")
                    st.rerun()
            with c2:
                if st.button("📥 В CRM", key=f"prom_crm_{oid}", use_container_width=True):
                    overrides = {oid: str(st.session_state.get(ttn_key, "") or "").strip()}
                    added, updated = _prom_import_orders([order], ttn_overrides=overrides)
                    st.toast(f"CRM: +{added}, оновлено {updated}", icon="✅")

            if is_up:
                st.caption("Укрпошта: створіть ТТН на вкладці **УП ТТН** або в кабінеті УП.")

            if st.session_state.get(f"prom_show_{oid}"):
                content, derr = _prom_get_order_cached(oid)
                if derr:
                    st.error(derr)
                elif content:
                    st.json(promua.order_detail_payload(content))
                else:
                    st.json(promua.order_detail_payload(order))

            ttn_ph = "ШКІ (Укрпошта)" if is_up else "ШКІ / номер відправлення"
            st.text_input(
                "ТТН для CRM",
                key=ttn_key,
                placeholder=ttn_ph,
                label_visibility="collapsed",
            )

        if card_n < len(order_items) - 1:
            st.markdown('<hr class="rz-order-divider" />', unsafe_allow_html=True)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if page > 1 and st.button("◀ Назад", key="prom_page_prev"):
            st.session_state.prom_page = page - 1
            st.session_state.pop("prom_orders_cache", None)
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
    with nav3:
        pc = meta.get("pages") or 1
        if page < int(pc) and st.button("Далі ▶", key="prom_page_next"):
            st.session_state.prom_page = page + 1
            st.session_state.pop("prom_orders_cache", None)
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
