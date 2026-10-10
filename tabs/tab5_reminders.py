"""Вкладка «Нагадування» — посилки в відділенні > 5 днів."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import sheets
import utils
from core.audit import audit_log
from ui.components import render_smart_buttons

_ARRIVED_KEYWORDS = ["прибув", "прибуло", "відділенні"]
_RECEIVED_KEYWORDS = [
    "отримано",
    "отримане",
    "отримані",
    "отриманий",
    "отримана",
    "відмова",
]
_SVC_MAP = {"НП": "Нова пошта", "УП": "Укрпошта", "Meest": "Meest Пошта"}
_REMINDER_SENT = "Отправлено"


def _send_reminder_turbosms(idx, row, text: str) -> tuple[bool, bool, str]:
    """Надіслати нагадування і точково зберегти його статус.

    Повертає (прийнято TurboSMS, статус збережено, повідомлення).
    """
    ttn = str(row.get("ТТН", "") or "").strip()
    if str(row.get("Статус Нагадування", "") or "").strip() == _REMINDER_SENT:
        return False, False, "Це нагадування вже позначене як відправлене."
    if not ttn:
        return False, False, "Неможливо надіслати нагадування без ТТН."

    valid, validation_error = sheets.validate_order_ttns([ttn], silent=True)
    if not valid:
        return False, False, validation_error or f"ТТН {ttn} не знайдено однозначно."

    message = str(text or "").strip()
    ok, message_id, send_error = utils.turbosms_send(
        row.get("Телефон", ""),
        message,
        idempotency_key=f"reminder:{ttn}",
    )
    if not ok:
        return False, False, send_error or "TurboSMS не підтвердив нагадування."

    st.session_state.df.at[idx, "Статус Нагадування"] = _REMINDER_SENT
    saved, save_error = sheets.update_order_cells_by_ttn(
        ttn,
        {"Статус Нагадування": _REMINDER_SENT},
        silent=True,
    )
    detail = f"TurboSMS · id={message_id}" if message_id else "TurboSMS · прийнято"
    try:
        audit_log("смс_нагадування", ttn[:40], detail)
    except Exception:
        pass

    if not saved:
        return (
            True,
            False,
            "TurboSMS прийняв SMS, але статус не вдалося зберегти. "
            "Не надсилайте це нагадування повторно."
            + (f" Деталі: {save_error}" if save_error else ""),
        )
    return True, True, ""


def render_tab():
    st.subheader("⏳ Посилки, що чекають > 5 днів")
    today = utils.now_kyiv_naive()
    found_rem = False
    for idx, row in st.session_state.df.iterrows():
        s_low = str(row["Статус"]).lower()
        if not any(x in s_low for x in _ARRIVED_KEYWORDS):
            continue
        if any(x in s_low for x in _RECEIVED_KEYWORDS):
            continue
        try:
            d_str = utils.normalize_date(str(row["Дата"]))
            if not d_str:
                continue
            delta = today - datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")
            if delta.days < 5:
                continue
            found_rem = True
            svc = _SVC_MAP.get(row["Служба"], row["Служба"])
            msg = (
                f"Добрий день! Ваше замовлення вже у відділенні {svc} {row['ТТН']}. "
                "Прохання забрати посилку."
            )
            is_sent = str(row.get("Статус Нагадування", "")) == _REMINDER_SENT
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                with c1:
                    st.markdown(f"**{row['Служба']}** `{row['ТТН']}`")
                    st.caption(f"Чекає: {delta.days} днів")
                    st.markdown(f"📞 **{row['Телефон']}**")
                    if is_sent:
                        st.success("✅ Відправлено")
                with c2:
                    reminder_text = st.text_area(
                        "Текст",
                        msg,
                        height=80,
                        key=f"rt_{idx}",
                        label_visibility="collapsed",
                    )
                with c3:
                    render_smart_buttons(
                        row["Телефон"], reminder_text, row_key=f"tab5_{idx}"
                    )
                    if not is_sent and utils.turbosms_configured():
                        if st.button(
                            "📨 Надіслати TurboSMS",
                            key=f"rem_turbosms_{idx}",
                            type="primary",
                            use_container_width=True,
                        ):
                            with st.spinner("Надсилання нагадування через TurboSMS…"):
                                accepted, saved, error = _send_reminder_turbosms(
                                    idx, row, reminder_text
                                )
                            if accepted and saved:
                                st.toast("Нагадування надіслано через TurboSMS", icon="📨")
                                st.rerun()
                            elif accepted:
                                st.warning(error)
                            else:
                                st.error(error)
                    elif not is_sent:
                        st.caption("TurboSMS не налаштовано")
                if st.button(
                    "✅ Вже нагадав",
                    key=f"rem_done_{idx}",
                    use_container_width=True,
                ):
                    st.session_state.df.at[idx, "Статус Нагадування"] = _REMINDER_SENT
                    sheets.save_manual(st.session_state.df)
                    st.rerun()
        except Exception:
            continue
    if not found_rem:
        st.info("👍 Боржників немає.")
