"""Журнал дій (LogisticAudit)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import sheets
from services.checkbox_archive import fetch_checkbox_archive


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


def audit_lookup_ship_cost(ttn_raw, main_df):
    ttn = str(ttn_raw).strip()
    if not ttn or ttn.lower() == "nan":
        return None
    try:
        m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
        if m.empty:
            return None
        v = m.iloc[0]["Вартість"]
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def audit_num_from_cell(val):
    if val is None:
        return float("nan")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "—", "-"):
        return float("nan")
    try:
        return float(s.replace(",", ".").strip())
    except (TypeError, ValueError):
        return float("nan")


def enrich_audit_table(adf, main_df, chk_df):
    """Додає / уточнює «Вартість ТТН» та «Сума чеку»."""
    out = adf.head(500).copy()
    ships, sums = [], []
    for _, r in out.iterrows():
        saved_ship = audit_num_from_cell(r.get("Вартість ТТН"))
        saved_rcpt = audit_num_from_cell(r.get("Сума чеку"))
        ttn = str(r.get("ТТН", "")).strip()
        detail = r.get("Деталі", "")

        if not pd.isna(saved_ship):
            ship_f = saved_ship
        else:
            sc = audit_lookup_ship_cost(ttn, main_df)
            ship_f = float(sc) if sc is not None else float("nan")

        if not pd.isna(saved_rcpt):
            rcpt_f = saved_rcpt
        else:
            rs = audit_lookup_receipt_sum(detail, chk_df)
            if rs is None and ttn:
                m = main_df[main_df["ТТН"].astype(str).str.strip() == ttn]
                if not m.empty:
                    curl = str(m.iloc[0].get("Чек", "")).strip()
                    if curl and curl.lower() != "nan":
                        rs = audit_lookup_receipt_sum(curl, chk_df)
            rcpt_f = float(rs) if rs is not None else float("nan")

        ships.append(ship_f)
        sums.append(rcpt_f)
    out["Вартість ТТН"] = ships
    out["Сума чеку"] = sums
    return out


def style_audit_amounts(df):
    """Підсвічує дві останні колонки: зелений збіг, червоний розбіжність."""

    def _row_style(row):
        blank = ""
        sty = [blank] * len(row)
        if "Вартість ТТН" not in row.index or "Сума чеку" not in row.index:
            return pd.Series(sty, index=row.index)
        ok = "background-color: #c8e6c9; color: #1b5e20; font-weight: 600"
        bad = "background-color: #ffcdd2; color: #b71c1c; font-weight: 600"
        a = row["Вартість ТТН"]
        b = row["Сума чеку"]
        try:
            fa = float(a) if not pd.isna(a) else None
        except (TypeError, ValueError):
            fa = None
        try:
            fb = float(b) if not pd.isna(b) else None
        except (TypeError, ValueError):
            fb = None
        i_a = row.index.get_loc("Вартість ТТН")
        i_b = row.index.get_loc("Сума чеку")
        if fa is not None and fb is not None:
            c = ok if abs(fa - fb) < 0.01 else bad
            sty[i_a] = c
            sty[i_b] = c
        return pd.Series(sty, index=row.index)

    return df.style.apply(_row_style, axis=1)


def render_audit_tab():
    """Вкладка «Контроль» — журнал дій."""
    st.subheader("📋 Хто що зробив")
    st.caption(
        "Журнал: Google **Orders** → **LogisticAudit**. "
        "**чек_посилання** — URL вручну; **чек_список** — з Checkbox; **чек_авто** — авто; "
        "**смс_готово** — «Готово». "
        "**Вартість ТТН** / **Сума чеку** зберігаються в аркуші на момент події; "
        "у таблиці нижче спочатку показуються вони, далі — підстановка з таблиці замовлень "
        "і архіву Checkbox. "
        "**Зелений** = збіг сум (±0,01 грн), **червоний** = розбіжність, коли обидва числа відомі."
    )
    if st.button("Оновити журнал", key="audit_refresh"):
        cached_audit_log_df.clear()
        st.rerun()
    adf = cached_audit_log_df()
    if adf.empty:
        st.info("Поки немає записів — після дій з’являться тут і в таблиці LogisticAudit.")
        return
    chk_df = fetch_checkbox_archive()
    disp = enrich_audit_table(adf, st.session_state.df, chk_df)
    styled = style_audit_amounts(disp).format(
        {"Вартість ТТН": "{:.2f}", "Сума чеку": "{:.2f}"},
        na_rep="—",
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)
