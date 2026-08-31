"""CRUD Supabase — ті самі колонки, що в Google Sheets (для сумісності з app.py)."""
from __future__ import annotations

import json
import math

import pandas as pd

import config
import sheets
import utils
from storage.supabase_client import get_client

_UP_HEADERS = sheets.UP_SHIPMENTS_HEADERS
_AUDIT_HEADERS = sheets.AUDIT_HEADERS


def _normalize_bc(barcode) -> str:
    return sheets._normalize_up_bc(barcode)


def _parse_ts(val) -> str:
    s = str(val or "").strip()
    if not s or s.lower() == "nan":
        return utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S")
    try:
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return s[:19]
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s[:19]


def _float_or_none(val):
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(val, str) and not val.strip():
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (TypeError, ValueError):
            return None
    s = str(val).strip().replace(",", ".").replace(" ", "")
    if not s or s.lower() in ("nan", "none", "null", "n/a", "#n/a", "-", "—"):
        return None
    try:
        f = float(s)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _sheet_cell(row, col: str):
    try:
        if hasattr(row, "index") and col in row.index:
            return row[col]
    except Exception:
        pass
    try:
        return row.get(col)
    except Exception:
        return None


def _prune_null_numeric(payload: dict, keys: tuple[str, ...]) -> dict:
    """Не відправляти в Postgres '' або None у float-колонках."""
    out = dict(payload)
    for k in keys:
        if k not in out:
            continue
        v = _float_or_none(out[k])
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def _audit_payload_from_sheet_row(row) -> dict:
    payload = {
        "username": str(_sheet_cell(row, "Користувач") or "")[:80],
        "action": str(_sheet_cell(row, "Дія") or "")[:80],
        "ttn": str(_sheet_cell(row, "ТТН") or "")[:40],
        "detail": str(_sheet_cell(row, "Деталі") or "")[:500],
    }
    sc = _float_or_none(_sheet_cell(row, "Вартість ТТН"))
    rs = _float_or_none(_sheet_cell(row, "Сума чеку"))
    if sc is not None:
        payload["ship_cost"] = sc
    if rs is not None:
        payload["receipt_sum"] = rs
    return payload


def import_audit_df(audit_df: pd.DataFrame) -> tuple[int, int, str]:
    """Імпорт audit по одному рядку. Повертає (ok, skipped, last_error)."""
    client = get_client()
    if not client:
        return 0, 0, "Немає клієнта Supabase"
    last_err = ""
    try:
        client.table("audit_log").delete().neq("id", 0).execute()
    except Exception as e:
        last_err = str(e)[:200]
    ok = 0
    skipped = 0
    if audit_df is None or audit_df.empty:
        return 0, 0, last_err
    for _, row in audit_df.iterrows():
        payload = _audit_payload_from_sheet_row(row)
        try:
            client.table("audit_log").insert(payload).execute()
            ok += 1
        except Exception as e:
            skipped += 1
            last_err = str(e)[:200]
    return ok, skipped, last_err


def _order_row_to_db(row: dict) -> dict:
    return {
        "ttn": str(row.get("ТТН", "") or "").strip(),
        "service": str(row.get("Служба", "") or "").strip(),
        "status": str(row.get("Статус", "") or "").strip() or "Нове",
        "created_at": _parse_ts(row.get("_created_at_raw") or row.get("Дата")),
        "phone": str(row.get("Телефон", "") or "").strip(),
        "cost": _float_or_none(row.get("Вартість")) or 0.0,
        "invoice_number": utils.normalize_invoice_number(str(row.get("Номер накладної", "") or "")),
        "check_url": str(row.get("Чек", "") or "").strip(),
        "message": str(row.get("Повідомлення", "") or "").strip(),
        "sms_status": str(row.get("Статус СМС", "") or "").strip(),
        "reminder_status": str(row.get("Статус Нагадування", "") or "").strip(),
    }


