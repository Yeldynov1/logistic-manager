"""Спільний стан «Авто-пошук ВКЛ/ВИКЛ» між сесіями (admin бачить менеджера)."""
from __future__ import annotations

import streamlit as st

import sheets
import utils
from core.tab_access import TAB_ORDER, is_admin_user

_AUTO_REFRESH_USERS_KEY = "auto_refresh_users"
_LEGACY_AUTO_REFRESH_KEY = "auto_refresh"
_TAB_KEYS = frozenset(TAB_ORDER)


def _parse_visible_tabs(settings: dict) -> dict | None:
    if not isinstance(settings, dict):
        return None
    vis = settings.get("visible_tabs")
    if isinstance(vis, dict):
        return vis
    flat = {k: settings[k] for k in _TAB_KEYS if k in settings}
    return flat if flat else None


def _load_role_settings(role: str = "manager") -> dict:
    raw = sheets.load_role_settings(role)
    return raw if isinstance(raw, dict) else {}


def _save_role_settings(role: str, settings: dict) -> tuple[bool, str]:
    return sheets.save_role_settings(role, settings)


def _auto_refresh_users_map(settings: dict) -> dict[str, dict]:
    users = settings.get(_AUTO_REFRESH_USERS_KEY)
    if isinstance(users, dict):
        return {str(k).strip().lower(): v for k, v in users.items() if isinstance(v, dict)}
    legacy = settings.get(_LEGACY_AUTO_REFRESH_KEY)
    if isinstance(legacy, dict):
        uname = str(legacy.get("username") or "manager").strip().lower()
        if uname:
            return {
                uname: {
                    "enabled": legacy.get("enabled"),
                    "updated_at": legacy.get("updated_at", ""),
                }
            }
    return {}


def persist_auto_refresh(enabled: bool) -> None:
    """Зберегти стан перемикача для поточного користувача (Sheets / Supabase)."""
    user = str(st.session_state.get("auth_user", "") or "").strip()
    if not user:
        return
    user_key = user.lower()
    role = "manager"
    settings = _load_role_settings(role)
    vis = _parse_visible_tabs(settings)
    if vis is not None:
        settings = {k: v for k, v in settings.items() if k not in _TAB_KEYS}
        settings["visible_tabs"] = vis
    users = _auto_refresh_users_map(settings)
    users[user_key] = {
        "enabled": bool(enabled),
        "updated_at": utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S"),
    }
    settings[_AUTO_REFRESH_USERS_KEY] = users
    settings.pop(_LEGACY_AUTO_REFRESH_KEY, None)
    _save_role_settings(role, settings)


def hydrate_auto_refresh_from_remote() -> None:
    """Відновити перемикач зі сховища після входу / перезавантаження."""
    if st.session_state.get("_auto_refresh_hydrated"):
        return
    user = str(st.session_state.get("auth_user", "") or "").strip().lower()
    if not user:
        st.session_state._auto_refresh_hydrated = True
        return
    users = _auto_refresh_users_map(_load_role_settings("manager"))
    entry = users.get(user)
    if isinstance(entry, dict) and entry.get("enabled") is not None:
        st.session_state.auto_refresh = bool(entry.get("enabled"))
    st.session_state._auto_refresh_hydrated = True


def load_manager_auto_refresh_status() -> dict:
    """
    Стан авто-пошуку менеджера для admin (перший не-admin у списку).
    keys: enabled (bool|None), username, updated_at
    """
    users = _auto_refresh_users_map(_load_role_settings("manager"))
    for uname in sorted(users.keys()):
        if uname == "admin":
            continue
        data = users[uname]
        enabled = data.get("enabled")
        return {
            "enabled": bool(enabled) if enabled is not None else None,
            "username": uname,
            "updated_at": str(data.get("updated_at") or "").strip(),
        }
    return {"enabled": None, "username": "", "updated_at": ""}


def render_admin_manager_auto_refresh_status() -> None:
    """Підказка для admin: чи увімкнений авто-пошук у менеджера."""
    if not is_admin_user(str(st.session_state.get("auth_user", "") or "")):
        return
    ar = load_manager_auto_refresh_status()
    user = ar.get("username") or "—"
    ts = ar.get("updated_at") or ""
    enabled = ar.get("enabled")
    if enabled is None:
        label = "невідомо (менеджер ще не перемикав)"
        color = "#6b7280"
    elif enabled:
        label = "ВКЛ"
        color = "#16a34a"
    else:
        label = "ВИКЛ"
        color = "#dc2626"
    ts_bit = f" · {ts}" if ts else ""
    st.sidebar.markdown(
        f'<div style="margin:0.35rem 0 0.6rem 0;font-size:0.82rem;line-height:1.35;color:#9ca3af;">'
        f'Менеджер <strong style="color:#e5e7eb;">{user}</strong> · авто-пошук '
        f'<strong style="color:{color};">{label}</strong>{ts_bit}</div>',
        unsafe_allow_html=True,
    )
