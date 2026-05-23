"""Колонки та порядок головної таблиці замовлень."""
from __future__ import annotations

import streamlit as st

import config
import sheets


def ensure_columns(df):
    for c in config.COLS:
        if c not in df.columns:
            if c == "Дія":
                df[c] = False
            elif c == "Вартість":
                df[c] = 0.0
            else:
                df[c] = ""
    return df


def restore_leading_zero(val):
    s = str(val).replace("'", "").strip()
    if len(s) == 12 and s.isdigit():
        return "0" + s
    return s


def normalize_table_column_order(order):
    if not order:
        return list(config.COLS)
    seen = []
    for c in order:
        if c in config.COLS and c not in seen:
            seen.append(c)
    for c in config.COLS:
        if c not in seen:
            seen.append(c)
    return seen


def get_table_column_order():
    if "table_column_order" in st.session_state:
        return normalize_table_column_order(st.session_state.table_column_order)
    user = str(st.session_state.get("auth_user", "")).strip()
    loaded = sheets.load_table_column_order(user) if user else None
    order = normalize_table_column_order(loaded or config.COLS)
    st.session_state.table_column_order = order
    return order


def persist_table_column_order(order):
    order = normalize_table_column_order(order)
    st.session_state.table_column_order = order
    user = str(st.session_state.get("auth_user", "")).strip()
    if user:
        sheets.save_table_column_order(user, order)
    return order


def apply_table_column_order(df, order=None):
    order = order or get_table_column_order()
    cols = [c for c in order if c in df.columns]
    rest = [c for c in df.columns if c not in cols]
    return df[cols + rest]
