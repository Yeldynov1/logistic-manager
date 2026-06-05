"""Вкладка «Rozetka» — замовлення з маркетплейсу."""
from __future__ import annotations

from html import escape

import streamlit as st

import config
import utils
from services import rozetka
from ui import delivery_logos


def _rz_order_cache() -> dict:
    cache = st.session_state.get("rozetka_order_detail_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.rozetka_order_detail_cache = cache
    return cache


def _rz_ttns_cache() -> dict:
    cache = st.session_state.get("rozetka_ttns_info_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state.rozetka_ttns_info_cache = cache
    return cache


def _rz_get_order_cached(oid: int) -> tuple[dict | None, str]:
    cache = _rz_order_cache()
    key = str(int(oid))
    if key in cache:
        val = cache.get(key)
        if isinstance(val, dict):
            return val, ""
    full, err = rozetka.get_order(oid)
    if err:
        return None, err
    content = rozetka.order_content(full)
    if not content:
        return None, "Не вдалося завантажити замовлення"
    cache[key] = content
    return content, ""


def _rz_get_ttns_user_info_cached(oid: int) -> tuple[dict, str]:
    cache = _rz_ttns_cache()
    key = str(int(oid))
    if key in cache:
        val = cache.get(key)
        if isinstance(val, dict):
            return val, ""
    data, err = rozetka.fetch_ttns_user_info(oid)
    if err:
        return {}, err
    if isinstance(data, dict):
        cache[key] = data
        return data, ""
    return {}, ""


@st.dialog("Створення ТТН Укрпошти")
def _rozetka_up_invoice_dialog():
    dlg = st.session_state.get("rozetka_up_dialog")
    if not isinstance(dlg, dict):
        return
    prefill = dlg.get("prefill")
    if not isinstance(prefill, dict):
        st.session_state.pop("rozetka_up_dialog", None)
        return

    def _dlg_int(val, default: int) -> int:
        try:
            return int(val)
        except Exception:
            return default

    oid = prefill.get("prom_order_id") or prefill.get("rozetka_order_id")
    src = "Prom.ua" if prefill.get("prom_order_id") is not None else "Rozetka"
    st.caption(
        f"{src} **#{oid}** · {prefill.get('firstname', '')} {prefill.get('lastname', '')}".strip()
    )
    if prefill.get("prom_order_id") is not None:
        pc = str(prefill.get("postcode") or "").strip()
        city = str(prefill.get("city") or "").strip()
        region = str(prefill.get("region") or "").strip()
        branch = str(prefill.get("place_number") or "").strip()
        addr_bits = [b for b in (pc, region, city) if b]
        addr_line = ", ".join(addr_bits)
        if branch:
            addr_line += f" · відд. №{branch}"
        if addr_line:
            st.info(f"**Адреса доставки (перевірте):** {addr_line}")
        elif not pc:
            st.warning(
                "Індекс не визначено з Prom.ua — після створення перевірте вкладку **УП ТТН** "
                "або скасуйте, якщо адреса невірна."
            )
    inv_key = f"rozetka_dialog_invoice_{oid}"
    if inv_key not in st.session_state:
        hint = str(dlg.get("invoice_hint") or prefill.get("invoice_number") or "").strip()
        st.session_state[inv_key] = hint

    invoice = st.text_input(
        "Номер накладної",
        key=inv_key,
        placeholder="наприклад 012345",
        help="Збережеться в таблиці Orders і в «Дод. інфо» відправлення УП (до 40 символів).",
    )

    w_key = f"rozetka_dialog_weight_{oid}"
    ln_key = f"rozetka_dialog_len_{oid}"
    wid_key = f"rozetka_dialog_wid_{oid}"
    h_key = f"rozetka_dialog_h_{oid}"
    if w_key not in st.session_state:
        st.session_state[w_key] = _dlg_int(prefill.get("weight_g"), 500)
    if ln_key not in st.session_state:
        st.session_state[ln_key] = _dlg_int(prefill.get("length_cm"), 30)
    if wid_key not in st.session_state:
        st.session_state[wid_key] = _dlg_int(prefill.get("width_cm"), 20)
    if h_key not in st.session_state:
        st.session_state[h_key] = _dlg_int(prefill.get("height_cm"), 10)

    st.caption("Габарити та вага (за замовчуванням підставлено автоматично):")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("Вага, г", min_value=1, max_value=30000, step=50, key=w_key)
        st.number_input("Довжина, см", min_value=1, max_value=200, step=1, key=ln_key)
    with c2:
        st.number_input("Ширина, см", min_value=1, max_value=200, step=1, key=wid_key)
        st.number_input("Висота, см", min_value=1, max_value=200, step=1, key=h_key)

    c_ok, c_cancel = st.columns(2)
    with c_ok:
        proceed = st.button("Створити ТТН", type="primary", use_container_width=True)
    with c_cancel:
        cancel = st.button("Скасувати", use_container_width=True)

    if cancel:
        st.session_state.pop("rozetka_up_dialog", None)
        st.session_state.pop(inv_key, None)
        for k in (w_key, ln_key, wid_key, h_key):
            st.session_state.pop(k, None)
        st.rerun()

    if proceed:
        merged = rozetka.merge_dialog_inputs_into_prefill(
            prefill,
            invoice_raw=invoice,
            weight_g=st.session_state.get(w_key, 500),
            length_cm=st.session_state.get(ln_key, 30),
            width_cm=st.session_state.get(wid_key, 20),
            height_cm=st.session_state.get(h_key, 10),
        )
        inv_norm = str(merged.get("invoice_number") or "").strip()
        if inv_norm:
            st.session_state.pop(inv_key, None)
            for k in (w_key, ln_key, wid_key, h_key):
                st.session_state.pop(k, None)
            st.session_state.rozetka_pending_create = merged
            st.session_state.rozetka_pending_ttn_key = dlg.get("ttn_key")
            st.session_state.pop("rozetka_up_dialog", None)
            st.session_state.up_journal_selected_day = utils.today_kyiv()
            st.toast(f"Накладна {inv_norm} збережена", icon="📋")
            st.rerun()
        else:
            st.warning("Введіть номер накладної.")


def render_tab():
    last = st.session_state.pop("rozetka_last_up_result", None)
    if isinstance(last, dict):
        if last.get("ok") and last.get("bc"):
            st.success(
                f"✅ ТТН Укрпошти: **{last['bc']}**"
                + (f" (замовлення #{last.get('oid')})" if last.get("oid") else "")
                + " — див. також вкладку **УП ТТН**."
            )
        elif last.get("err"):
            st.error(f"❌ {last['err']}")
            st.caption("Відкрийте **УП ТТН** — форма заповнена для ручного доповнення.")

    st.subheader("🛒 Rozetka · замовлення")
    st.caption(
        "Підключення: **ROZETKA_USERNAME** і **ROZETKA_PASSWORD** у Secrets "
        "(пароль звичайним текстом). Токен API діє ~24 год."
    )

    if not rozetka.credentials_configured():
        st.warning(
            "Додайте у Streamlit Secrets:\n\n"
            "```toml\nROZETKA_USERNAME = \"логін_кабінету_продавця\"\n"
            "ROZETKA_PASSWORD = \"пароль\"\n"
            "# опційно: статус при передачі ТТН (за замовч. 3)\n"
            "ROZETKA_TTN_STATUS = 3\n```"
        )
        return

    col_r, col_s = st.columns([1, 3])
    with col_r:
        if st.button("🔄 Оновити список", key="rz_refresh", use_container_width=True):
            st.session_state.pop("rozetka_orders_cache", None)
            st.session_state.pop("rozetka_orders_err", None)
            st.session_state.pop("rozetka_order_detail_cache", None)
            st.session_state.pop("rozetka_ttns_info_cache", None)
            st.rerun()
    with col_s:
        st.caption(
            "Замовлення **в обробці**. На картці — **логотип служби доставки**. "
            "Кнопка **Створити УП** — лише для замовлень Укрпошти. "
            "Для НП/Meest — ТТН у своєму кабінеті, потім **Передати ТТН у Rozetka**."
        )

    page = int(st.session_state.get("rz_page", 1))
    if "rozetka_orders_cache" not in st.session_state:
        data, err = rozetka.search_orders(page=page)
        if err:
            st.session_state.rozetka_orders_err = err
            st.session_state.rozetka_orders_cache = []
        else:
            st.session_state.rozetka_orders_cache = rozetka.orders_from_search_response(data)
            st.session_state.rozetka_orders_meta = rozetka.search_meta(data)
            st.session_state.rozetka_orders_err = ""

    err = str(st.session_state.get("rozetka_orders_err") or "")
    if err:
        st.error(f"Rozetka API: {err}")
        if st.button("Спробувати авторизацію ще раз", key="rz_reauth"):
            st.session_state.pop("rozetka_access_token", None)
            st.session_state.pop("rozetka_orders_cache", None)
            st.session_state.pop("rozetka_order_detail_cache", None)
            st.session_state.pop("rozetka_ttns_info_cache", None)
            st.rerun()
        return

    orders = st.session_state.get("rozetka_orders_cache") or []
    meta = st.session_state.get("rozetka_orders_meta") or {}
    if meta:
        st.caption(
            f"Сторінка **{meta.get('currentPage', page)}** / {meta.get('pageCount', '?')} · "
            f"всього **{meta.get('totalCount', len(orders))}**"
        )

    if not orders:
        st.info("Немає замовлень у статусі «в обробці» або список порожній.")
        return

    delivery_logos.inject_rozetka_delivery_css()
    linked = st.session_state.get("rozetka_linked_order_id")

    order_items: list[tuple[int, dict]] = []
    for order in orders:
        oid = order.get("id")
        if oid is None:
            continue
        order_items.append((int(oid), order))

    for card_n, (oid, order) in enumerate(order_items):
        status = rozetka.status_label(order)
        phone = str(order.get("user_phone") or "—")
        ttn = str(order.get("ttn") or "").strip()
        amount = order.get("cost_with_discount") or order.get("amount") or "—"
        created = str(order.get("created") or "")[:16]
        delivery = order.get("delivery") if isinstance(order.get("delivery"), dict) else {}
        user = order.get("user") if isinstance(order.get("user"), dict) else {}
        recipient = str(
            delivery.get("recipient_title")
            or user.get("title")
            or user.get("name")
            or "—"
        ).strip()
        pay_form = str(order.get("payment_type_name") or order.get("payment_type") or "—").strip() or "—"
        pay_status = str(
            (order.get("status_payment") or {}).get("name")
            if isinstance(order.get("status_payment"), dict)
            else (order.get("payment_status") or "")
        ).strip()
        if rozetka.is_cod_payment_order(order):
            pay_form = f"{pay_form} (при отриманні)".strip()
        title = ""
        photos = order.get("items_photos")
        if isinstance(photos, list) and photos:
            title = str(photos[0].get("item_name") or "")[:60]

        svc_logo = delivery_logos.badge_html_for_order(order)
        svc_name = rozetka.delivery_service_label(order)
        place_hint = rozetka.delivery_place_hint(order)
        is_up = rozetka.is_ukrposhta_order(order)

        kind = rozetka.delivery_service_kind(svc_name)
        card_slug = {"УП": "up", "НП": "np", "Meest": "meest", "Rozetka": "rz"}.get(
            kind, "other"
        )

        status_line = escape(status)
        if ttn:
            status_line += f' · ТТН <code class="rz-ttn-code">{escape(ttn)}</code>'
        if linked and int(linked) == oid:
            status_line += " · 🔗 чернетка УП"

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

            ttn_key = f"rz_ttn_input_{oid}"
            if ttn_key not in st.session_state and ttn:
                st.session_state[ttn_key] = ttn

            if is_up:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("📋 Деталі", key=f"rz_det_{oid}", use_container_width=True):
                        st.session_state[f"rz_show_{oid}"] = not st.session_state.get(
                            f"rz_show_{oid}"
                        )
                        st.rerun()
                with c2:
                    if st.button(
                        "📮 Створити УП",
                        key=f"rz_up_{oid}",
                        use_container_width=True,
                    ):
                        # Беремо з локального кешу або підтягуємо повне замовлення один раз.
                        content, derr = _rz_get_order_cached(oid)
                        if derr or not content:
                            st.error(derr or "Не вдалося завантажити замовлення")
                        elif not rozetka.is_ukrposhta_order(content):
                            st.error(
                                f"Це не Укрпошта ({rozetka.delivery_service_label(content)}). "
                                "Створіть ТТН у кабінеті обраної служби."
                            )
                        else:
                            prefill = rozetka.build_up_prefill(content)
                            inv_hint = ""
                            inv_raw = content.get("payment_invoice_id")
                            if inv_raw not in (None, "", 0, "0"):
                                inv_hint = str(inv_raw).strip()
                            st.session_state.rozetka_up_dialog = {
                                "prefill": prefill,
                                "ttn_key": ttn_key,
                                "invoice_hint": inv_hint,
                            }
                            st.rerun()
            else:
                if st.button("📋 Деталі", key=f"rz_det_{oid}", use_container_width=True):
                    st.session_state[f"rz_show_{oid}"] = not st.session_state.get(
                        f"rz_show_{oid}"
                    )
                    st.rerun()

            if st.session_state.get(f"rz_show_{oid}"):
                content, derr = _rz_get_order_cached(oid)
                if derr:
                    st.error(derr)
                elif content:
                    delivery = content.get("delivery") if isinstance(content.get("delivery"), dict) else {}
                    user = content.get("user") if isinstance(content.get("user"), dict) else {}
                    ttns_extra, _ = _rz_get_ttns_user_info_cached(oid)
                    st.json(
                        {
                            "id": content.get("id"),
                            "status": rozetka.status_label(content),
                            "phone": content.get("user_phone"),
                            "ttn": content.get("ttn"),
                            "recipient": delivery.get("recipient_title") or user.get("title"),
                            "delivery_service": (
                                (content.get("delivery_service") or {}).get("name")
                                if isinstance(content.get("delivery_service"), dict)
                                else None
                            ),
                            "place_number": delivery.get("place_number"),
                            "address": {
                                "street": delivery.get("place_street"),
                                "house": delivery.get("place_house"),
                                "flat": delivery.get("place_flat"),
                                "city": (delivery.get("city") or {}).get("name")
                                if isinstance(delivery.get("city"), dict)
                                else None,
                            },
                            "purchases_count": len(content.get("purchases") or []),
                            "payment_type": content.get("payment_type"),
                            "payment_type_name": content.get("payment_type_name"),
                            "payment_status": content.get("payment_status"),
                            "status_payment": content.get("status_payment"),
                            "cost_with_discount": content.get("cost_with_discount"),
                            "ttns_payment_method": ttns_extra.get("payment_method"),
                            "ttns_amount": ttns_extra.get("amount"),
                            "postpay_uah": rozetka.postpay_uah_from_order(content, ttns_extra),
                        }
                    )

            ttn_ph = (
                "ШКІ після створення в УП"
                if is_up
                else f"ШКІ ({rozetka.delivery_service_kind(svc_name)} / інший кабінет)"
            )
            st.text_input(
                "ТТН для Rozetka",
                key=ttn_key,
                placeholder=ttn_ph,
                label_visibility="collapsed",
            )
            stat_key = f"rz_status_{oid}"
            if stat_key not in st.session_state:
                st.session_state[stat_key] = config.ROZETKA_TTN_STATUS

            if st.button(f"✅ Передати ТТН у Rozetka", key=f"rz_send_{oid}", use_container_width=True):
                ttn_val = str(st.session_state.get(ttn_key, "")).strip()
                if not ttn_val:
                    st.warning("Введіть номер ТТН.")
                else:
                    status_id = int(st.session_state.get(stat_key, config.ROZETKA_TTN_STATUS))
                    _, uerr = rozetka.update_order(oid, status=status_id, ttn=ttn_val)
                    if uerr:
                        st.error(uerr)
                    else:
                        st.success(f"ТТН {ttn_val} передано в замовлення #{oid}")
                        st.session_state.pop("rozetka_orders_cache", None)
                        st.session_state.pop("rozetka_order_detail_cache", None)
                        st.session_state.pop("rozetka_ttns_info_cache", None)
                        st.rerun()

        if card_n < len(order_items) - 1:
            st.markdown('<hr class="rz-order-divider" />', unsafe_allow_html=True)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if page > 1 and st.button("◀ Назад", key="rz_page_prev"):
            st.session_state.rz_page = page - 1
            st.session_state.pop("rozetka_orders_cache", None)
            st.session_state.pop("rozetka_order_detail_cache", None)
            st.session_state.pop("rozetka_ttns_info_cache", None)
            st.rerun()
    with nav3:
        pc = meta.get("pageCount") or 1
        if page < int(pc) and st.button("Далі ▶", key="rz_page_next"):
            st.session_state.rz_page = page + 1
            st.session_state.pop("rozetka_orders_cache", None)
            st.session_state.pop("rozetka_order_detail_cache", None)
            st.session_state.pop("rozetka_ttns_info_cache", None)
            st.rerun()
