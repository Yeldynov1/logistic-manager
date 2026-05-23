"""Вкладка «Таблиця» — редагування замовлень (tab2)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import config
import sheets
import utils
from core.messages import ensure_messages_exist
from core.table_data import (
    apply_table_column_order,
    ensure_columns,
    get_table_column_order,
    persist_table_column_order,
    restore_leading_zero,
)
from tabs.tab1_checkout import check_sms_text

def _coalesce_edited_table(editor_value, base: pd.DataFrame | None = None) -> pd.DataFrame | None:
    """Повертає повну таблицю з data_editor (return value або session_state з edited_rows)."""
    base = (base if base is not None else st.session_state.get("df")).copy()
    if editor_value is None:
        return None
    if isinstance(editor_value, pd.DataFrame):
        return editor_value.copy()
    if not isinstance(editor_value, dict):
        return None
    df = base.copy()
    for idx, changes in (editor_value.get("edited_rows") or {}).items():
        i = int(idx)
        if i not in df.index:
            continue
        for col, val in (changes or {}).items():
            if col in df.columns:
                df.at[i, col] = val
    for idx in sorted((editor_value.get("deleted_rows") or []), reverse=True):
        i = int(idx)
        if i in df.index:
            df = df.drop(index=i)
    added = editor_value.get("added_rows") or []
    if added:
        df = pd.concat([df, pd.DataFrame(added)], ignore_index=True)
    return df.reset_index(drop=True)


def _prepare_table_df_for_save(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_columns(df.copy())
    df = apply_table_column_order(df)
    if "ТТН" in df.columns:
        df["ТТН"] = df["ТТН"].apply(restore_leading_zero)
    text_cols = [
        "ТТН",
        "Служба",
        "Статус",
        "Дата",
        "Телефон",
        "Чек",
        "Повідомлення",
        "Статус СМС",
        "Статус Нагадування",
        "Номер накладної",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", "").str.strip()
    if "Номер накладної" in df.columns:
        df["Номер накладної"] = df["Номер накладної"].apply(utils.normalize_invoice_number)
    if "Вартість" in df.columns:
        df["Вартість"] = (
            df["Вартість"]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace(r"\s+", "", regex=True)
        )
        df["Вартість"] = pd.to_numeric(df["Вартість"], errors="coerce").fillna(0.0)
    if "Дія" in df.columns:
        df["Дія"] = (
            df["Дія"]
            .replace({"True": True, "False": False, "": False, "FALSE": False, "TRUE": True, 1: True, 0: False})
            .infer_objects(copy=False)
            .fillna(False)
            .astype(bool)
        )
    if "Дата" in df.columns:
        df["Дата"] = df["Дата"].apply(utils.normalize_date)
    return ensure_messages_exist(df)


def _table_data_changed(candidate: pd.DataFrame, baseline: pd.DataFrame) -> bool:
    a = _prepare_table_df_for_save(candidate)
    b = _prepare_table_df_for_save(baseline)
    if len(a) != len(b):
        return True
    cols = [c for c in config.COLS if c in a.columns and c in b.columns]
    a = a[cols].reset_index(drop=True)
    b = b[cols].reset_index(drop=True)
    for col in cols:
        if col == "Вартість":
            if not pd.to_numeric(a[col], errors="coerce").fillna(0).equals(
                pd.to_numeric(b[col], errors="coerce").fillna(0)
            ):
                return True
        elif col == "Дія":
            if not a[col].astype(bool).equals(b[col].astype(bool)):
                return True
        else:
            if not a[col].astype(str).equals(b[col].astype(str)):
                return True
    return False


def _resolve_row_index(df: pd.DataFrame, pos: int):
    """Індекс рядка в df за позицією в таблиці (0, 1, 2…)."""
    if pos in df.index:
        return pos
    if 0 <= pos < len(df):
        return df.index[pos]
    return None


def _normalize_table_cell(col: str, val):
    if val is None:
        return ""
    if col == "ТТН":
        return restore_leading_zero(str(val))
    if col == "Номер накладної":
        return utils.normalize_invoice_number(str(val))
    if col == "Вартість":
        s = str(val).replace(",", ".").strip()
        return float(pd.to_numeric(s, errors="coerce") or 0.0)
    if col == "Дія":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("true", "1", "так")
    if col == "Дата":
        return utils.normalize_date(str(val))
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def _refresh_row_message_if_needed(df: pd.DataFrame, row_key) -> bool:
    """Оновлює «Повідомлення» для одного рядка після зміни чека."""
    if row_key is None or "Чек" not in df.columns or "Повідомлення" not in df.columns:
        return False
    row = df.loc[row_key]
    if utils.row_receipt_not_required(row):
        return False
    if str(row.get("Статус СМС", "")).strip() == "Отправлено":
        return False
    link = str(row.get("Чек", "")).strip()
    if not link or len(link) < 5 or link.lower() == "nan":
        return False
    if not utils.status_has_any(str(row.get("Статус", "")).lower(), utils.DELIVERED_STATUS_KEYWORDS):
        return False
    msg_val = str(row.get("Повідомлення", "")).strip()
    if len(msg_val) > 5 and msg_val.lower() != "nan" and link in msg_val:
        return False
    new_msg = check_sms_text(link)
    df.at[row_key, "Повідомлення"] = new_msg
    if "Статус СМС" in df.columns and len(str(row.get("Телефон", "")).strip()) > 5:
        df.at[row_key, "Статус СМС"] = "Не отправлено"
    return True


def _tab2_display_dataframe(col_order):
    """Таблиця з session_state (після autosave значення вже в тому ж рядку)."""
    return apply_table_column_order(st.session_state.df, col_order)


def _render_tab2_scroll_preserve():
    """Зберігає прокрутку сторінки між rerun; ніколи не викликає scrollTo(0,0)."""
    components.html(
        """
