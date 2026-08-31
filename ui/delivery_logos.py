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

DELIVERY_KIND_OPTIONS: tuple[str, ...] = ("УП", "НП", "Meest", "Rozetka", "Інше")

DELIVERY_KIND_LABELS: dict[str, str] = {
    "УП": "Укрпошта",
    "НП": "Нова пошта",
    "Meest": "Meest",
    "Rozetka": "Rozetka",
    "Інше": "Інше",
}


def rozetka_order_kind(order: dict) -> str:
    from services import rozetka

    return rozetka.delivery_service_kind(rozetka.delivery_service_label(order))


def prom_order_kind(order: dict) -> str:
    from services import promua

    return promua.delivery_service_kind(order)


def epic_order_kind(order: dict) -> str:
    from services import epicentr

    return epicentr.delivery_service_kind(order)


def _order_kind_fn(source: str):
    if source == "prom":
        return prom_order_kind
    if source == "epicentr":
        return epic_order_kind
    return rozetka_order_kind


def delivery_kind_counts(
    items: list[tuple[int | str, dict]],
    *,
    source: str,
) -> dict[str, int]:
    """Кількість замовлень по службах (+ ключ all)."""
    kind_fn = _order_kind_fn(source)
    counts: dict[str, int] = {"all": len(items)}
    for _, order in items:
        k = kind_fn(order)
        counts[k] = counts.get(k, 0) + 1
    return counts


def _delivery_filter_btn_label(kind: str, label: str, counts: dict[str, int] | None) -> str:
    if not counts:
        return label
    n = counts.get("all" if kind == "all" else kind, 0)
    return f"{label} · {n}" if n else label


def ui_rerun(*, fragment: bool = False) -> None:
    import streamlit as st

    if fragment:
        st.rerun(scope="fragment")
    else:
        st.rerun()


def render_delivery_service_filter(
    *,
    key: str,
    counts: dict[str, int] | None = None,
    fragment: bool = False,
) -> list[str]:
    """Спочатку Укрпошта; «Показати всі» — окремо над службами."""
    import streamlit as st

    state_key = f"{key}_active"
    migration_key = f"{key}_up_default_v1"
    if not st.session_state.get(migration_key):
        # Один раз переводимо старий фільтр «Всі» на новий стартовий «Укрпошта».
        previous = str(st.session_state.get(state_key) or "all")
        if previous == "all" or previous not in DELIVERY_KIND_OPTIONS:
            st.session_state[state_key] = "УП"
        st.session_state[migration_key] = True
    if state_key not in st.session_state:
        st.session_state[state_key] = "УП"

    active = str(st.session_state.get(state_key) or "УП")

    if st.button(
        _delivery_filter_btn_label("all", "Показати всі", counts),
        key=f"{key}_btn_all",
        type="primary" if active == "all" else "secondary",
        use_container_width=True,
    ):
        st.session_state[state_key] = "all"
        ui_rerun(fragment=fragment)

    buttons = [(k, DELIVERY_KIND_LABELS[k]) for k in DELIVERY_KIND_OPTIONS]
    cols = st.columns(len(buttons))
    for col, (kind, label) in zip(cols, buttons):
        with col:
            if st.button(
                _delivery_filter_btn_label(kind, label, counts),
                key=f"{key}_btn_{kind}",
                type="primary" if active == kind else "secondary",
                use_container_width=True,
            ):
                st.session_state[state_key] = kind
                ui_rerun(fragment=fragment)

    if active == "all" or active not in DELIVERY_KIND_OPTIONS:
        return list(DELIVERY_KIND_OPTIONS)
    return [active]


def active_delivery_filter_label(*, key: str) -> str:
    """Підпис активного фільтра для підказок."""
    import streamlit as st

    active = str(st.session_state.get(f"{key}_active") or "all")
    if active == "all":
        return "Всі"
    return DELIVERY_KIND_LABELS.get(active, active)


def filter_orders_by_delivery_kinds(
    items: list[tuple[int | str, dict]],
    kinds: list[str],
    *,
    source: str,
) -> list[tuple[int | str, dict]]:
    if not kinds or set(kinds) >= set(DELIVERY_KIND_OPTIONS):
        return items
    kind_fn = _order_kind_fn(source)
    return [(oid, order) for oid, order in items if kind_fn(order) in kinds]


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


def badge_html_for_prom_order(order: dict, *, show_label: bool = False) -> str:
    from services import promua

    label = promua.delivery_service_label(order)
    kind = promua.delivery_service_kind(order)
    need_text = show_label or (kind == "Інше" and bool(label))
    return badge_html(kind, label, show_label=need_text)


def badge_html_for_epic_order(order: dict, *, show_label: bool = False) -> str:
    from services import epicentr

    label = epicentr.delivery_service_label(order)
    kind = epicentr.delivery_service_kind(order)
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
  color: var(--text, #F9FAFB);
  line-height: 1.35;
}
.rz-order-status {
  color: var(--muted, #9CA3AF);
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
  background: var(--surface, rgba(17, 24, 39, 0.55));
  border: 1px solid var(--border, rgba(255, 255, 255, 0.14));
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
  color: var(--muted, #D1D5DB);
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
.rz-ttn-code {
  color: var(--primary, #93C5FD);
  background: transparent;
  font-size: 0.9em;
}
.rz-order-card {
  display: none;
}
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-order-card) {
  background: #1F2937 !important;
  border: 2px solid #4B5563 !important;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important;
  border-radius: 14px !important;
  padding: 1rem 1.15rem !important;
  margin-top: 0.35rem !important;
  margin-bottom: 0.5rem !important;
}
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-order-card) {
  background: #FFFBF5 !important;
  border: 2px solid #C9B896 !important;
  outline: 1px solid rgba(201, 184, 150, 0.45) !important;
  box-shadow: 0 4px 14px rgba(61, 52, 40, 0.1), 0 0 0 1px #E8DFD0 !important;
  border-radius: 14px !important;
  padding: 1rem 1.15rem !important;
  margin-top: 0.35rem !important;
  margin-bottom: 0.5rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-card-np) {
  border-left: 5px solid #DA291C !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-card-up) {
  border-left: 5px solid #FFCC00 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-card-meest) {
  border-left: 5px solid #0066B3 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-card-rz) {
  border-left: 5px solid #00A046 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.rz-card-other) {
  border-left: 5px solid #9CA3AF !important;
}
hr.rz-order-divider {
  border: none;
  border-top: 2px solid var(--border);
  margin: 0.85rem 0 1.1rem 0;
}
html[data-app-theme="light"] hr.rz-order-divider {
  border-top-color: #C9B896;
  border-top-style: dashed;
}
html[data-app-theme="dark"] hr.rz-order-divider {
  border-top-color: #4B5563;
}
</style>
""",
        unsafe_allow_html=True,
    )
