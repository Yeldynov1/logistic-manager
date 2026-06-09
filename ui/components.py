"""Дрібні переиспользувані UI-компоненти."""
from __future__ import annotations

import html
import re

import streamlit as st
import streamlit.components.v1 as components

import utils


def render_smart_buttons(phone, message, row_key=None):
    if not phone or len(str(phone)) < 10:
        st.caption("Невірний телефон")
        return
    raw_phone = str(phone)
    digits = "".join(filter(str.isdigit, raw_phone))
    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    if len(digits) != 12:
        st.caption(f"Формат? {raw_phone}")
        return
    msg_safe = (
        str(message)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("'", "\\'")
    )
    token_raw = f"{digits}_{row_key if row_key is not None else 'default'}"
    token = re.sub(r"[^0-9A-Za-z_]", "_", token_raw)
    js_code = f"""<script>function clickHandler_{token}(type) {{ const text = '{msg_safe}'; const url = type === 'viber' ? 'viber://chat?number=%2B{digits}' : 'sms:+{digits}'; const el = document.createElement('textarea'); el.value = text; document.body.appendChild(el); el.select(); document.execCommand('copy'); document.body.removeChild(el); const link = document.createElement('a'); link.href = url; document.body.appendChild(link); link.click(); document.body.removeChild(link); }}</script><div style="display: flex; flex-direction: column; gap: 8px;"><button onclick="clickHandler_{token}('viber')" style="background-color: #7360f2; color: white; border: none; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">💬 Viber</button><button onclick="clickHandler_{token}('sms')" style="background-color: #f0f2f6; color: #31333F; border: 1px solid #ccc; padding: 10px; border-radius: 8px; font-weight: bold; cursor: pointer; width: 100%;">📩 SMS</button></div>"""
    components.html(js_code, height=100)


def render_copyable_invoice(invoice_num, row_key):
    inv = utils.normalize_invoice_number(invoice_num)
    if not inv or inv.lower() == "nan":
        return
    inv_safe = html.escape(inv).replace("\\", "\\\\").replace("'", "\\'")
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"invoice_{row_key}")
    js_code = f"""
<script>
function showCopied_{token}() {{
  const el = document.getElementById('copied_{token}');
  if (!el) return;
  el.style.opacity = '1';
  setTimeout(() => {{ el.style.opacity = '0'; }}, 1200);
}}
function copyInvoice_{token}() {{
  const text = '{inv_safe}';
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text);
    showCopied_{token}();
    return;
  }}
  const el = document.createElement('textarea');
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  showCopied_{token}();
}}
</script>
<div style="margin-top: 4px; display: flex; align-items: center; gap: 8px;">
  <button onclick="copyInvoice_{token}()"
          title="Натисніть, щоб скопіювати номер"
          style="background: transparent; border: none; color: #1f77b4; cursor: pointer; padding: 0; font: inherit; text-decoration: underline; white-space: nowrap; line-height: 1.35;">
    📄 Накладна: {inv_safe}
  </button>
  <span id="copied_{token}" style="opacity: 0; transition: opacity .2s ease; color: #2e7d32; font-size: 13px; font-weight: 600;">✅ Скопійовано</span>
</div>
"""
    components.html(js_code, height=42)


def render_journal_bc_barcode(text: str, row_key: str) -> None:
    """ШКІ + 📋 в одному блоці (без st.copy_button і без другого iframe поруч)."""
    val = str(text or "").strip()
    if not val:
        return
    val_disp = html.escape(val)
    val_safe = val_disp.replace("\\", "\\\\").replace("'", "\\'")
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"bc_{row_key}")
    js_code = f"""
<script>
function showBcCopied_{token}() {{
  const el = document.getElementById('bc_ok_{token}');
  if (!el) return;
  el.style.opacity = '1';
  setTimeout(() => {{ el.style.opacity = '0'; }}, 900);
}}
function copyBc_{token}() {{
  const text = '{val_safe}';
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(showBcCopied_{token});
    return;
  }}
  const el = document.createElement('textarea');
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
  showBcCopied_{token}();
}}
</script>
<div style="display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; margin:0; padding:0; line-height:1.2;">
  <span title="Виділи текст для копіювання"
        style="font-size:0.98rem; font-weight:700; letter-spacing:0.03em; font-variant-numeric:tabular-nums; user-select:all; -webkit-user-select:all; cursor:text; text-align:center; color:#111827; white-space:nowrap;">{val_disp}</span>
  <div style="display:flex; align-items:center; justify-content:center; gap:4px; min-height:1.5rem;">
    <button type="button" onclick="copyBc_{token}()"
            title="Копіювати ШКІ"
            style="min-width:1.6rem; height:1.6rem; padding:0; font-size:0.85rem; line-height:1; border-radius:6px; border:1px solid #D1D5DB; background:#F9FAFB; cursor:pointer;">
      📋
    </button>
    <span id="bc_ok_{token}" style="opacity:0; transition:opacity .2s ease; color:#16A34A; font-size:11px; font-weight:600;">✓</span>
  </div>
</div>
"""
    components.html(js_code, height=54, scrolling=False)
