"""Вкладка «Епіцентр» — замовлення з Merchant API."""
from __future__ import annotations

from html import escape

import streamlit as st

import config
import utils
from services import epicentr
from ui import delivery_logos


def _epic_order_cache() -> dict:
    cache = st.session_state.get("epic_order_detail_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.epic_order_detail_cache = cache
    return cache


def _epic_sync_ttn_input(ttn_key: str, ship: dict) -> str:
    epic_ttn = epicentr.normalize_ttn(ship.get("epic_ttn"))
    any_ttn = epicentr.normalize_ttn(ship.get("ttn"))
    target = epic_ttn or any_ttn
    if not target:
        return ""
    current = epicentr.normalize_ttn(st.session_state.get(ttn_key, ""))
    if epic_ttn:
        if current != epic_ttn:
            st.session_state[ttn_key] = epic_ttn
        return epic_ttn
    if not current or current != target:
        st.session_state[ttn_key] = target
    return target


def _epic_get_order_cached(oid: str) -> tuple[dict | None, str]:
    cache = _epic_order_cache()
    key = str(oid).strip()
    if key in cache:
        val = cache.get(key)
        if isinstance(val, dict):
            return val, ""
    full, err = epicentr.fetch_order(key)
    if err:
        return None, err
    if isinstance(full, dict):
        cache[key] = full
        return full, ""
    return None, "Не вдалося завантажити замовлення"


def render_tab() -> None:
    last = st.session_state.pop("rozetka_last_up_result", None)
    if isinstance(last, dict):
        if last.get("ok") and last.get("bc"):
            st.success(
                f"✅ ТТН Укрпошти: **{last['bc']}**"
                + (
                    f" (Епіцентр #{last.get('oid')})"
                    if last.get("oid")
                    else ""
                )
                + " — див. також вкладку **УП ТТН**."
            )
        elif last.get("err"):
            st.error(f"❌ {last['err']}")
            st.caption("Відкрийте **УП ТТН** — форма заповнена для ручного доповнення.")

    config.apply_epicentr_secrets()
    st.subheader("🏪 Епіцентр · замовлення")
    st.caption(
        "Підключення: `EPICENTR_API_TOKEN` у Secrets (кабінет продавця → Налаштування → API). "
        "На картці: **Створити УП** → перевірте адресу → **Передати ТТН у Епіцентр**."
    )

    if not epicentr.token_configured():
        diag = config.epicentr_secret_diagnostics()
        st.warning(
            "Токен Епіцентр не знайдено. У **Streamlit Cloud → Settings → Secrets** додайте:\n\n"
            "```toml\nEPICENTR_API_TOKEN = \"ваш_api_token\"\n"
            "EPICENTR_IMPORT_LIMIT = 50\n```\n\n"
            "Після збереження натисніть **Reboot app**."
        )
        with st.expander("Діагностика Secrets"):
            st.write(f"Токен: **{diag['token']}**")
            st.write(f"Знайдені ключі: {diag['found_keys']}")
            st.write(f"Секції з «epic»: {diag['epic_sections']}")
            st.caption(diag["hint"])
        return

    limit_default = int(getattr(config, "EPICENTR_IMPORT_LIMIT", 50) or 50)

    col_r, col_s = st.columns([1, 3])
    with col_r:
        if st.button("🔄 Оновити список", key="epic_refresh", use_container_width=True):
            utils.session_cache_invalidate("epic_orders_cache")
            st.session_state.pop("epic_orders_meta", None)
            st.session_state.pop("epic_orders_err", None)
            st.session_state.pop("epic_order_detail_cache", None)
            st.session_state.pop("epic_orders_cursor", None)
            st.session_state.pop("epic_orders_cursor_stack", None)
            st.rerun()
    with col_s:
        st.caption(
            "Список — активні статуси (нові / підтверджені / відправлені). "
            "Кнопка **Створити УП** — лише для Укрпошти."
        )

    cursor = str(st.session_state.get("epic_orders_cursor") or "").strip() or None
    if not utils.session_cache_is_fresh("epic_orders_cache", ttl_sec=180):
        orders, meta, err = epicentr.fetch_orders(limit=limit_default, cursor=cursor)
        if err:
            st.session_state.epic_orders_err = err
            st.session_state.epic_orders_cache = []
            st.session_state.epic_orders_meta = {}
        else:
            st.session_state.epic_orders_cache = orders
            st.session_state.epic_orders_meta = meta
            st.session_state.epic_orders_err = ""
        utils.session_cache_touch("epic_orders_cache")

    err = str(st.session_state.get("epic_orders_err") or "")
    if err:
        st.error(f"Епіцентр API: {err}")
        return

    _epic_orders_list_fragment()


@st.fragment
def _epic_orders_list_fragment():
    orders = st.session_state.get("epic_orders_cache") or []
    meta = st.session_state.get("epic_orders_meta") or {}
    if meta:
        st.caption(f"Завантажено **{len(orders)}** замовлень · ліміт **{meta.get('limit', '?')}**")

    if not orders:
        st.info("Немає замовлень або список порожній. Натисніть «Оновити список».")
        return

    delivery_logos.inject_rozetka_delivery_css()

    order_items: list[tuple[str, dict]] = []
    for order in orders:
        oid = epicentr.order_uuid(order)
        if not oid:
            continue
        order_items.append((oid, order))

    kind_counts = delivery_logos.delivery_kind_counts(order_items, source="epicentr")
    delivery_kinds = delivery_logos.render_delivery_service_filter(
        key="epic_delivery_filter",
        counts=kind_counts,
        fragment=True,
    )

    linked = st.session_state.get("rozetka_linked_order_id")
    total_count = len(order_items)
    order_items = delivery_logos.filter_orders_by_delivery_kinds(
        order_items, delivery_kinds, source="epicentr"
    )
    if len(order_items) < total_count:
        st.caption(
            f"**{delivery_logos.active_delivery_filter_label(key='epic_delivery_filter')}** · "
            f"показано **{len(order_items)}** з **{total_count}**"
        )
    if not order_items:
        st.info("Немає замовлень для цієї служби доставки.")
        return

    for card_n, (oid, order) in enumerate(order_items):
        num = epicentr.order_number(order)
        status = epicentr.status_label(order)
        phone = epicentr.phone(order) or "—"
        cached_detail = _epic_order_cache().get(oid)
        detail = cached_detail if isinstance(cached_detail, dict) else None
        ship = epicentr.shipment_state_for_order(
            oid, order, detail=detail, invoice_number=num
        )
        if not detail and isinstance(ship.get("epic_detail"), dict):
            detail = ship["epic_detail"]
        ttn = str(ship.get("ttn") or epicentr.order_ttn(order, detail))
        amount = epicentr.order_amount_display(order, detail=detail)
        created = epicentr.order_created_display(order)
        recipient = epicentr.recipient_name(order)
        pay_form = epicentr.payment_label(order)
        if epicentr.is_cod_payment_order(order):
            pay_form = f"{pay_form} (при отриманні)".strip()
        pay_status = epicentr.payment_status_label(order)
        title = epicentr.product_title(order)
        svc_logo = delivery_logos.badge_html_for_epic_order(order)
        place_hint = epicentr.delivery_place_hint(order)
        is_up = epicentr.is_ukrposhta_order(order)
        ttn_key = f"epic_ttn_input_{oid}"

        kind = epicentr.delivery_service_kind(order)
        card_slug = {"УП": "up", "НП": "np", "Meest": "meest", "Rozetka": "rz"}.get(kind, "other")

        status_line = escape(status)
        if ttn:
            src_lbl = epicentr.shipment_source_label(str(ship.get("source") or ""))
            src_note = f" · {escape(src_lbl)}" if src_lbl else ""
            status_line += f' · ТТН <code class="rz-ttn-code">{escape(ttn)}</code>{src_note}'
        if linked and str(linked) == str(num or oid):
            status_line += " · 🔗 чернетка УП"
        if ship.get("has_draft") and not ttn:
            status_line += " · 📝 чернетка УП"

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
                f'<div class="rz-order-meta">#{escape(num or oid[:8])} · {escape(created)}</div>'
                f"{svc_logo}"
                f"</div>"
                f'<div class="rz-order-status">{status_line}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:1.45rem;font-weight:800;line-height:1.2;color:#16A34A;'>"
                f"Замовлення #{escape(num or oid[:8])}"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(f"**Отримувач:** {recipient}")
            st.markdown(
                f"**Сума:** `{amount}` грн · **Форма оплати:** {pay_form}"
                + (f" · **Статус оплати:** {pay_status}" if pay_status else "")
            )
            st.caption(cap)

            st.markdown("**📦 ТТН у Епіцентр**")
            epic_attached = bool(epicentr.normalize_ttn(ship.get("epic_ttn")))
            synced_ttn = _epic_sync_ttn_input(ttn_key, ship)
            if ship.get("has_real_ttn"):
                src_lbl = epicentr.shipment_source_label(str(ship.get("source") or ""))
                if epic_attached:
                    st.success(
                        f"ТТН **{synced_ttn or ttn}** уже в Епіцентр"
                        + (f" ({src_lbl})" if src_lbl else "")
                        + "."
                    )
                else:
                    st.info(
                        f"ТТН **{synced_ttn or ttn}** знайдено"
                        + (f" ({src_lbl})" if src_lbl else "")
                        + " — можна передати в Епіцентр."
                    )
            elif ship.get("has_draft"):
                st.warning("Є чернетка УП — продовжіть на вкладці **УП ТТН**.")

            ttn_ph = "ШКІ після створення в УП" if is_up else f"ШКІ ({kind})"
            col_ttn, col_send = st.columns([5, 3])
            with col_ttn:
                st.text_input(
                    "Номер ТТН",
                    key=ttn_key,
                    placeholder=ttn_ph,
                    label_visibility="collapsed",
                    disabled=epic_attached,
                )
            with col_send:
                send_ttn = st.button(
                    "✅ Передати ТТН у Епіцентр",
                    key=f"epic_send_{oid}",
                    type="primary",
                    use_container_width=True,
                    disabled=epic_attached,
                )
            if send_ttn:
                ttn_val = str(st.session_state.get(ttn_key, "")).strip()
                if not ttn_val:
                    st.warning("Введіть номер ТТН.")
                else:
                    _, serr = epicentr.save_shipment_number(oid, ttn_val)
                    if serr:
                        st.error(serr)
                    else:
                        st.success(f"ТТН {ttn_val} передано в замовлення Епіцентр #{num or oid[:8]}")
                        utils.session_cache_invalidate("epic_orders_cache")
                        st.session_state.pop("epic_order_detail_cache", None)
                        st.rerun()

            if is_up:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📋 Деталі", key=f"epic_det_{oid}", use_container_width=True):
                        st.session_state[f"epic_show_{oid}"] = not st.session_state.get(
                            f"epic_show_{oid}"
                        )
                        st.rerun()
                with c2:
                    up_blocked = epicentr.block_up_create_message(
                        oid, order, detail=detail, invoice_number=num
                    )
                    if st.button(
                        "📮 Створити УП",
                        key=f"epic_up_{oid}",
                        use_container_width=True,
                        disabled=bool(up_blocked),
                    ):
                        content, derr = _epic_get_order_cached(oid)
                        if derr or not content:
                            st.error(derr or "Не вдалося завантажити замовлення")
                        elif not epicentr.is_ukrposhta_order(content):
                            st.error(
                                f"Це не Укрпошта ({epicentr.delivery_service_label(content)}). "
                                "Створіть ТТН у кабінеті обраної служби."
                            )
                        else:
                            block = epicentr.block_up_create_message(
                                oid, content, detail=content, invoice_number=num
                            )
                            if block:
                                st.warning(block)
                            else:
                                prefill = epicentr.build_up_prefill(content)
                                inv_hint = str(
                                    prefill.get("invoice_number")
                                    or num
                                    or ""
                                ).strip()
                                st.session_state.rozetka_up_dialog = {
                                    "prefill": prefill,
                                    "ttn_key": ttn_key,
                                    "invoice_hint": inv_hint,
                                }
                                st.rerun()
                    if up_blocked:
                        st.caption(up_blocked)
            else:
                if st.button("📋 Деталі", key=f"epic_det_{oid}", use_container_width=True):
                    st.session_state[f"epic_show_{oid}"] = not st.session_state.get(
                        f"epic_show_{oid}"
                    )
                    st.rerun()

            if st.session_state.get(f"epic_show_{oid}"):
                content, derr = _epic_get_order_cached(oid)
                if derr:
                    st.error(derr)
                elif content:
                    st.json(epicentr.order_detail_payload(content))
                else:
                    st.json(epicentr.order_detail_payload(order))

        if card_n < len(order_items) - 1:
            st.markdown('<hr class="rz-order-divider" />', unsafe_allow_html=True)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        stack = st.session_state.get("epic_orders_cursor_stack")
        if not isinstance(stack, list):
            stack = []
        if stack and st.button("◀ Назад", key="epic_page_prev"):
            st.session_state.epic_orders_cursor = stack.pop()
            st.session_state.epic_orders_cursor_stack = stack
            utils.session_cache_invalidate("epic_orders_cache")
            st.session_state.pop("epic_order_detail_cache", None)
            st.rerun()
    with nav3:
        nxt = str(meta.get("next") or "").strip()
        if nxt and st.button("Далі ▶", key="epic_page_next"):
            cur = str(st.session_state.get("epic_orders_cursor") or "").strip()
            stack = st.session_state.get("epic_orders_cursor_stack")
            if not isinstance(stack, list):
                stack = []
            if cur:
                stack.append(cur)
            st.session_state.epic_orders_cursor_stack = stack
            st.session_state.epic_orders_cursor = nxt
            utils.session_cache_invalidate("epic_orders_cache")
            st.session_state.pop("epic_order_detail_cache", None)
            st.rerun()
