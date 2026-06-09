#!/usr/bin/env python3
"""Один раз: імпорт Orders / UP_Shipments / LogisticAudit з Google Sheets → Supabase.

Потрібно в .streamlit/secrets.toml:
  gcp_service_account = { ... }
  SUPABASE_URL = "..."
  SUPABASE_SERVICE_KEY = "..."
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st

st.secrets  # noqa: B018 — завантажити secrets.toml локально

import sheets  # noqa: E402
from storage import supabase_repo  # noqa: E402
from storage.supabase_client import get_client, reset_client, supabase_configured  # noqa: E402


def main() -> int:
    if not supabase_configured():
        print("❌ Додай SUPABASE_URL і SUPABASE_SERVICE_KEY у secrets.toml")
        return 1
    reset_client()
    client = get_client()
    if not client:
        print("❌ Не вдалося підключитись до Supabase")
        return 1

    print("📥 Читаю Google Sheets…")
    sheets.load_data_from_gsheets.clear()
    orders = sheets.load_data_from_gsheets()
    up = sheets.read_up_shipments(include_json=True)
    audit = sheets.read_audit_log()

    print(f"   Orders: {len(orders)} рядків")
    print(f"   UP_Shipments: {len(up)} рядків")
    print(f"   Audit: {len(audit)} рядків")

    print("📤 Orders → Supabase…")
    if not orders.empty:
        if not supabase_repo.save_orders_df(orders):
            print("❌ Помилка збереження orders")
            return 1
    else:
        print("   (порожньо)")

    print("📤 UP_Shipments → Supabase…")
    ok_n = 0
    for _, row in up.iterrows():
        if supabase_repo.append_up_shipment_record(row.to_dict()):
            ok_n += 1
    print(f"   Записано: {ok_n}")

    print("📤 Audit → Supabase…")
    client.table("audit_log").delete().neq("id", 0).execute()
    audit_rows = []
    for _, row in audit.iterrows():
        audit_rows.append(
            {
                "username": str(row.get("Користувач", "") or ""),
                "action": str(row.get("Дія", "") or ""),
                "ttn": str(row.get("ТТН", "") or ""),
                "detail": str(row.get("Деталі", "") or ""),
                "ship_cost": row.get("Вартість ТТН"),
                "receipt_sum": row.get("Сума чеку"),
            }
        )
    if audit_rows:
        for i in range(0, len(audit_rows), 500):
            client.table("audit_log").insert(audit_rows[i : i + 500]).execute()
    print(f"   Записано: {len(audit_rows)}")

    print()
    print("✅ Готово. У Streamlit Secrets встанови:")
    print('   DATA_BACKEND = "supabase"')
    print("   і перезапусти додаток.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
