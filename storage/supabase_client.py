"""Клієнт Supabase (service_role з Streamlit Secrets)."""
from __future__ import annotations

import streamlit as st

_client = None


def supabase_configured() -> bool:
    try:
        url = str(st.secrets.get("SUPABASE_URL", "") or "").strip()
        key = str(st.secrets.get("SUPABASE_SERVICE_KEY", "") or "").strip()
        return bool(url and key)
    except Exception:
        return False


def use_supabase_backend() -> bool:
    if not supabase_configured():
        return False
    backend = str(st.secrets.get("DATA_BACKEND", "") or "").strip().lower()
    return backend in ("supabase", "db", "postgres")


def get_client():
    global _client
    if _client is not None:
        return _client
    if not supabase_configured():
        return None
    from supabase import create_client

    url = str(st.secrets["SUPABASE_URL"]).strip()
    key = str(st.secrets["SUPABASE_SERVICE_KEY"]).strip()
    _client = create_client(url, key)
    return _client


def reset_client() -> None:
    global _client
    _client = None
