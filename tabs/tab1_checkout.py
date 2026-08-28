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
from core.audit import audit_log
from core.receipt_delivery import (
    CHECKBOX_RECEIPT_HOST as _CHECKBOX_RECEIPT_HOST,
    CHECK_SMS_PREFIX as _CHECK_SMS_PREFIX,
    default_receipt_sms_text,
    receipt_sms_prefill,
    receipt_sms_text,
    receipt_sms_text_for_send,
    row_ready_for_turbosms,
)
from services.checkbox_archive import (
    fetch_checkbox_archive,
    tab1_freshest_today_unattached_receipt,
)
from ui.components import render_copyable_invoice, render_smart_buttons

def check_sms_text(link: str) -> str:
    return receipt_sms_text(link)


def tab1_sms_prefill() -> str:
    """Готовий текст до вставки посилання на чек."""
    return receipt_sms_prefill()


def tab1_default_sms_text(row) -> str:
    """Текст СМС: колонка «Чек» — джерело правди; без неї не показуємо «леві» URL з «Повідомлення»."""
    return default_receipt_sms_text(row)


def _tab1_attach_check(
    idx,
    row,
    link: str,
    audit_action: str,
    *,
    ship_cost=None,
    receipt_sum=None,
) -> None:
    """Швидко прикріпити чек: лише дві комірки в Sheet, журнал — у фоні."""
    link = str(link or "").strip()
    if len(link) < 5:
        return
    ttn = str(row.get("ТТН", "")).strip()
    old_link = st.session_state.df.at[idx, "Чек"]
    old_message = st.session_state.df.at[idx, "Повідомлення"]
    wid = tab1_row_widget_id(row)
    wk = f"tab1_sms_{wid}"
    had_widget_message = wk in st.session_state
    old_widget_message = st.session_state.get(wk)
    last_check_key = f"_tab1_last_ck_{wid}"
    had_last_check = last_check_key in st.session_state
    old_last_check = st.session_state.get(last_check_key)
    msg = check_sms_text(link)
    st.session_state.df.at[idx, "Чек"] = link
    st.session_state.df.at[idx, "Повідомлення"] = msg
    st.session_state[wk] = msg
    st.session_state[last_check_key] = link
    st.session_state[f"tab1_pick_open_{wid}"] = False

    saved, save_error = sheets.update_order_cells_by_ttn(
        ttn,
        {"Чек": link, "Повідомлення": msg},
        silent=True,
    )
    if not saved:
        st.session_state.df.at[idx, "Чек"] = old_link
        st.session_state.df.at[idx, "Повідомлення"] = old_message
        if had_widget_message:
            st.session_state[wk] = old_widget_message
        else:
            st.session_state.pop(wk, None)
        if had_last_check:
            st.session_state[last_check_key] = old_last_check
        else:
            st.session_state.pop(last_check_key, None)
        st.error(save_error or f"Не вдалося зберегти чек для {ttn}.")
        return

    audit_ttn = ttn[:40]
    sc = ship_cost
    rs = receipt_sum

    def _bg():
        try:
            audit_log(audit_action, audit_ttn, link[:120], ship_cost=sc, receipt_sum=rs)
        except Exception:
            pass

    threading.Thread(target=_bg, daemon=True).start()
    st.rerun()


def tab1_row_widget_id(row) -> str:
    """Стабільний id для ключів Streamlit (індекс DataFrame змінюється після reset_index)."""
    raw = f"{str(row.get('ТТН', '')).strip()}|{str(row.get('Телефон', '')).strip()}"
    return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


def _sms_status_series(df: pd.DataFrame) -> pd.Series:
    if "Статус СМС" not in df.columns:
        return pd.Series([""] * len(df), index=df.index)
    return df["Статус СМС"].fillna("").astype(str).str.strip()


