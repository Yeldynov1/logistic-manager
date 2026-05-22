"""Вкладка «Архів чеків» (Checkbox)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import utils
from services.checkbox_archive import (
    ARCHIVE_DAYS,
    archive_shift_day,
    fetch_checkbox_archive,
    used_checkbox_links_from_df,
)


def _archive_table(df: pd.DataFrame, used_links: set):
    """Таблиця: дата, час, сума, посилання."""
    work = df.copy()
    if "_dt" not in work.columns:
        work["_dt"] = pd.to_datetime(work["Дата"], errors="coerce")
    disp = pd.DataFrame(
        {
            "Дата": work["_dt"].dt.strftime("%d.%m.%Y"),
            "Час": work["_dt"].dt.strftime("%H:%M"),
            "Сума": work["Сума"],
            "Посилання": work["Посилання"],
        }
    )

    def _row_style(row):
        if str(row.get("Посилання", "")).strip() in used_links:
            return ["background-color: #abf7b1; color: black"] * len(row)
        return [""] * len(row)

    st.dataframe(
        disp.style.apply(_row_style, axis=1),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Посилання": st.column_config.LinkColumn(display_text="🧾 Чек"),
            "Сума": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_tab():
    """Архів чеків Checkbox — перегляд по днях."""
    c_df = fetch_checkbox_archive()
    if c_df is None:
        st.warning(
            "Архів недоступний: перевір **CHECKBOX_LOGIN**, **CHECKBOX_PASSWORD**, "
            "**CHECKBOX_LICENSE_KEY** у Secrets."
        )
        return
    if c_df.empty:
        st.info("Чеків за останні 30 днів не знайдено.")
        return

    used = used_checkbox_links_from_df(st.session_state.df)
    c_df = c_df.copy()
    c_df["_dt"] = pd.to_datetime(c_df["Дата"], errors="coerce")
    c_df["_day"] = c_df["_dt"].dt.date
    days_sorted = sorted({d for d in c_df["_day"].dropna().unique()}, reverse=True)
    today = utils.today_kyiv()

    attached = sum(1 for lk in c_df["Посилання"].astype(str) if lk.strip() in used)

    selected = st.session_state.get("chk_arch_selected_day")
    if selected is not None and not hasattr(selected, "strftime"):
        try:
            selected = pd.to_datetime(selected).date()
        except Exception:
            selected = None
    if selected not in days_sorted:
        selected = today if today in days_sorted else days_sorted[0]

    st.session_state.chk_arch_selected_day = selected
    try:
        day_idx = days_sorted.index(selected)
    except ValueError:
        day_idx = 0

    disp = selected.strftime("%d.%m.%Y")
    chunk = c_df[c_df["_day"] == selected].sort_values("_dt", ascending=False)
    day_label = disp + (" · сьогодні" if selected == today else "")

    top_btn, top_info = st.columns([1, 5])
    with top_btn:
        if st.button("🔄 Оновити", key="chk_arch_refresh", use_container_width=True):
            fetch_checkbox_archive.clear()
            st.cache_data.clear()
            st.rerun()
    with top_info:
        st.caption(
            f"**{len(c_df)}** чеків / {ARCHIVE_DAYS} дн. · "
            f"прикріплено: **{attached}** · зелений = використано"
        )

    nav_l, nav_c, nav_r = st.columns([1, 8, 1])
    with nav_l:
        if st.button(
            "◀",
            key="chk_arch_day_older",
            use_container_width=True,
            disabled=day_idx >= len(days_sorted) - 1,
        ):
            st.session_state.chk_arch_selected_day = archive_shift_day(
                days_sorted, selected, 1
            )
            st.rerun()
    with nav_c:
        st.markdown(
            f"<p style='margin:0;text-align:center;font-size:1.05rem;font-weight:600'>"
            f"{day_label} · <span style='font-weight:400'>{len(chunk)} чеків</span></p>",
            unsafe_allow_html=True,
        )
    with nav_r:
        if st.button(
            "▶",
            key="chk_arch_day_newer",
            use_container_width=True,
            disabled=day_idx <= 0,
        ):
            st.session_state.chk_arch_selected_day = archive_shift_day(
                days_sorted, selected, -1
            )
            st.rerun()
    if chunk.empty:
        st.info(f"За {disp} чеків у архіві немає.")
    else:
        _archive_table(chunk, used)