def _order_db_to_row(rec: dict) -> dict:
    created = rec.get("created_at") or ""
    return {
        "ТТН": str(rec.get("ttn") or ""),
        "Служба": str(rec.get("service") or ""),
        "Статус": str(rec.get("status") or ""),
        "Дата": _parse_ts(created),
        "Телефон": str(rec.get("phone") or ""),
        "Вартість": rec.get("cost") if rec.get("cost") is not None else 0.0,
        "Номер накладної": str(rec.get("invoice_number") or ""),
        "Чек": str(rec.get("check_url") or ""),
        "Повідомлення": str(rec.get("message") or ""),
        "Статус СМС": str(rec.get("sms_status") or ""),
        "Статус Нагадування": str(rec.get("reminder_status") or ""),
        "Дія": False,
        "_created_at_raw": created,
        "_order_id": rec.get("id"),
    }


def _up_row_to_db(row: dict) -> dict:
    bc = _normalize_bc(row.get("ШКІ", ""))
    payload = {
        "created_at": _parse_ts(row.get("Час")),
        "username": str(row.get("Користувач", "") or "").strip(),
        "barcode": bc,
        "shipment_uuid": str(row.get("UUID", "") or "").strip(),
        "up_status": str(row.get("Статус УП", "") or "").strip(),
        "recipient_name": str(row.get("Отримувач", "") or "").strip(),
        "phone": str(row.get("Телефон", "") or "").strip(),
        "tariff": str(row.get("Тариф", "") or "").strip(),
        "delivery_type": str(row.get("Доставка", "") or "").strip(),
        "delivery_price": _float_or_none(row.get("Вартість")),
        "postpay": _float_or_none(row.get("Післяплата")),
        "description": utils.normalize_invoice_number(str(row.get("Дод. інфо", "") or ""))[:500],
        "postcode": str(row.get("Індекс", "") or "").strip(),
        "city": str(row.get("Місто", "") or "").strip(),
        "api_json": str(row.get("JSON", "") or "")[:45000] or None,
    }
    printed_mark = str(row.get("Надруковано", "") or "").strip()
    if printed_mark:
        payload["printed_mark"] = printed_mark[:160]
    return _prune_null_numeric(payload, ("delivery_price", "postpay"))


def _up_db_to_row(rec: dict) -> dict:
    return {
        "Час": _parse_ts(rec.get("created_at")),
        "Користувач": str(rec.get("username") or ""),
        "ШКІ": _normalize_bc(rec.get("barcode")),
        "UUID": str(rec.get("shipment_uuid") or ""),
        "Статус УП": str(rec.get("up_status") or ""),
        "Отримувач": str(rec.get("recipient_name") or ""),
        "Телефон": str(rec.get("phone") or ""),
        "Тариф": str(rec.get("tariff") or ""),
        "Доставка": str(rec.get("delivery_type") or ""),
        "Вартість": rec.get("delivery_price"),
        "Післяплата": rec.get("postpay"),
        "Дод. інфо": str(rec.get("description") or ""),
        "Індекс": str(rec.get("postcode") or ""),
        "Місто": str(rec.get("city") or ""),
        "JSON": str(rec.get("api_json") or ""),
        "Надруковано": str(rec.get("printed_mark") or ""),
    }