def _tab1_without_manual_done_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Видалити лише рядки, які користувач позначив кнопкою «Готово»."""
    return df[
        _sms_status_series(df) != utils.SMS_STATUS_MANUAL_DONE
    ].reset_index(drop=True)


def _tab1_drop_indices(df: pd.DataFrame, indices: list) -> pd.DataFrame:
    """Прибрати з session_state лише конкретні рядки, прийняті TurboSMS."""
    if not indices:
        return df
    return df.drop(index=list(indices), errors="ignore").reset_index(drop=True)


def _tab1_pending_mask(df: pd.DataFrame) -> pd.Series:
    """Рядки черги «Видати чек» — без відправлених SMS."""
    not_sent = ~_sms_status_series(df).map(utils.sms_status_is_done)

    def _eligible(row) -> bool:
        status = row.get("Статус", "")
        if utils.status_is_non_customer_delivery(status):
            return False
        if utils.row_is_meest(row) or utils.row_is_up(row) or utils.row_is_np(row):
            return utils.checkout_status_is_ready(row)
        msg = str(row.get("Повідомлення", "")).strip()
        if len(msg) > 5 and msg.lower() != "nan":
            return True
        return utils.checkout_status_is_ready(row)

    eligible = df.apply(_eligible, axis=1)
    return not_sent & eligible


def _tab1_sms_text_for_send(row) -> str:
    """Текст для TurboSMS: «Повідомлення» або шаблон з колонки «Чек»."""
    return receipt_sms_text_for_send(row)


def _tab1_ready_for_turbosms(row) -> bool:
    return row_ready_for_turbosms(row)


def _tab1_send_turbosms_row(idx, row) -> tuple[bool, str]:
    """Одна відправка TurboSMS + журнал + «Отправлено»."""
    full_ttn = str(row.get("ТТН", "")).strip()
    if not utils.checkout_status_is_ready(row):
        return False, "Статус не підтверджує вручення покупцю."
    valid, validation_error = sheets.validate_order_ttns([full_ttn], silent=True)
    if not valid:
        return False, validation_error or f"ТТН {full_ttn} не знайдено однозначно."
    txt = _tab1_sms_text_for_send(row)
    st.session_state.df.at[idx, "Повідомлення"] = txt
    ok, mid, terr = utils.turbosms_send(
        row["Телефон"], txt, idempotency_key=full_ttn
    )
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
    _tab1_finalize_turbosms_sent(idx, row)
    return True, ""


def _tab1_bulk_send_turbosms(ready_rows: list) -> tuple[int, list]:
    """ready_rows: [(idx, row, text), ...]. Повертає (успішно, [(ttn, err), ...])."""
    unsafe_ttns = [
        str(row.get("ТТН", "")).strip()[:40]
        for _, row, _ in ready_rows
        if not utils.checkout_status_is_ready(row)
    ]
    if unsafe_ttns:
        error = "Статус не підтверджує вручення покупцю."
        return 0, [(ttn, error) for ttn in unsafe_ttns]
    candidate_ttns = [str(row.get("ТТН", "")).strip() for _, row, _ in ready_rows]
    valid, validation_error = sheets.validate_order_ttns(candidate_ttns, silent=True)
    if not valid:
        err = validation_error or "Не вдалося однозначно знайти ТТН у Orders."
        return 0, [(ttn[:40], err) for ttn in candidate_ttns]
    ok_count = 0
    errors = []
    sent_indices = []
    sent_ttns = []
    audit_records = []
    df = st.session_state.df
    for idx, row, txt in ready_rows:
        df.at[idx, "Повідомлення"] = txt
        full_ttn = str(row.get("ТТН", "")).strip()
        ok, mid, terr = utils.turbosms_send(
            row["Телефон"], txt, idempotency_key=full_ttn
        )
        ttn = full_ttn[:40]
        if not ok:
            errors.append((ttn, terr or "Помилка TurboSMS"))
            continue
        detail = str(df.at[idx, "Чек"]).strip()[:120]
        if mid:
            detail = f"{detail} · id={mid}" if detail else f"id={mid}"
        try:
            sc_t = float(str(row.get("Вартість", 0)).replace(",", ".").strip() or 0)
        except Exception:
            sc_t = None
        audit_records.append(("смс_turbosms", ttn, detail, sc_t))
        df.at[idx, "Статус СМС"] = utils.SMS_STATUS_SENT
        sent_indices.append(idx)
        sent_ttns.append(full_ttn)
        ok_count += 1
        time.sleep(0.35)
    if ok_count:
        deleted, delete_error = sheets.delete_orders_by_ttns(sent_ttns, silent=True)
        if deleted:
            st.session_state.df = _tab1_drop_indices(df, sent_indices)
        else:
            st.session_state.df = df
            st.session_state["_tab1_turbo_delete_failed"] = {
                "ttns": sent_ttns,
                "error": delete_error,
            }

        def _bg_audit():
            for action, ttn, detail, sc in audit_records:
                try:
                    audit_log(action, ttn, detail, ship_cost=sc, receipt_sum=None)
                except Exception:
                    pass

        threading.Thread(target=_bg_audit, daemon=True).start()
    return ok_count, errors


def auto_send_ready_turbosms() -> tuple[int, list[tuple[str, str]]]:
    """Авто-видача готових чеків через TurboSMS (режим «Авто-пошук ВКЛ»)."""
    if not utils.turbosms_configured():
        return 0, []
    df = st.session_state.get("df")
    if df is None or getattr(df, "empty", True):
        return 0, []
    pending = df[_tab1_pending_mask(df)]
    if pending.empty:
        return 0, []
    ready_rows: list = []
    for idx, row in pending.iterrows():
        if not _tab1_ready_for_turbosms(row):
            continue
        ready_rows.append((idx, row, _tab1_sms_text_for_send(row)))
    if not ready_rows:
        return 0, []
    sent, errors = _tab1_bulk_send_turbosms(ready_rows)
    if sent or errors:
        st.session_state._tab1_bulk_result = {"ok": sent, "errors": errors, "auto": True}
    return sent, errors


def _tab1_finalize_turbosms_sent(idx, row) -> None:
    """Прийнятий TurboSMS: автоматично видалити лише цей рядок."""
    df = st.session_state.df
    df.at[idx, "Статус СМС"] = utils.SMS_STATUS_SENT
    ttn = str(row.get("ТТН", "")).strip()
    deleted, delete_error = sheets.delete_orders_by_ttns([ttn], silent=True)
    if deleted:
        st.session_state.df = _tab1_drop_indices(df, [idx])
    else:
        st.session_state.df = df
        st.session_state["_tab1_turbo_delete_failed"] = {
            "ttns": [ttn],
            "error": delete_error,
        }


def _tab1_mark_done(idx, row) -> bool:
    """Кнопка «Готово»: позначити рядок, але не видаляти його з Google Sheets."""
    df = st.session_state.df
    previous_status = df.at[idx, "Статус СМС"]
    df.at[idx, "Статус СМС"] = utils.SMS_STATUS_MANUAL_DONE
    chk = str(df.at[idx, "Чек"]).strip()
    msg = str(df.at[idx, "Повідомлення"]).strip()
    if msg and msg.lower() != "nan":
        df.at[idx, "Повідомлення"] = msg
    if chk and len(chk) > 5 and chk.lower() != "nan":
        df.at[idx, "Чек"] = chk

    try:
        sc_done = float(str(df.at[idx, "Вартість"]).replace(",", ".").strip())
    except Exception:
        sc_done = None
    if utils.row_receipt_not_required(row):
        detail = "ЧЕК НЕ ПОТРІБЕН (*)"
    else:
        detail = chk[:120] if chk else "(без посилання на чек)"
    ttn = str(row.get("ТТН", "")).strip()[:40]

    changes = {"Статус СМС": utils.SMS_STATUS_MANUAL_DONE}
    if msg and msg.lower() != "nan":
        changes["Повідомлення"] = msg
    if chk and len(chk) > 5 and chk.lower() != "nan":
        changes["Чек"] = chk
    saved, save_error = sheets.update_order_cells_by_ttn(ttn, changes, silent=True)
    if not saved:
        df.at[idx, "Статус СМС"] = previous_status
        st.session_state["_tab1_save_failed"] = {
            "ttn": ttn,
            "error": save_error,
        }
        return False

    def _persist_async():
        try:
            audit_log("смс_готово", ttn, detail, ship_cost=sc_done, receipt_sum=None)
        except Exception:
            pass

    threading.Thread(target=_persist_async, daemon=True).start()
    return True



@st.fragment
def render_fragment():
    if not st.session_state.get("_no_receipt_auto_done"):
        if utils.apply_no_receipt_auto_sent(st.session_state.df):
            sheets.save_manual(st.session_state.df, clear_cache=False)
        st.session_state["_no_receipt_auto_done"] = True

    save_failed = st.session_state.pop("_tab1_save_failed", None)
    if save_failed:
        failed_ttn = save_failed.get("ttn", "") if isinstance(save_failed, dict) else str(save_failed)
        failed_error = save_failed.get("error", "") if isinstance(save_failed, dict) else ""
        st.warning(
            f"Не вдалося зберегти «Видано вручну» для `{failed_ttn}`. "
            "Рядок не видалено; перевір інтернет і спробуй ще раз."
            + (f" Деталі: {failed_error}" if failed_error else "")
        )

    turbo_delete_failed = st.session_state.pop("_tab1_turbo_delete_failed", None)
    if turbo_delete_failed:
        failed_ttns = (
            turbo_delete_failed.get("ttns", [])
            if isinstance(turbo_delete_failed, dict)
            else turbo_delete_failed
        )
        failed_error = (
            turbo_delete_failed.get("error", "")
            if isinstance(turbo_delete_failed, dict)
            else ""
        )
        st.warning(
            "TurboSMS прийняв повідомлення, але рядок не вдалося видалити з Google Sheets: "
            + ", ".join(str(x) for x in failed_ttns)
            + (f". Деталі: {failed_error}" if failed_error else "")
        )

    pending = st.session_state.df[_tab1_pending_mask(st.session_state.df)]

    bulk_res = st.session_state.pop("_tab1_bulk_result", None)
    if bulk_res:
        auto_lbl = "Авто · " if bulk_res.get("auto") else ""
        st.success(f"{auto_lbl}TurboSMS: надіслано **{bulk_res['ok']}**")
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

                        try:
                            row_cost = float(
                                str(row.get("Вартість", 0)).replace(",", ".").strip() or 0
                            )
                        except Exception:
                            row_cost = 0.0

                        if st.button(
                            "📎 Прикріпити чек",
                            key=f"attach_chk_{wid}",
                            type="primary",
                            help="Найсвіжіший вільний чек за сьогодні з такою ж сумою",
                            use_container_width=True,
                        ):
                            fetch_checkbox_archive.clear()
                            arch = fetch_checkbox_archive()
                            pick, err = tab1_freshest_today_unattached_receipt(
                                st.session_state.df, arch, row.get("Вартість", 0)
                            )
                            if pick:
                                _tab1_attach_check(
                                    idx,
                                    row,
                                    pick["link"],
                                    "чек_авто",
                                    ship_cost=row_cost if row_cost > 0 else None,
                                    receipt_sum=pick.get("receipt_sum"),
                                )
                            else:
                                st.warning(err)

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
                        if _tab1_mark_done(idx, row):
                            st.rerun()
                        else:
                            st.error("Не вдалося зберегти статус. Рядок не видалено.")
            if card_n < len(pending_rows) - 1:
                st.markdown('<hr class="tab1-card-divider" />', unsafe_allow_html=True)