<script>
(function () {
  const win = window.parent;
  const KEY = "logistic_tab2_page_y";
  try {
    const y = parseInt(sessionStorage.getItem(KEY) || "0", 10) || 0;
    if (y > 40) win.scrollTo(0, y);
  } catch (e) {}
  if (!win._logisticTab2Preserve) {
    win._logisticTab2Preserve = true;
    win.addEventListener(
      "scroll",
      function () {
        if ((win.scrollY || 0) > 40) {
          try { sessionStorage.setItem(KEY, String(win.scrollY)); } catch (e) {}
        }
      },
      { passive: true }
    );
  }
})();
</script>
        """,
        height=0,
        width=0,
    )


def _cell_values_equal(col: str, a, b) -> bool:
    return str(_normalize_table_cell(col, a)) == str(_normalize_table_cell(col, b))


def _tab2_editor_baseline() -> pd.DataFrame:
    b = st.session_state.get("_tab2_editor_baseline")
    if b is None or not isinstance(b, pd.DataFrame):
        b = st.session_state.df.copy()
        st.session_state._tab2_editor_baseline = b
    return b


def _tab2_reset_baseline():
    st.session_state._tab2_editor_baseline = st.session_state.df.copy()


def _edited_rows_from_main(main_state) -> dict:
    if not isinstance(main_state, dict):
        return {}
    return {int(k): dict(v) for k, v in (main_state.get("edited_rows") or {}).items()}


def _filter_rows_vs_baseline(edited_rows: dict) -> dict:
    if not edited_rows:
        return {}
    base = apply_table_column_order(_tab2_editor_baseline()).reset_index(drop=True)
    out = {}
    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        if row_pos < 0 or row_pos >= len(base):
            continue
        real = {}
        for col, val in (changes or {}).items():
            if col not in base.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, val, base.at[row_pos, col]):
                real[col] = val
        if real:
            out[row_pos] = real
    return out


def _editor_df_from_value(value) -> pd.DataFrame | None:
    if isinstance(value, pd.DataFrame):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, pd.DataFrame):
        return data
    return None


def _diff_edited_rows(baseline: pd.DataFrame, current: pd.DataFrame) -> dict:
    """Порівняння таблиці з редактором і baseline — зміни з останнього збереження."""
    b = apply_table_column_order(baseline).reset_index(drop=True)
    c = apply_table_column_order(current).reset_index(drop=True)
    n = min(len(b), len(c))
    edited_rows = {}
    for i in range(n):
        changes = {}
        for col in config.COLS:
            if col not in b.columns or col not in c.columns or col == "Дія":
                continue
            if not _cell_values_equal(col, b.at[i, col], c.at[i, col]):
                changes[col] = c.at[i, col]
        if changes:
            edited_rows[i] = changes
    return edited_rows


def _apply_partial_edits(edited_rows: dict) -> bool:
    if not edited_rows:
        return False
    df = st.session_state.df
    extra_sheet_cells = []
    norm_for_sheet = {}

    for idx, changes in edited_rows.items():
        row_pos = int(idx)
        row_key = _resolve_row_index(df, row_pos)
        if row_key is None:
            continue
        norm_for_sheet[row_pos] = {}
        for col, val in (changes or {}).items():
            if col not in df.columns or col == "Дія":
                continue
            norm = _normalize_table_cell(col, val)
            df.at[row_key, col] = norm
            norm_for_sheet[row_pos][col] = norm
        if "Чек" in (changes or {}) and _refresh_row_message_if_needed(df, row_key):
            extra_sheet_cells.append(
                (row_pos, "Повідомлення", df.at[row_key, "Повідомлення"])
            )
            if "Статус СМС" in df.columns:
                extra_sheet_cells.append(
                    (row_pos, "Статус СМС", df.at[row_key, "Статус СМС"])
                )

    if not sheets.update_table_cell_edits(norm_for_sheet, extra_sheet_cells):
        return False
    _tab2_reset_baseline()
    return True


def _autosave_table_edits_partial(editor_value=None, edited_df=None) -> bool:
    """Зберігає лише змінені комірки."""
    if isinstance(editor_value, dict) and (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        return _autosave_table_if_changed(editor_value, show_toast=False)

    baseline = _tab2_editor_baseline()
    from_main = _edited_rows_from_main(editor_value)
    current = _editor_df_from_value(edited_df)
    from_diff = _diff_edited_rows(baseline, current) if current is not None else {}
    merged = dict(from_main)
    for row, cols in from_diff.items():
        merged.setdefault(int(row), {}).update(cols)
    edited_rows = _filter_rows_vs_baseline(merged)

    return _apply_partial_edits(edited_rows)


def _autosave_table_from_editor(edited_df) -> bool:
    """Fallback autosave після data_editor."""
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)
    return _autosave_table_edits_partial(editor_value=main, edited_df=edited_df)


def _autosave_table_if_changed(editor_value=None, *, show_toast: bool = False) -> bool:
    if isinstance(editor_value, dict) and editor_value.get("edited_rows") and not (
        editor_value.get("deleted_rows") or editor_value.get("added_rows")
    ):
        if _autosave_table_edits_partial(editor_value):
            if show_toast:
                st.session_state._tab2_autosave_ok = True
            return True
        return False
    edited = _coalesce_edited_table(editor_value)
    if edited is None:
        return False
    prepared = _prepare_table_df_for_save(edited)
    if not _table_data_changed(prepared, st.session_state.df):
        return False
    if sheets.save_manual(prepared, clear_cache=False, merge_session=True):
        if show_toast:
            st.session_state._tab2_autosave_ok = True
        return True
    return False


def _try_sync_column_order_from_editor(editor_df: pd.DataFrame | None = None):
    """Порядок колонок — лише drag у dict-стані (не з return DataFrame — інакше «оновлює все»)."""
    main = st.session_state.get("main")
    if not isinstance(main, dict):
        return
    cols = [str(c) for c in (main.get("column_order") or []) if c in config.COLS]
    if not cols:
        return
    norm = normalize_table_column_order(cols)
    if norm != get_table_column_order():
        persist_table_column_order(norm)
        st.session_state.df = apply_table_column_order(st.session_state.df, norm)

def _autosave_table_on_edit():
    """Зберегти в callback, поки edited_rows ще в session_state (2-ге редагування)."""
    st.session_state.pop("_tab2_saved_in_callback", None)
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        st.session_state["_tab2_pending_save"] = "full"
        return
    to_save = _filter_rows_vs_baseline(_edited_rows_from_main(main))
    if to_save and _apply_partial_edits(to_save):
        st.session_state["_tab2_saved_in_callback"] = True
        return
    st.session_state["_tab2_pending_save"] = True


def _mark_tab2_saved():
    try:
        st.toast("Збережено", icon="✅")
    except Exception:
        pass


def _save_table_from_editor(edited_df=None) -> bool:
    """Зберегти таблицю вручну: частково або повністю."""
    if isinstance(edited_df, pd.DataFrame):
        if _autosave_table_from_editor(edited_df):
            return True
    main = st.session_state.get("main")
    if isinstance(main, dict) and (main.get("deleted_rows") or main.get("added_rows")):
        return _autosave_table_if_changed(main, show_toast=False)
    if isinstance(main, dict) and main.get("edited_rows"):
        if _autosave_table_edits_partial(editor_value=main, edited_df=edited_df):
            return True
    src = _coalesce_edited_table(main) if main else None
    if src is None and isinstance(edited_df, pd.DataFrame):
        src = edited_df
    if src is None:
        src = st.session_state.df
    prepared = _prepare_table_df_for_save(src)
    return sheets.save_manual(prepared, clear_cache=False, merge_session=True)


@st.fragment
def render_fragment():
    """Окремий фрагмент: автозбереження після редагування (без окремої кнопки)."""
    _tab2_editor_baseline()
    _render_tab2_scroll_preserve()
    col_order = get_table_column_order()
    display_df = _tab2_display_dataframe(col_order)

    with st.expander("↔️ Порядок колонок", expanded=False):
        order = list(col_order)
        for i, col in enumerate(order):
            c1, c2, c3 = st.columns([6, 1, 1])
            with c1:
                st.markdown(f"**{i + 1}.** {col}")
            with c2:
                if st.button("↑", key=f"tab2_col_up_{col}", disabled=(i == 0)):
                    new_order = list(order)
                    new_order[i], new_order[i - 1] = new_order[i - 1], new_order[i]
                    persist_table_column_order(new_order)
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
            with c3:
                if st.button("↓", key=f"tab2_col_dn_{col}", disabled=(i == len(order) - 1)):
                    new_order = list(order)
                    new_order[i], new_order[i + 1] = new_order[i + 1], new_order[i]
                    persist_table_column_order(new_order)
                    st.session_state.df = apply_table_column_order(st.session_state.df, new_order)
                    st.rerun()
        if st.button("Скинути порядок колонок", key="tab2_col_reset"):
            persist_table_column_order(list(config.COLS))
            st.session_state.df = apply_table_column_order(st.session_state.df, config.COLS)
            st.rerun()

    edited_df = st.data_editor(
        display_df.style.map(utils.color_status, subset=["Статус"]),
        key="main",
        height=600,
        use_container_width=True,
        hide_index=True,
        column_order=col_order,
        on_change=_autosave_table_on_edit,
        column_config={
            "Дія": None,
            "Статус": st.column_config.TextColumn(width="large", disabled=True),
            "Чек": st.column_config.LinkColumn(display_text="🧾"),
            "Статус СМС": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "Статус Нагадування": st.column_config.SelectboxColumn(
                options=["", "Отправлено", "Не отправлено"]
            ),
            "ТТН": st.column_config.TextColumn(help="Meest, НП, УП"),
        },
    )
    if st.session_state.pop("_tab2_saved_in_callback", False):
        _mark_tab2_saved()
    pending = st.session_state.pop("_tab2_pending_save", False)
    if pending:
        ok = False
        if pending == "full":
            main = st.session_state.get("main")
            ok = _autosave_table_if_changed(main, show_toast=False)
        else:
            ok = _autosave_table_from_editor(edited_df)
        if ok:
            _mark_tab2_saved()

    if st.button(
        "💾 Зберегти",
        type="primary",
        use_container_width=True,
        key="tab2_manual_save",
    ):
        if _save_table_from_editor(edited_df):
            _mark_tab2_saved()
        else:
            st.error("Не вдалося зберегти таблицю.")

    st.caption(
        "Зміни зберігаються автоматично після Enter або кліку поза коміркою. "
        "Кнопка «Зберегти» — на всяк випадок, якщо автозбереження не спрацювало."
    )
