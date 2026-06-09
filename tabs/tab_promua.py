"""Prom.ua tab: orders list (Rozetka-style cards) + створення ТТН УП."""
from __future__ import annotations

from html import escape

import streamlit as st

import config
import utils
from services import promua
from services import rozetka as rozetka_api
from ui import delivery_logos


def _prom_order_cache() -> dict:
    cache = st.session_state.get("prom_order_detail_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.prom_order_detail_cache = cache
    return cache


def _prom_sync_ttn_input(ttn_key: str, ship: dict) -> str:
    """Підставити відому ТТН у поле (Prom → journal/orders), перезаписати порожнє/застаріле."""
    prom_ttn = promua.normalize_ttn(ship.get("prom_ttn"))
    any_ttn = promua.normalize_ttn(ship.get("ttn"))
    target = prom_ttn or any_ttn
    if not target:
        return ""
    current = promua.normalize_ttn(st.session_state.get(ttn_key, ""))
    if prom_ttn:
        if current != prom_ttn:
            st.session_state[ttn_key] = prom_ttn
        return prom_ttn
    if not current or current != target:
        st.session_state[ttn_key] = target
    return target


def _prom_get_order_cached(oid: int) -> tuple[dict | None, str]:
    return promua.fetch_order_cached(oid)


def render_tab() -> None:
    last = st.session_state.pop("rozetka_last_up_result", None)
    if isinstance(last, dict):
        if last.get("ok") and last.get("bc"):
            st.success(
                f"✅ ТТН Укрпошти: **{last['bc']}**"
                + (
                    f" (Prom.ua #{last.get('oid')})"
                    if last.get("oid")
                    else ""
                )
                + " — див. також вкладку **УП ТТН**."
            )
        elif last.get("err"):
            st.error(f"❌ {last['err']}")
            st.caption("Відкрийте **УП ТТН** — форма заповнена для ручного доповнення.")

    config.apply_prom_secrets()
    st.subheader("🛍️ Prom.ua · замовлення")
    st.caption(
        "Підключення: `PROM_UA_TOKEN` у Secrets. "
        "На картці: **Створити УП** → **перевірте індекс і місто** у діалозі → **Передати ТТН у Prom.ua**. "
        "Версія UI: `prom-addr-1`."
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

    col_r, col_s = st.columns([1, 3])
    with col_r:
        if st.button("🔄 Оновити список", key="prom_refresh", use_container_width=True):
            utils.session_cache_invalidate("prom_orders_cache")
            st.session_state.pop("prom_orders_meta", None)
            st.session_state.pop("prom_orders_err", None)
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
    with col_s:
        st.caption(
            "На картці — **логотип служби доставки**. "
            "Кнопка **Створити УП** — лише для замовлень Укрпошти. "
            "Для НП/Meest — ТТН у своєму кабінеті, потім **Передати ТТН у Prom.ua**."
        )

    page = int(st.session_state.get("prom_page", 1))
    if not utils.session_cache_is_fresh("prom_orders_cache", ttl_sec=180):
        orders, meta, err = promua.fetch_orders(limit=limit_default, page=page)
        if err:
            st.session_state.prom_orders_err = err
            st.session_state.prom_orders_cache = []
            st.session_state.prom_orders_meta = {}
        else:
            st.session_state.prom_orders_cache = orders
            st.session_state.prom_orders_meta = meta
            st.session_state.prom_orders_err = ""
        utils.session_cache_touch("prom_orders_cache")

    err = str(st.session_state.get("prom_orders_err") or "")
    if err:
        st.error(f"Prom.ua API: {err}")
        return

    _prom_orders_list_fragment()


@st.fragment
def _prom_orders_list_fragment():
    page = int(st.session_state.get("prom_page", 1))
    orders = st.session_state.get("prom_orders_cache") or []
    meta = st.session_state.get("prom_orders_meta") or {}
    if meta:
        st.caption(
            f"Сторінка **{meta.get('page', page)}** / {meta.get('pages', '?')} · "
            f"всього **{meta.get('total', len(orders))}**"
        )

    if not orders:
        st.info("Немає замовлень або список порожній. Натисніть «Оновити список».")
        return

    delivery_logos.inject_rozetka_delivery_css()

    order_items: list[tuple[int, dict]] = []
    for order in orders:
        oid = promua.order_id(order)
        if oid is None:
            continue
        order_items.append((oid, order))

    kind_counts = delivery_logos.delivery_kind_counts(order_items, source="prom")
    delivery_kinds = delivery_logos.render_delivery_service_filter(
        key="prom_delivery_filter",
        counts=kind_counts,
        fragment=True,
    )

    linked = st.session_state.get("rozetka_linked_order_id")

    total_count = len(order_items)
    order_items = delivery_logos.filter_orders_by_delivery_kinds(
        order_items, delivery_kinds, source="prom"
    )
    if len(order_items) < total_count:
        st.caption(
            f"**{delivery_logos.active_delivery_filter_label(key='prom_delivery_filter')}** · "
            f"показано **{len(order_items)}** з **{total_count}**"
        )
    if not order_items:
        st.info(
            "Немає замовлень для цієї служби доставки. "
            "Натисніть **Всі** або «Оновити список»."
        )
        return

    for card_n, (oid, order) in enumerate(order_items):
        status = promua.status_label(order)
        phone = promua.phone(order) or "—"
        cached_detail = _prom_order_cache().get(str(oid))
        detail = cached_detail if isinstance(cached_detail, dict) else None
        inv_num = str(order.get("number") or "").strip()
        ship = promua.shipment_state_for_order(
            oid, order, detail=detail, invoice_number=inv_num
        )
        if not detail and isinstance(ship.get("prom_detail"), dict):
            detail = ship["prom_detail"]
        ttn = str(ship.get("ttn") or promua.resolve_order_ttn(order, detail, order_id=oid))
        amount = promua.order_amount_display(order, detail=detail)
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
        ttn_key = f"prom_ttn_input_{oid}"

        kind = promua.delivery_service_kind(order)
        card_slug = {"УП": "up", "НП": "np", "Meest": "meest", "Rozetka": "rz"}.get(kind, "other")

        status_line = escape(status)
        if ttn:
            src_lbl = promua.shipment_source_label(str(ship.get("source") or ""))
            src_note = f" · {escape(src_lbl)}" if src_lbl else ""
            status_line += f' · ТТН <code class="rz-ttn-code">{escape(ttn)}</code>{src_note}'
        if linked and int(linked) == oid:
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

            st.markdown("**📦 ТТН у Prom.ua**")
            prom_attached = bool(promua.normalize_ttn(ship.get("prom_ttn")))
            synced_ttn = _prom_sync_ttn_input(ttn_key, ship)
            if ship.get("has_ttn"):
                src_lbl = promua.shipment_source_label(str(ship.get("source") or ""))
                if prom_attached:
                    st.success(
                        f"ТТН **{synced_ttn or ttn}** уже в Prom.ua"
                        + (f" ({src_lbl})" if src_lbl else "")
                        + "."
                    )
                else:
                    st.info(
                        f"ТТН **{synced_ttn or ttn}** знайдено"
                        + (f" ({src_lbl})" if src_lbl else "")
                        + " — можна передати в Prom.ua."
                    )
            elif ship.get("has_draft"):
                st.warning(
                    "Є чернетка УП для цього замовлення — продовжіть на вкладці **УП ТТН**."
                )
            ttn_ph = (
                "ШКІ після створення в УП"
                if is_up
                else f"ШКІ ({kind} / інший кабінет)"
            )
            overwrite_key = f"prom_ttn_overwrite_{oid}"
            input_ttn = promua.normalize_ttn(st.session_state.get(ttn_key, ""))
            existing_any = promua.normalize_ttn(ship.get("ttn"))
            show_overwrite = bool(
                not prom_attached
                and existing_any
                and input_ttn
                and existing_any != input_ttn
            )
            if show_overwrite:
                st.checkbox(
                    f"Замінити наявну ТТН ({existing_any} → {input_ttn or 'новий'})",
                    key=overwrite_key,
                )
            col_ttn, col_send = st.columns([5, 3])
            with col_ttn:
                st.text_input(
                    "Номер ТТН",
                    key=ttn_key,
                    placeholder=ttn_ph,
                    label_visibility="collapsed",
                    disabled=prom_attached,
                )
            with col_send:
                send_ttn = st.button(
                    "✅ Передати ТТН у Prom.ua",
                    key=f"prom_send_{oid}",
                    type="primary",
                    use_container_width=True,
                    disabled=prom_attached,
                )
            if send_ttn:
                ttn_val = str(st.session_state.get(ttn_key, "")).strip()
                content, derr = _prom_get_order_cached(oid)
                src = content if isinstance(content, dict) else order
                ok, verr, _existing = promua.validate_send_declaration(
                    oid,
                    ttn_val,
                    order=src if isinstance(src, dict) else order,
                    detail=detail,
                    invoice_number=inv_num,
                    allow_overwrite=bool(st.session_state.get(overwrite_key)),
                )
                if not ttn_val:
                    st.warning("Введіть номер ТТН.")
                elif not ok:
                    st.warning(verr)
                elif not isinstance(src, dict):
                    st.error(derr or "Не вдалося завантажити замовлення")
                elif _existing and promua.normalize_ttn(_existing) == promua.normalize_ttn(ttn_val):
                    st.info(f"ТТН {ttn_val} уже прикріплена до замовлення #{oid}.")
                else:
                    _, serr = promua.save_declaration_id(
                        oid, ttn_val, order=src
                    )
                    if serr:
                        st.error(serr)
                    else:
                        st.success(
                            f"ТТН {ttn_val} передано в замовлення Prom.ua #{oid}"
                        )
                        st.session_state.pop(overwrite_key, None)
                        utils.session_cache_invalidate("prom_orders_cache")
                        st.session_state.pop("prom_order_detail_cache", None)
                        st.rerun()

            if is_up:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📋 Деталі", key=f"prom_det_{oid}", use_container_width=True):
                        st.session_state[f"prom_show_{oid}"] = not st.session_state.get(
                            f"prom_show_{oid}"
                        )
                        st.rerun()
                with c2:
                    up_blocked = promua.block_up_create_message(
                        oid,
                        order,
                        detail=detail,
                        invoice_number=inv_num,
                    )
                    if st.button(
                        "📮 Створити УП",
                        key=f"prom_up_{oid}",
                        use_container_width=True,
                        disabled=bool(up_blocked),
                    ):
                        content, derr = _prom_get_order_cached(oid)
                        if derr or not content:
                            st.error(derr or "Не вдалося завантажити замовлення")
                        elif not promua.is_ukrposhta_order(content):
                            st.error(
                                f"Це не Укрпошта ({promua.delivery_service_label(content)}). "
                                "Створіть ТТН у кабінеті обраної служби."
                            )
                        else:
                            block = promua.block_up_create_message(
                                oid,
                                content,
                                detail=content,
                                invoice_number=inv_num,
                            )
                            if block:
                                st.warning(block)
                            else:
                                prefill = promua.build_up_prefill(content)
                                inv_hint = str(
                                    prefill.get("invoice_number")
                                    or order.get("number")
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
                if st.button("📋 Деталі", key=f"prom_det_{oid}", use_container_width=True):
                    st.session_state[f"prom_show_{oid}"] = not st.session_state.get(
                        f"prom_show_{oid}"
                    )
                    st.rerun()

            if st.session_state.get(f"prom_show_{oid}"):
                content, derr = _prom_get_order_cached(oid)
                if derr:
                    st.error(derr)
                elif content:
                    st.json(promua.order_detail_payload(content))
                else:
                    st.json(promua.order_detail_payload(order))

        if card_n < len(order_items) - 1:
            st.markdown('<hr class="rz-order-divider" />', unsafe_allow_html=True)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if page > 1 and st.button("◀ Назад", key="prom_page_prev"):
            st.session_state.prom_page = page - 1
            utils.session_cache_invalidate("prom_orders_cache")
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
    with nav3:
        pc = meta.get("pages") or 1
        if page < int(pc) and st.button("Далі ▶", key="prom_page_next"):
            st.session_state.prom_page = page + 1
            utils.session_cache_invalidate("prom_orders_cache")
            st.session_state.pop("prom_order_detail_cache", None)
            st.rerun()
