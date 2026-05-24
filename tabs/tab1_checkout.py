"""Вкладка «Видати чек» (tab1)."""
from __future__ import annotations

import hashlib
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st

import sheets
import ui_theme
import utils
from core.audit import audit_log, audit_lookup_receipt_sum
from services.checkbox_archive import (
    fetch_checkbox_archive,
    tab1_unattached_receipt_picker_rows,
)
from ui.components import render_copyable_invoice, render_smart_buttons

_CHECKBOX_RECEIPT_HOST = "check.checkbox.ua/"
_CHECK_SMS_PREFIX = "Magazin Alius. Vash chek: "
_CHECK_SMS_TEXT = _CHECK_SMS_PREFIX + "{link}"


def check_sms_text(link: str) -> str:
    return _CHECK_SMS_TEXT.format(link=str(link or "").strip())


def tab1_sms_prefill() -> str:
    """Готовий текст до вставки посилання на чек."""
    return _CHECK_SMS_PREFIX


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
        return check_sms_text(link)
    if len(msg) > 5 and msg.lower() != "nan":
        if _CHECKBOX_RECEIPT_HOST in msg.lower():
            return tab1_sms_prefill()
        return msg
    return tab1_sms_prefill()


def _tab1_attach_check(
    idx,
    row,
    link: str,
    audit_action: str,
    *,
    ship_cost=None,
    receipt_sum=None,
) -> None:
    """Швидко прикріпити чек: текст одразу, журнал і збереження — у фоні."""
    link = str(link or "").strip()
    if len(link) < 5:
        return
    wid = tab1_row_widget_id(row)
    wk = f"tab1_sms_{wid}"
    msg = check_sms_text(link)
    st.session_state.df.at[idx, "Чек"] = link
    st.session_state.df.at[idx, "Повідомлення"] = msg
    st.session_state[wk] = msg
    st.session_state[f"_tab1_last_ck_{wid}"] = link
    st.session_state[f"tab1_pick_open_{wid}"] = False
    st.session_state._deferred_save = True

    ttn = str(row.get("ТТН", "")).strip()[:40]
    sc = ship_cost
    rs = receipt_sum

    def _bg():
        try:
            audit_log(audit_action, ttn, link[:120], ship_cost=sc, receipt_sum=rs)
        except Exception:
            pass

    threading.Thread(target=_bg, daemon=True).start()
    st.rerun()


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


def _sms_status_series(df: pd.DataFrame) -> pd.Series:
    if "Статус СМС" not in df.columns:
        return pd.Series([""] * len(df), index=df.index)
    return df["Статус СМС"].fillna("").astype(str).str.strip()


