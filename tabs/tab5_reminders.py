"""Вкладка «Нагадування» — посилки в відділенні > 5 днів."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import sheets
import utils
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
            is_sent = str(row.get("Статус Нагадування", "")) == "Отправлено"
            with st.container(border=True):
                c1, c2, c3 = st.columns([1.5, 3, 1.5])
                with c1:
                    st.markdown(f"**{row['Служба']}** `{row['ТТН']}`")
                    st.caption(f"Чекає: {delta.days} днів")
                    st.markdown(f"📞 **{row['Телефон']}**")
                    if is_sent:
                        st.success("✅ Відправлено")
                with c2:
                    st.text_area(
                        "Текст",
                        msg,
                        height=80,
                        key=f"rt_{idx}",
                        label_visibility="collapsed",
                    )
                with c3:
                    render_smart_buttons(
                        row["Телефон"], msg, row_key=f"tab5_{idx}"
                    )
                if st.button(
                    "✅ Вже нагадав",
                    key=f"rem_done_{idx}",
                    use_container_width=True,
                ):
                    st.session_state.df.at[idx, "Статус Нагадування"] = "Отправлено"
                    sheets.save_manual(st.session_state.df)
                    st.rerun()
        except Exception:
            continue
    if not found_rem:
        st.info("👍 Боржників немає.")
