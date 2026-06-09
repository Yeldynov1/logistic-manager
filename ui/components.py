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


def render_copy_bc_button(text: str, row_key: str) -> None:
    """Кнопка 📋 для копіювання ШКІ (без st.copy_button — сумісність зі Streamlit Cloud)."""
    val = str(text or "").strip()
    if not val:
        return
    val_safe = html.escape(val).replace("\\", "\\\\").replace("'", "\\'")
    token = re.sub(r"[^0-9A-Za-z_]", "_", f"bc_{row_key}")
    js_code = f"""
<script>
function copyBc_{token}() {{
  const text = '{val_safe}';
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text);
    return;
  }}
  const el = document.createElement('textarea');
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
}}
</script>
<div style="display:flex; justify-content:center; align-items:center;">
  <button type="button" onclick="copyBc_{token}()"
          title="Копіювати ШКІ"
          style="min-width:1.75rem; height:1.75rem; padding:0 0.2rem; font-size:0.9rem; border-radius:6px; border:1px solid #D1D5DB; background:#F9FAFB; cursor:pointer;">
    📋
  </button>
</div>
"""
    components.html(js_code, height=38)