def _tab1_without_sent_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Прибрати з таблиці рядки з «Отправлено» (як «Видалити відправлені»)."""
    return df[_sms_status_series(df) != "Отправлено"].reset_index(drop=True)


def _tab1_pending_mask(df: pd.DataFrame) -> pd.Series:
    """Рядки черги «Видати чек» — без відправлених SMS."""
    target_statuses = utils.DELIVERED_STATUS_KEYWORDS
    no_receipt = ~df.apply(utils.row_receipt_not_required, axis=1)
    not_sent = _sms_status_series(df) != "Отправлено"
    msg_or_status = (df["Повідомлення"].fillna("").astype(str).str.len() > 5) | (
        df["Статус"].fillna("").astype(str).str.lower().str.contains(
            "|".join(target_statuses), na=False
        )
    )
    return no_receipt & not_sent & msg_or_status


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
        st.session_state.df = _tab1_without_sent_rows(st.session_state.df)
        sheets.save_manual(st.session_state.df)
    return ok_count, errors


def _tab1_mark_done(idx, row) -> None:
    """Статус «Отправлено», прибрати з черги tab1 і зберегти в Google."""
    st.session_state.df.at[idx, "Статус СМС"] = "Отправлено"
    chk = str(st.session_state.df.at[idx, "Чек"]).strip()
    msg = str(st.session_state.df.at[idx, "Повідомлення"]).strip()
    if msg and msg.lower() != "nan":
        st.session_state.df.at[idx, "Повідомлення"] = msg
    if chk and len(chk) > 5 and chk.lower() != "nan":
        st.session_state.df.at[idx, "Чек"] = chk

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

    st.session_state.df = _tab1_without_sent_rows(st.session_state.df)
    if not sheets.save_manual(st.session_state.df):
        st.session_state["_tab1_save_failed"] = ttn

    def _persist_async():
        try:
            audit_log("смс_готово", ttn, detail, ship_cost=sc_done, receipt_sum=None)
        except Exception:
            pass

    threading.Thread(target=_persist_async, daemon=True).start()



@st.fragment
def render_fragment():
    if utils.apply_no_receipt_auto_sent(st.session_state.df):
        sheets.save_manual(st.session_state.df)

    failed_ttn = st.session_state.pop("_tab1_save_failed", None)
    if failed_ttn:
        st.warning(
            f"Рядок `{failed_ttn}` прибрано з черги, але запис у Google не вдався — "
            "перевір інтернет і натисни «Зберегти» на вкладці «Таблиця» за потреби."
        )

    pending = st.session_state.df[_tab1_pending_mask(st.session_state.df)]

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

        n_ready = len(ready_rows)
        n_pending = len(pending)
        ui_theme.render_tab1_queue_bar(
            n_pending,
            n_ready,
            utils.now_kyiv_naive().strftime("%H:%M"),
        )
        ui_theme.render_tab1_hint()

        if utils.turbosms_configured():
            import config as _cfg_bulk

            st.caption(f"Відправник TurboSMS: **{_cfg_bulk.TURBOSMS_SENDER}**")
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

        pending_rows = list(pending.iterrows())
        for card_n, (idx, row) in enumerate(pending_rows):
            wid = tab1_row_widget_id(row)
            svc_cls = ui_theme.tab1_card_service_class(row)
            with st.container(border=True):
                st.markdown(
                    f'<div class="tab1-shipment-card {svc_cls}" aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                c1, c2, c3 = st.columns([1.6, 4.2, 1.6])
                
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
                        if str(st.session_state.df.at[idx, "Повідомлення"]).strip() in (
                            "",
                            "nan",
                        ):
                            st.session_state.df.at[idx, "Повідомлення"] = tab1_sms_prefill()
                        link_in, link_btn = st.columns([5, 1])
                        with link_in:
                            draft_link = st.text_input(
                                "➕ Посилання на чек:",
                                key=f"add_link_{wid}",
                                placeholder="https://check.checkbox.ua/...",
                            )
                        with link_btn:
                            st.write("")
                            if st.button("OK", key=f"apply_link_{wid}", use_container_width=True):
                                if str(draft_link or "").strip():
                                    try:
                                        sc_m = float(
                                            str(row.get("Вартість", 0))
                                            .replace(",", ".")
                                            .strip()
                                            or 0
                                        )
                                    except Exception:
                                        sc_m = None
                                    _tab1_attach_check(
                                        idx,
                                        row,
                                        draft_link.strip(),
                                        "чек_посилання",
                                        ship_cost=sc_m,
                                    )

                        pick_key = f"tab1_pick_open_{wid}"
                        if not st.session_state.get(pick_key):
                            if st.button(
                                "📋 Вибрати чек зі списку",
                                key=f"open_pick_{wid}",
                                help="Вибрати чек зі списку",
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
                                        rs_p = (
                                            audit_lookup_receipt_sum(sel_link, arch)
                                            if arch is not None and not arch.empty
                                            else None
                                        )
                                        _tab1_attach_check(
                                            idx,
                                            row,
                                            sel_link,
                                            "чек_список",
                                            ship_cost=row_cost if row_cost > 0 else None,
                                            receipt_sum=rs_p,
                                        )

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
            if card_n < len(pending_rows) - 1:
                st.markdown('<hr class="tab1-card-divider" />', unsafe_allow_html=True)
