"""Sidebar: admin налаштовує вкладки для manager."""
from __future__ import annotations

import streamlit as st

from core.tab_access import (
    TAB_ORDER,
    TAB_LABELS,
    load_manager_tab_visibility,
    save_manager_tab_visibility,
)


def render_manager_tabs_panel() -> None:
    if str(st.session_state.get("auth_user", "")).strip().lower() != "admin":
        return

    with st.expander("👤 Доступ менеджера", expanded=False):
        st.caption("Які вкладки бачить користувач **manager** (і інші не-admin).")
        current = load_manager_tab_visibility()
        draft: dict[str, bool] = {}
        for key in TAB_ORDER:
            draft[key] = st.checkbox(
                TAB_LABELS[key],
                value=bool(current.get(key)),
                key=f"mgr_tab_{key}",
            )
        last_err = str(st.session_state.get("manager_tabs_save_error") or "").strip()
        if last_err:
            st.warning(f"Остання помилка збереження: {last_err}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                "Зберегти",
                key="mgr_tabs_save",
                type="primary",
                use_container_width=True,
            ):
                ok, err = save_manager_tab_visibility(draft)
                if ok:
                    st.toast("Доступ менеджера збережено", icon="✅")
                    st.rerun()
                else:
                    st.error(err or "Не вдалося зберегти (Sheets / Supabase)")
        with c2:
            if st.button("Усі", key="mgr_tabs_all", use_container_width=True):
                ok, err = save_manager_tab_visibility({k: True for k in TAB_ORDER})
                if ok:
                    st.rerun()
                st.error(err or "Не вдалося зберегти")
        if st.button("За замовчуванням", key="mgr_tabs_reset", use_container_width=True):
            from core.tab_access import MANAGER_TAB_DEFAULTS

            ok, err = save_manager_tab_visibility(MANAGER_TAB_DEFAULTS)
            if ok:
                st.rerun()
            st.error(err or "Не вдалося зберегти")
