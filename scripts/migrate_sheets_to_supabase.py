#!/usr/bin/env python3
"""Один раз: імпорт Orders / UP_Shipments / LogisticAudit з Google Sheets → Supabase."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import streamlit as st

st.secrets  # noqa: B018

from storage.migrate import migrate_sheets_to_supabase  # noqa: E402


def main() -> int:
    ok, msg = migrate_sheets_to_supabase()
    print(msg.replace("**", ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