def load_orders_df() -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame(columns=config.COLS)
    try:
        res = (
            client.table("orders")
            .select("*")
            .order("created_at", desc=False)
            .order("id", desc=False)
            .limit(20000)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return pd.DataFrame(columns=config.COLS)
        records = [_order_db_to_row(r) for r in rows]
        df = pd.DataFrame(records)
        return utils.ensure_orders_sorted(df)
    except Exception:
        return pd.DataFrame(columns=config.COLS)


def save_orders_df(df: pd.DataFrame) -> bool:
    client = get_client()
    if not client:
        return False
    try:
        to_save = df.drop(columns=["Дія", "_created_at_raw", "_order_id"], errors="ignore")
        payload = [_order_row_to_db(r) for _, r in to_save.iterrows()]
        client.table("orders").delete().neq("id", 0).execute()
        if payload:
            # Supabase batch insert (chunks of 500)
            for i in range(0, len(payload), 500):
                client.table("orders").insert(payload[i : i + 500]).execute()
        return True
    except Exception:
        return False


def insert_new_orders_df(df: pd.DataFrame) -> tuple[int, str]:
    """Додати лише відсутні ТТН, не видаляючи таблицю orders.

    Цей шлях використовує автопошук: одна сесія не може затерти
    додані паралельно іншою сесією рядки.
    """
    client = get_client()
    if not client:
        return 0, "Немає підключення до Supabase."
    if not isinstance(df, pd.DataFrame) or df.empty:
        return 0, ""
    try:
        to_save = df.drop(
            columns=["Дія", "_created_at_raw", "_order_id"], errors="ignore"
        )
        unique_rows: dict[str, dict] = {}
        for _, row in to_save.iterrows():
            payload = _order_row_to_db(row)
            ttn = str(payload.get("ttn") or "").strip()
            if ttn and ttn not in unique_rows:
                unique_rows[ttn] = payload
        if not unique_rows:
            return 0, ""

        ttns = list(unique_rows)
        existing_res = client.table("orders").select("ttn").in_("ttn", ttns).execute()
        existing = {
            str(item.get("ttn") or "").strip()
            for item in (existing_res.data or [])
            if isinstance(item, dict)
        }

        inserted = 0
        errors: list[str] = []
        # По одному: якщо інша сесія встигла додати ту саму ТТН,
        # unique-index зупинить лише цей рядок, а не весь пакет.
        for ttn, payload in unique_rows.items():
            if ttn in existing:
                continue
            try:
                client.table("orders").insert(payload).execute()
                inserted += 1
            except Exception as exc:
                try:
                    check = (
                        client.table("orders")
                        .select("ttn")
                        .eq("ttn", ttn)
                        .limit(1)
                        .execute()
                    )
                    if check.data:
                        continue
                except Exception:
                    pass
                errors.append(f"{ttn}: {str(exc)[:120]}")
        return inserted, "; ".join(errors[:3])
    except Exception as exc:
        return 0, str(exc)[:300]


_ORDER_SHEET_TO_DB = {
    "ТТН": "ttn",
    "Служба": "service",
    "Статус": "status",
    "Дата": "created_at",
    "Телефон": "phone",
    "Вартість": "cost",
    "Номер накладної": "invoice_number",
    "Чек": "check_url",
    "Повідомлення": "message",
    "Статус СМС": "sms_status",
    "Статус Нагадування": "reminder_status",
}


def _ttn_from_df_pos(df: pd.DataFrame, pos: int) -> str:
    pos = int(pos)
    if pos < 0 or pos >= len(df):
        return ""
    return str(df.iloc[pos].get("ТТН", "") or "").strip()


def _df_cell_to_db(col: str, val):
    col = str(col).strip()
    db_col = _ORDER_SHEET_TO_DB.get(col)
    if not db_col:
        return None, None
    if db_col == "cost":
        return db_col, _float_or_none(val) or 0.0
    if db_col == "invoice_number":
        return db_col, utils.normalize_invoice_number(str(val or ""))
    if db_col == "created_at":
        return db_col, _parse_ts(val)
    if val is None:
        return db_col, ""
    if isinstance(val, bool):
        return db_col, val
    if isinstance(val, float) and col == "Вартість":
        return db_col, val
    return db_col, str(val).strip()


def delete_orders_by_ttns(ttns: list[str]) -> bool:
    client = get_client()
    if not client:
        return False
    unique = list(dict.fromkeys(t for t in ttns if t))
    if not unique:
        return True
    try:
        client.table("orders").delete().in_("ttn", unique).execute()
        return True
    except Exception:
        return False


def validate_order_ttns(ttns: list[str]) -> bool:
    client = get_client()
    unique = list(dict.fromkeys(str(t or "").strip() for t in ttns if str(t or "").strip()))
    if not client or not unique:
        return False
    try:
        result = client.table("orders").select("ttn").in_("ttn", unique).execute()
        found = [str(row.get("ttn") or "").strip() for row in (result.data or [])]
        return len(found) == len(unique) and set(found) == set(unique)
    except Exception:
        return False


def update_order_cells_by_ttn(ttn: str, changes: dict) -> bool:
    client = get_client()
    label = str(ttn or "").strip()
    if not client or not label:
        return False
    payload = {}
    for col, val in (changes or {}).items():
        if str(col).strip() == "Дія":
            continue
        db_col, db_val = _df_cell_to_db(col, val)
        if db_col:
            payload[db_col] = db_val
    if not payload:
        return True
    try:
        existing = (
            client.table("orders")
            .select("id")
            .eq("ttn", label)
            .limit(2)
            .execute()
        )
        rows = existing.data or []
        if len(rows) != 1:
            return False
        client.table("orders").update(payload).eq("id", rows[0]["id"]).execute()
        return True
    except Exception:
        return False


def fill_missing_order_invoices_by_ttn(
    updates: list[tuple[str, str]],
) -> tuple[int, str]:
    client = get_client()
    if not client or not updates:
        return 0, "Немає з’єднання з Supabase."
    labels = [str(ttn or "").strip() for ttn, _ in updates]
    try:
        result = (
            client.table("orders")
            .select("id,ttn,invoice_number")
            .in_("ttn", labels)
            .execute()
        )
        rows = result.data or []
        by_ttn: dict[str, list[dict]] = {}
        for row in rows:
            by_ttn.setdefault(str(row.get("ttn") or "").strip(), []).append(row)
        if any(len(by_ttn.get(label, [])) != 1 for label in labels):
            return 0, "Не всі ТТН для номерів накладних знайдені однозначно."
        written = 0
        for ttn, invoice in updates:
            row = by_ttn[str(ttn).strip()][0]
            if utils.normalize_invoice_number(row.get("invoice_number", "")):
                continue
            client.table("orders").update(
                {"invoice_number": utils.normalize_invoice_number(invoice)}
            ).eq("id", row["id"]).execute()
            written += 1
        return written, ""
    except Exception as exc:
        return 0, f"Помилка Supabase: {exc}"


def delete_orders_at_positions(df: pd.DataFrame, positions: list) -> bool:
    ttns = [_ttn_from_df_pos(df, p) for p in positions]
    return delete_orders_by_ttns(ttns)


def update_orders_cell_edits(
    edited_rows: dict | None,
    df: pd.DataFrame,
    extra_cells=None,
) -> bool:
    client = get_client()
    if not client:
        return False
    changes_by_pos: dict[int, dict] = {}
    for pos, changes in (edited_rows or {}).items():
        p = int(pos)
        changes_by_pos.setdefault(p, {})
        for col, val in (changes or {}).items():
            changes_by_pos[p][col] = val
    for row_pos, col_name, value in extra_cells or []:
        p = int(row_pos)
        changes_by_pos.setdefault(p, {})
        changes_by_pos[p][str(col_name).strip()] = value
    if not changes_by_pos:
        return True
    try:
        for pos, changes in changes_by_pos.items():
            ttn = _ttn_from_df_pos(df, pos)
            if not ttn:
                continue
            payload = {}
            for col, val in changes.items():
                if str(col).strip() == "Дія":
                    continue
                db_col, db_val = _df_cell_to_db(col, val)
                if db_col:
                    payload[db_col] = db_val
            if payload:
                client.table("orders").update(payload).eq("ttn", ttn).execute()
        return True
    except Exception:
        return False


def read_up_shipments_df(*, include_json: bool = False) -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame(columns=_UP_HEADERS)
    base_cols = (
        "created_at,username,barcode,shipment_uuid,up_status,recipient_name,"
        "phone,tariff,delivery_type,delivery_price,postpay,description,postcode,city,api_json"
    )
    try:
        try:
            res = (
                client.table("up_shipments")
                .select(base_cols + ",printed_mark")
                .order("created_at", desc=True)
                .limit(10000)
                .execute()
            )
        except Exception:
            # Сумісність до виконання ALTER TABLE з новою колонкою друку.
            res = (
                client.table("up_shipments")
                .select(base_cols)
                .order("created_at", desc=True)
                .limit(10000)
                .execute()
            )
        rows = res.data or []
        records = []
        for r in rows:
            rec = _up_db_to_row(r)
            if not include_json:
                rec["JSON"] = ""
            if rec.get("ШКІ"):
                records.append(rec)
        return sheets._dataframe_from_up_records(records)
    except Exception:
        return pd.DataFrame(columns=_UP_HEADERS)


def read_up_shipment_json(barcode: str) -> str:
    client = get_client()
    if not client:
        return ""
    bc = _normalize_bc(barcode)
    if not bc:
        return ""
    try:
        res = (
            client.table("up_shipments")
            .select("api_json")
            .eq("barcode", bc)
            .limit(1)
            .execute()
        )
        if res.data:
            return str(res.data[0].get("api_json") or "")[:45000]
    except Exception:
        pass
    return ""


def append_up_shipment_record(row: dict) -> bool:
    client = get_client()
    if not client:
        return False
    payload = _up_row_to_db(row)
    bc = payload.get("barcode") or ""
    if not bc:
        return False
    try:
        existing = (
            client.table("up_shipments")
            .select("id,description")
            .eq("barcode", bc)
            .limit(1)
            .execute()
        )
        if existing.data:
            old = existing.data[0]
            if not str(payload.get("description") or "").strip():
                payload["description"] = str(old.get("description") or "")
            payload.pop("created_at", None)
            client.table("up_shipments").update(payload).eq("id", old["id"]).execute()
        else:
            if not payload.get("created_at"):
                payload["created_at"] = utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S")
            client.table("up_shipments").insert(payload).execute()
        return True
    except Exception:
        return False


def patch_up_shipment_description(barcode: str, description: str) -> bool:
    client = get_client()
    if not client:
        return False
    bc = _normalize_bc(barcode)
    if not bc:
        return False
    val = utils.normalize_invoice_number(str(description or "").strip())[:500]
    try:
        res = client.table("up_shipments").update({"description": val}).eq("barcode", bc).execute()
        return bool(res.data)
    except Exception:
        return False


def patch_up_shipment_status(barcode: str, status: str) -> bool:
    client = get_client()
    if not client:
        return False
    bc = _normalize_bc(barcode)
    if not bc:
        return False
    val = str(status or "").strip()[:120]
    if not val:
        return False
    try:
        res = client.table("up_shipments").update({"up_status": val}).eq("barcode", bc).execute()
        return bool(res.data)
    except Exception:
        return False


def mark_up_shipments_printed(
    barcodes: list[str],
    *,
    printed: bool = True,
    username: str = "",
) -> int:
    client = get_client()
    values = list(dict.fromkeys(_normalize_bc(value) for value in barcodes or []))
    values = [value for value in values if value]
    if not client or not values:
        return 0
    marker = ""
    if printed:
        marker = utils.now_kyiv_naive().strftime("%Y-%m-%d %H:%M:%S")
        user = str(username or "").strip()
        if user:
            marker += f" · {user[:80]}"
    try:
        res = (
            client.table("up_shipments")
            .update({"printed_mark": marker})
            .in_("barcode", values)
            .execute()
        )
        return len(res.data or [])
    except Exception:
        return 0


def delete_up_shipment_record(barcode: str) -> bool:
    client = get_client()
    if not client:
        return False
    bc = _normalize_bc(barcode)
    if not bc:
        return False
    try:
        client.table("up_shipments").delete().eq("barcode", bc).execute()
        return True
    except Exception:
        return False


def append_audit_log(user, action, ttn="", detail="", ship_cost=None, receipt_sum=None) -> bool:
    client = get_client()
    if not client:
        return False
    row = _prune_null_numeric(
        {
            "username": str(user or "?")[:80],
            "action": str(action or "")[:80],
            "ttn": str(ttn or "")[:40],
            "detail": str(detail or "")[:500],
            "ship_cost": ship_cost,
            "receipt_sum": receipt_sum,
        },
        ("ship_cost", "receipt_sum"),
    )
    try:
        client.table("audit_log").insert(row).execute()
        return True
    except Exception:
        return False


def read_audit_log_df() -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame(columns=_AUDIT_HEADERS)
    try:
        res = (
            client.table("audit_log")
            .select("*")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        rows = res.data or []
        records = []
        for r in rows:
            records.append(
                {
                    "Час": _parse_ts(r.get("created_at")),
                    "Користувач": str(r.get("username") or ""),
                    "Дія": str(r.get("action") or ""),
                    "ТТН": str(r.get("ttn") or ""),
                    "Деталі": str(r.get("detail") or ""),
                    "Вартість ТТН": r.get("ship_cost"),
                    "Сума чеку": r.get("receipt_sum"),
                }
            )
        df = pd.DataFrame(records)
        for h in _AUDIT_HEADERS:
            if h not in df.columns:
                df[h] = ""
        return df[_AUDIT_HEADERS] if not df.empty else pd.DataFrame(columns=_AUDIT_HEADERS)
    except Exception:
        return pd.DataFrame(columns=_AUDIT_HEADERS)


def load_table_column_order(username: str):
    client = get_client()
    if not client:
        return None
    user = str(username or "").strip().lower()
    if not user:
        return None
    try:
        res = client.table("ui_settings").select("column_order").eq("username", user).limit(1).execute()
        if not res.data:
            return None
        raw = res.data[0].get("column_order")
        if isinstance(raw, list) and raw:
            return [str(c) for c in raw]
        if isinstance(raw, str) and raw.strip():
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(c) for c in parsed]
    except Exception:
        return None
    return None


def save_table_column_order(username: str, column_order: list) -> bool:
    client = get_client()
    if not client:
        return False
    user = str(username or "").strip().lower()
    if not user or not column_order:
        return False
    try:
        client.table("ui_settings").upsert(
            {"username": user, "column_order": column_order},
            on_conflict="username",
        ).execute()
        return True
    except Exception:
        return False


def _tab_access_ui_username(role_key: str) -> str:
    return f"_tab_access_{role_key}"


def _parse_tab_visibility_raw(raw) -> dict | None:
    if isinstance(raw, dict):
        if "visible_tabs" in raw and isinstance(raw["visible_tabs"], dict):
            return raw["visible_tabs"]
        if any(k in raw for k in ("checkout", "table", "up_ttn", "rozetka")):
            return raw
    if isinstance(raw, list):
        return {str(k): True for k in raw}
    return None


def load_role_settings(role: str = "manager") -> dict | None:
    client = get_client()
    if not client:
        return None
    role_key = str(role or "manager").strip().lower()
    if not role_key:
        return None
    try:
        res = (
            client.table("role_settings")
            .select("settings")
            .eq("role", role_key)
            .limit(1)
            .execute()
        )
        if res.data:
            raw = res.data[0].get("settings")
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
    except Exception:
        pass
    try:
        res = (
            client.table("ui_settings")
            .select("column_order")
            .eq("username", _tab_access_ui_username(role_key))
            .limit(1)
            .execute()
        )
        if res.data:
            raw = res.data[0].get("column_order")
            if isinstance(raw, dict):
                return raw
    except Exception:
        return None
    return {}


def save_role_settings(role: str, settings: dict) -> tuple[bool, str]:
    client = get_client()
    if not client:
        return False, "Немає підключення до Supabase (SUPABASE_URL / SUPABASE_SERVICE_KEY)."
    role_key = str(role or "manager").strip().lower()
    if not role_key or not isinstance(settings, dict):
        return False, "Порожні дані для збереження."
    import streamlit as st

    updated_by = str(st.session_state.get("auth_user", "") or "").strip()
    last_err = ""
    try:
        client.table("role_settings").upsert(
            {
                "role": role_key,
                "settings": settings,
                "updated_by": updated_by,
            },
            on_conflict="role",
        ).execute()
        return True, ""
    except Exception as e:
        last_err = str(e)[:300]
    try:
        client.table("ui_settings").upsert(
            {
                "username": _tab_access_ui_username(role_key),
                "column_order": settings,
            },
            on_conflict="username",
        ).execute()
        return True, ""
    except Exception as e2:
        hint = str(e2)[:300]
        if last_err:
            hint = f"{last_err}; fallback ui_settings: {hint}"
        return False, hint


def load_manager_tab_visibility(role: str = "manager"):
    settings = load_role_settings(role)
    if not settings:
        return None
    parsed = _parse_tab_visibility_raw(settings)
    if parsed:
        return parsed
    return None


def save_manager_tab_visibility(role: str, visibility: dict) -> tuple[bool, str]:
    role_key = str(role or "manager").strip().lower()
    if not role_key or not isinstance(visibility, dict):
        return False, "Порожні дані для збереження."
    current = load_role_settings(role_key) or {}
    merged = dict(current) if isinstance(current, dict) else {}
    if "visible_tabs" not in merged and _parse_tab_visibility_raw(merged):
        merged = {"visible_tabs": _parse_tab_visibility_raw(merged), **{
            k: v for k, v in merged.items() if k not in ("checkout", "table", "up_ttn", "rozetka", "promua", "epicentr", "refusals", "archive", "reminders", "audit")
        }}
    merged["visible_tabs"] = visibility
    return save_role_settings(role_key, merged)
