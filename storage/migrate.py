"""Імпорт Google Sheets → Supabase (CLI і кнопка в Streamlit)."""
from __future__ import annotations

import sheets
from storage import supabase_repo
from storage.supabase_client import get_client, reset_client, supabase_configured
from storage.supabase_repo import _float_or_none


def migrate_sheets_to_supabase() -> tuple[bool, str]:
    """Перенести Orders, UP_Shipments, LogisticAudit у Supabase."""
    if not supabase_configured():
        return False, "Додай SUPABASE_URL і SUPABASE_SERVICE_KEY у Secrets."

    reset_client()
    client = get_client()
    if not client:
        return False, "Не вдалося підключитись до Supabase."

    sheets.set_sheets_migration_mode(True)
    try:
        sheets.load_data_from_gsheets.clear()
        orders = sheets.load_data_from_gsheets()
        up = sheets.read_up_shipments(include_json=True)
        audit = sheets.read_audit_log()
    finally:
        sheets.set_sheets_migration_mode(False)

    lines = [
        f"Orders: **{len(orders)}** рядків",
        f"UP_Shipments: **{len(up)}** рядків",
        f"Audit: **{len(audit)}** рядків",
    ]

    if not orders.empty:
        if not supabase_repo.save_orders_df(orders):
            return False, "Помилка збереження orders у Supabase."
    lines.append("✅ Orders — записано")

    ok_n = 0
    for _, row in up.iterrows():
        if supabase_repo.append_up_shipment_record(row.to_dict()):
            ok_n += 1
    lines.append(f"✅ UP_Shipments — **{ok_n}** записів")

    try:
        client.table("audit_log").delete().neq("id", 0).execute()
        audit_rows = []
        for _, row in audit.iterrows():
            audit_rows.append(
                {
                    "username": str(row.get("Користувач", "") or ""),
                    "action": str(row.get("Дія", "") or ""),
                    "ttn": str(row.get("ТТН", "") or ""),
                    "detail": str(row.get("Деталі", "") or ""),
                    "ship_cost": _float_or_none(row.get("Вартість ТТН")),
                    "receipt_sum": _float_or_none(row.get("Сума чеку")),
                }
            )
        if audit_rows:
            for i in range(0, len(audit_rows), 500):
                client.table("audit_log").insert(audit_rows[i : i + 500]).execute()
        lines.append(f"✅ Audit — **{len(audit_rows)}** записів")
    except Exception as e:
        return False, f"Помилка audit: {e}"

    lines.append("")
    lines.append(
        'Далі: у **Streamlit Cloud → Secrets** додай `DATA_BACKEND = "supabase"` '
        "і натисни **Reboot app**."
    )
    return True, "\n\n".join(lines)


def render_migration_sidebar() -> None:
    """Кнопка імпорту в сайдбарі (лише якщо Supabase налаштовано, але ще Sheets)."""
    import streamlit as st

    from storage.supabase_client import use_supabase_backend

    if not supabase_configured():
        return
    if use_supabase_backend():
        st.sidebar.caption("Сховище: **Supabase**")
        return

    with st.sidebar.expander("🗄 Перехід на Supabase", expanded=False):
        st.caption(
            "Один раз перенести дані з Google Sheets у Supabase. "
            "Потрібні `SUPABASE_URL` і `SUPABASE_SERVICE_KEY` у Secrets."
        )
        if st.button(
            "Імпортувати з Google Sheets",
            key="sb_migrate_btn",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner("Читаю Sheets і записую в Supabase…"):
                ok, msg = migrate_sheets_to_supabase()
            if ok:
                st.success(msg)
                st.session_state["_supabase_migrate_done"] = True
            else:
                st.error(msg)
