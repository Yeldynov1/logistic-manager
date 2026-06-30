"""Видимість вкладок для ролі manager (налаштовує admin)."""
from __future__ import annotations

import streamlit as st

import sheets

# Ключі вкладок (стабільні, для збереження в Sheets/Supabase).
TAB_CHECKOUT = "checkout"
TAB_TABLE = "table"
TAB_UP_TTN = "up_ttn"
TAB_ROZETKA = "rozetka"
TAB_PROMUA = "promua"
TAB_EPICENTR = "epicentr"
TAB_REFUSALS = "refusals"
TAB_ARCHIVE = "archive"
TAB_REMINDERS = "reminders"
TAB_AUDIT = "audit"

TAB_LABELS: dict[str, str] = {
    TAB_CHECKOUT: "📨 Видати чек",
    TAB_TABLE: "📊 Таблиця",
    TAB_UP_TTN: "📮 Укрпошта",
    TAB_ROZETKA: "🛒 Rozetka",
    TAB_PROMUA: "🛍️ Prom.ua",
    TAB_EPICENTR: "🏪 Епіцентр",
    TAB_REFUSALS: "❌ Відмови",
    TAB_ARCHIVE: "🧾 Архів чеків",
    TAB_REMINDERS: "⏳ Нагадування",
    TAB_AUDIT: "📋 Контроль",
}

# Порядок вкладок у UI.
TAB_ORDER: tuple[str, ...] = tuple(TAB_LABELS.keys())

# За замовчуванням — як було для логіна manager.
MANAGER_TAB_DEFAULTS: dict[str, bool] = {
    TAB_CHECKOUT: True,
    TAB_TABLE: True,
    TAB_UP_TTN: False,
    TAB_ROZETKA: False,
    TAB_PROMUA: False,
    TAB_EPICENTR: False,
    TAB_REFUSALS: True,
    TAB_ARCHIVE: True,
    TAB_REMINDERS: True,
    TAB_AUDIT: False,
}

_MANAGER_ROLE = "manager"
_SESSION_KEY = "manager_tab_visibility"


def normalize_tab_visibility(raw) -> dict[str, bool]:
    """Словник key→bool з усіма відомими вкладками."""
    out = dict(MANAGER_TAB_DEFAULTS)
    if isinstance(raw, dict):
        for key in TAB_ORDER:
            if key in raw:
                out[key] = bool(raw[key])
    elif isinstance(raw, (list, tuple)):
        enabled = {str(k) for k in raw}
        for key in TAB_ORDER:
            out[key] = key in enabled
    return out


def load_manager_tab_visibility(*, force: bool = False) -> dict[str, bool]:
    if not force and _SESSION_KEY in st.session_state:
        return dict(st.session_state[_SESSION_KEY])
    loaded = sheets.load_manager_tab_visibility(_MANAGER_ROLE)
    vis = normalize_tab_visibility(loaded if loaded is not None else MANAGER_TAB_DEFAULTS)
    st.session_state[_SESSION_KEY] = vis
    return dict(vis)


def save_manager_tab_visibility(visibility: dict[str, bool]) -> tuple[bool, str]:
    vis = normalize_tab_visibility(visibility)
    if not any(vis.values()):
        vis[TAB_CHECKOUT] = True
        vis[TAB_TABLE] = True
    ok, err = sheets.save_manager_tab_visibility(_MANAGER_ROLE, vis)
    if ok:
        st.session_state[_SESSION_KEY] = vis
        st.session_state.pop("manager_tabs_save_error", None)
    elif err:
        st.session_state.manager_tabs_save_error = err
    return ok, err or ""


def is_admin_user(auth_user: str) -> bool:
    return str(auth_user or "").strip().lower() == "admin"


def tab_visibility_for_user(auth_user: str) -> dict[str, bool]:
    """Admin бачить усе; інші — за налаштуванням manager."""
    if is_admin_user(auth_user):
        return {key: True for key in TAB_ORDER}
    return load_manager_tab_visibility()


def visible_tab_keys(auth_user: str) -> list[str]:
    vis = tab_visibility_for_user(auth_user)
    return [key for key in TAB_ORDER if vis.get(key)]


def tab_label(key: str) -> str:
    return TAB_LABELS.get(key, key)
