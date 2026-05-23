"""Вкладка «Відмови»."""
from __future__ import annotations

import streamlit as st

import utils


def render_tab():
    mask = (
        st.session_state.df["Статус"]
        .str.lower()
        .str.contains("відмова|повернення|denied", na=False)
    )
    st.dataframe(
        st.session_state.df[mask].style.map(utils.color_status, subset=["Статус"]),
        use_container_width=True,
        hide_index=True,
    )
