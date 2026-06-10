"""Панель діагностики швидкості (sidebar, лише admin)."""
from __future__ import annotations

import streamlit as st

from services import perf


def _ms_badge(ms: float) -> str:
    if ms >= 5000:
        return "🔴"
    if ms >= 1500:
        return "🟠"
    if ms >= 500:
        return "🟡"
    return "🟢"


def render_perf_sidebar() -> None:
    with st.sidebar.expander("⏱ Діагностика швидкості", expanded=False):
        st.caption(
            "Час операцій і відгуку API. Повільність часто через мережу або великі списки замовлень."
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🌐 Ping API", use_container_width=True, key="perf_ping_btn"):
                with st.spinner("Перевірка…"):
                    perf.run_network_ping()
        with c2:
            if st.button("🗑 Очистити", use_container_width=True, key="perf_clear_btn"):
                perf.clear()
                st.rerun()

        ping_rows = st.session_state.get("perf_ping_results")
        if isinstance(ping_rows, list) and ping_rows:
            st.markdown("**Затримка до серверів (ms)**")
            for row in ping_rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "—")
                ms = float(row.get("ms") or 0)
                status = int(row.get("status") or 0)
                err = str(row.get("error") or "").strip()
                line = f"{_ms_badge(ms)} **{name}** — {ms:.0f} ms"
                if status:
                    line += f" (HTTP {status})"
                    if name == "Nova Poshta API" and status == 401:
                        line += " — очікувано без ключа"
                if err:
                    line += f" — {err[:60]}"
                st.markdown(line)

        http_sum = perf.summary_by_prefix("HTTP ")
        if http_sum:
            st.markdown("**Найповільніші HTTP (сума за сесію)**")
            for label, total_ms, count in http_sum[:8]:
                short = label.replace("HTTP ", "", 1)
                st.caption(f"{_ms_badge(total_ms / max(count, 1))} {short}: **{total_ms:.0f} ms** × {count}")

        rows = perf.entries(25)
        if rows:
            st.markdown("**Останні операції**")
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label") or "—")
                ms = float(row.get("ms") or 0)
                ok = row.get("ok")
                err = str(row.get("error") or "").strip()
                status = row.get("status")
                suffix = ""
                if ok is False and err:
                    suffix = f" — {err[:50]}"
                elif status:
                    suffix = f" (HTTP {status})"
                st.caption(f"{_ms_badge(ms)} {label}: **{ms:.0f} ms**{suffix}")
        else:
            st.caption("Ще немає записів. Відкрийте вкладку або натисніть Ping API.")
