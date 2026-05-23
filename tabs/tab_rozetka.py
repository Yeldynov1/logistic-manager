"""Вкладка «Rozetka» — замовлення з маркетплейсу."""
from __future__ import annotations

import streamlit as st

import config
import utils
from services import rozetka


def render_tab():
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
            st.rerun()
    with col_s:
        st.caption(
            "Замовлення **в обробці**. **Створити УП** — одразу ТТН Укрпошти в журналі; "
            "потім передайте ШКІ у Rozetka."
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

    linked = st.session_state.get("rozetka_linked_order_id")

    for order in orders:
        oid = order.get("id")
        if oid is None:
            continue
        oid = int(oid)
        status = rozetka.status_label(order)
        phone = str(order.get("user_phone") or "—")
        ttn = str(order.get("ttn") or "").strip()
        amount = order.get("cost_with_discount") or order.get("amount") or "—"
        created = str(order.get("created") or "")[:16]
        title = ""
        photos = order.get("items_photos")
        if isinstance(photos, list) and photos:
            title = str(photos[0].get("item_name") or "")[:60]

        hdr = f"**#{oid}** · {created} · {status}"
        if ttn:
            hdr += f" · ТТН `{ttn}`"
        if linked and int(linked) == oid:
            hdr += " · 🔗 для УП"

        with st.container(border=True):
            st.markdown(hdr)
            st.caption(f"📞 {phone} · **{amount}** грн" + (f" · {title}" if title else ""))

            ttn_key = f"rz_ttn_input_{oid}"
            if ttn_key not in st.session_state and ttn:
                st.session_state[ttn_key] = ttn

            c1, c2 = st.columns(2)
            with c1:
                if st.button("📋 Деталі", key=f"rz_det_{oid}", use_container_width=True):
                    st.session_state[f"rz_show_{oid}"] = not st.session_state.get(f"rz_show_{oid}")
                    st.rerun()
            with c2:
                if st.button("📮 Створити УП", key=f"rz_up_{oid}", use_container_width=True):
                    full, derr = rozetka.get_order(oid)
                    content = rozetka.order_content(full)
                    if derr or not content:
                        st.error(derr or "Не вдалося завантажити замовлення")
                    else:
                        prefill = rozetka.build_up_prefill(content)
                        st.session_state.rozetka_pending_create = prefill
                        st.session_state.up_journal_selected_day = utils.today_kyiv()
                        st.info(
                            f"Замовлення **#{oid}** — створення ТТН Укрпошти… "
                            "Відкрийте вкладку **УП ТТН** (або оновіть сторінку)."
                        )
                        st.rerun()

            if st.session_state.get(f"rz_show_{oid}"):
                full, derr = rozetka.get_order(oid)
                content = rozetka.order_content(full)
                if derr:
                    st.error(derr)
                elif content:
                    delivery = content.get("delivery") if isinstance(content.get("delivery"), dict) else {}
                    user = content.get("user") if isinstance(content.get("user"), dict) else {}
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
                        }
                    )

            st.text_input(
                "ТТН для Rozetka",
                key=ttn_key,
                placeholder="ШКІ після створення в УП",
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
                        st.rerun()

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if page > 1 and st.button("◀ Назад", key="rz_page_prev"):
            st.session_state.rz_page = page - 1
            st.session_state.pop("rozetka_orders_cache", None)
            st.rerun()
    with nav3:
        pc = meta.get("pageCount") or 1
        if page < int(pc) and st.button("Далі ▶", key="rz_page_next"):
            st.session_state.rz_page = page + 1
            st.session_state.pop("rozetka_orders_cache", None)
            st.rerun()
