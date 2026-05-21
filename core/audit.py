"""Журнал дій (LogisticAudit)."""
from __future__ import annotations

import streamlit as st

import sheets


@st.cache_data(ttl=20)
def cached_audit_log_df():
    return sheets.read_audit_log()


def audit_log(action, ttn="", detail="", ship_cost=None, receipt_sum=None):
    """Журнал дій (аркуш LogisticAudit у книзі Orders)."""
    u = str(st.session_state.get("auth_user", "")).strip() or "?"
    if sheets.append_audit_log(
        u, action, ttn, detail, ship_cost=ship_cost, receipt_sum=receipt_sum
    ):
        cached_audit_log_df.clear()


def audit_lookup_receipt_sum(detail_raw, chk_df):
    """Сума з архіву Checkbox, якщо у «Деталі» є URL чека."""
    if chk_df is None or chk_df.empty:
        return None
    d = str(detail_raw).lower()
    for _, cr in chk_df.iterrows():
        link = str(cr.get("Посилання", "")).lower().strip()
        if link and link in d:
            try:
                return float(cr.get("Сума", 0) or 0)
            except Exception:
                continue
    return None
