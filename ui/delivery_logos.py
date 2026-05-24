"""Логотипи служб доставки для UI (SVG, без зовнішніх файлів)."""
from __future__ import annotations

from html import escape
from urllib.parse import quote

# Компактні SVG у стилі брендів (для темного фону карток).
_LOGO_SVG: dict[str, str] = {
    "УП": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 132 32" role="img" aria-label="Укрпошта">
  <rect width="132" height="32" rx="6" fill="#FFCC00"/>
  <text x="66" y="21.5" text-anchor="middle" fill="#0057B8"
    font-family="Arial,Helvetica,sans-serif" font-size="13" font-weight="700">Укрпошта</text>
</svg>""",
    "НП": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 148 32" role="img" aria-label="Нова пошта">
  <rect width="148" height="32" rx="6" fill="#DA291C"/>
  <text x="74" y="21.5" text-anchor="middle" fill="#fff"
    font-family="Arial,Helvetica,sans-serif" font-size="13" font-weight="700">Нова пошта</text>
</svg>""",
    "Meest": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 32" role="img" aria-label="Meest">
  <rect width="120" height="32" rx="6" fill="#0066B3"/>
  <text x="60" y="21.5" text-anchor="middle" fill="#fff"
    font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="800" letter-spacing="1">MEEST</text>
</svg>""",
    "Rozetka": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 132 32" role="img" aria-label="Rozetka">
  <rect width="132" height="32" rx="6" fill="#00A046"/>
  <text x="66" y="21.5" text-anchor="middle" fill="#fff"
    font-family="Arial,Helvetica,sans-serif" font-size="13" font-weight="700">ROZETKA</text>
</svg>""",
    "Інше": """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 32" role="img" aria-label="Доставка">
  <rect width="96" height="32" rx="6" fill="#374151"/>
  <path fill="#9CA3AF" d="M12 22h52v2H12zm4-12h28l6 8H16z"/>
  <text x="72" y="21" text-anchor="middle" fill="#E5E7EB"
    font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600">···</text>
</svg>""",
}

_KIND_CSS: dict[str, str] = {
    "УП": "rz-svc-up",
    "НП": "rz-svc-np",
    "Meest": "rz-svc-meest",
    "Rozetka": "rz-svc-rz",
    "Інше": "rz-svc-other",
}


def _svg_data_uri(kind: str) -> str:
    svg = _LOGO_SVG.get(kind) or _LOGO_SVG["Інше"]
    return "data:image/svg+xml," + quote(svg.strip())


def logo_img_html(kind: str, *, height_px: int = 28) -> str:
    """Тег img з SVG-логотипом служби."""
    k = kind if kind in _LOGO_SVG else "Інше"
    return (
        f'<img class="rz-delivery-logo" src="{_svg_data_uri(k)}" '
        f'height="{height_px}" alt="" loading="lazy" decoding="async"/>'
    )


def badge_html(kind: str, label: str, *, show_label: bool = False) -> str:
    """Бейдж: логотип + опційно короткий текст (якщо назва відрізняється від бренду)."""
    k = kind if kind in _LOGO_SVG else "Інше"
    css = _KIND_CSS.get(k, "rz-svc-other")
    title = escape(str(label or "").strip())
    parts = [
        f'<span class="rz-delivery-badge {css}" title="{title}">',
        logo_img_html(k),
    ]
    if show_label and label:
        parts.append(f'<span class="rz-svc-text">{title}</span>')
    parts.append("</span>")
    return "".join(parts)


def badge_html_for_order(order: dict, *, show_label: bool = False) -> str:
    from services import rozetka

    name, _ = rozetka.delivery_service_raw(order)
    label = rozetka.delivery_service_label(order)
    kind = rozetka.delivery_service_kind(name or label)
    # Для «Інше» показуємо повну назву з Rozetka поруч із піктограмою.
    need_text = show_label or (kind == "Інше" and bool(label))
    return badge_html(kind, label, show_label=need_text)


def inject_rozetka_delivery_css() -> None:
    """Один раз за сесію — стилі бейджів на вкладці Rozetka."""
    import streamlit as st

    if st.session_state.get("_rz_delivery_logo_css"):
        return
    st.session_state._rz_delivery_logo_css = True
    st.markdown(
        """
<style>
.rz-order-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem 0.85rem;
  margin-bottom: 0.2rem;
}
.rz-order-meta {
  font-size: 1.02rem;
  font-weight: 700;
  color: #F9FAFB;
  line-height: 1.35;
}
.rz-order-status {
  color: #9CA3AF;
  font-size: 0.92rem;
  line-height: 1.45;
  margin-bottom: 0.15rem;
}
.rz-delivery-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.2rem 0.55rem 0.2rem 0.35rem;
  border-radius: 8px;
  background: rgba(17, 24, 39, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.14);
  flex-shrink: 0;
}
.rz-delivery-logo {
  height: 28px;
  width: auto;
  max-width: 148px;
  display: block;
  border-radius: 4px;
}
.rz-svc-text {
  font-size: 0.82rem;
  font-weight: 600;
  color: #D1D5DB;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rz-svc-up { border-color: rgba(59, 130, 246, 0.55); }
.rz-svc-np { border-color: rgba(218, 41, 28, 0.55); }
.rz-svc-meest { border-color: rgba(0, 102, 179, 0.55); }
.rz-svc-rz { border-color: rgba(0, 160, 70, 0.55); }
.rz-svc-other { border-color: rgba(107, 114, 128, 0.45); }
</style>
""",
        unsafe_allow_html=True,
    )
