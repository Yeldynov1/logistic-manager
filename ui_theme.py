"""Тема інтерфейсу Alius Checkbox (темний / світлий режим)."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_THEME_BG = {"dark": "#111827", "light": "#F3F4F6"}


def theme_is_dark() -> bool:
    return bool(st.session_state.get("theme_dark", True))


def tab1_card_service_class(row) -> str:
    svc = str(row.get("Служба", "")).strip().lower()
    if "meest" in svc:
        return "tab1-svc-meest"
    if "уп" in svc or "укр" in svc:
        return "tab1-svc-up"
    if "нп" in svc or "nova" in svc:
        return "tab1-svc-np"
    return "tab1-svc-other"


def _inject_theme_document_sync() -> None:
    """Синхронізує data-app-theme і фони в parent DOM (без «залипання» темного)."""
    theme = "dark" if theme_is_dark() else "light"
    bg = _THEME_BG[theme]
    components.html(
        f"""
<script>
(function () {{
  const doc = window.parent.document;
  const html = doc.documentElement;
  const theme = "{theme}";
  const bg = "{bg}";
  html.setAttribute("data-app-theme", theme);
  html.style.colorScheme = theme;
  try {{ localStorage.setItem("logistic_theme", theme); }} catch (e) {{}}

  const shell = [
    "header[data-testid=stHeader]",
    "[data-testid=stToolbar]",
    "[data-testid=stDecoration]",
    "[data-testid=stAppViewContainer]",
    "[data-testid=stMainBlockContainer]",
    "section.main",
    ".stApp",
  ];
  shell.forEach(function (sel) {{
    doc.querySelectorAll(sel).forEach(function (el) {{
      el.style.setProperty("background-color", bg, "important");
      el.style.setProperty("background", bg, "important");
    }});
  }});

  doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
    btn.style.removeProperty("background");
    btn.style.removeProperty("color");
    btn.style.removeProperty("border");
    btn.querySelectorAll("p, span").forEach(function (el) {{
      el.style.removeProperty("color");
    }});
  }});

  function paintDarkCards() {{
    doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {{
      const el = m.closest('[data-testid="stVerticalBlockBorderWrapper"]');
      if (!el) return;
      el.classList.add("tab1-shipment-frame");
      const svc = m.className.match(/tab1-svc-\\w+/);
      if (svc) el.classList.add(svc[0]);
      el.style.setProperty("background", "#2E3A48", "important");
      el.style.setProperty("border", "2px solid #B8C9DC", "important");
      el.style.setProperty("outline", "2px solid rgba(184, 201, 220, 0.5)", "important");
      el.style.setProperty("border-radius", "14px", "important");
      el.style.setProperty(
        "box-shadow",
        "0 0 0 1px #9AA8BC, 0 10px 32px rgba(0,0,0,0.5)",
        "important"
      );
    }});
  }}
  function clearCardPaint() {{
    doc.querySelectorAll(".tab1-shipment-frame").forEach(function (el) {{
      el.style.removeProperty("background");
      el.style.removeProperty("border");
      el.style.removeProperty("outline");
      el.style.removeProperty("box-shadow");
      el.style.removeProperty("border-radius");
    }});
  }}

  if (theme === "dark") {{
    doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
      const kind = (btn.getAttribute("kind") || "").toLowerCase();
      const text = (btn.innerText || btn.textContent || "").trim();
      if (kind === "primary") return;
      if (text.indexOf("Видалити відправлені") >= 0) return;
      btn.style.setProperty("background", "#374151", "important");
      btn.style.setProperty("color", "#F3F4F6", "important");
      btn.style.setProperty("border", "1px solid #4B5563", "important");
      btn.querySelectorAll("p, span").forEach(function (el) {{
        el.style.setProperty("color", "#F3F4F6", "important");
      }});
    }});
    paintDarkCards();
  }} else {{
    clearCardPaint();
  }}
}})();
</script>
        """,
        height=0,
        width=0,
    )


def _inject_action_button_styles() -> None:
    components.html(
        """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;
  const RED_MARKS = [
    "Вибрати чек зі списку",
    "TurboSMS",
    "Надіслати TurboSMS",
    "Видати готові чеки",
  ];
  const RED_GRAD =
    "linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%)";
  const DELETE_MARK = "Видалити відправлені";
  function isDark() {
    return doc.documentElement.getAttribute("data-app-theme") === "dark";
  }
  function matches(btn, marks) {
    const label = (btn.getAttribute("aria-label") || "").trim();
    const text = (btn.innerText || btn.textContent || "").trim();
    return marks.some(function (m) {
      return label.indexOf(m) >= 0 || text.indexOf(m) >= 0;
    });
  }
  function styleRed(btn) {
    btn.style.setProperty("background", RED_GRAD, "important");
    btn.style.setProperty("color", "#FFFFFF", "important");
    btn.style.setProperty("border", "none", "important");
    btn.style.setProperty("font-weight", "700", "important");
    btn.style.setProperty("box-shadow", "0 4px 14px rgba(239, 68, 68, 0.45)", "important");
    btn.querySelectorAll("p, span").forEach(function (el) {
      el.style.setProperty("color", "#FFFFFF", "important");
    });
  }
  function styleDone(btn) {
    btn.style.setProperty("background", "transparent", "important");
    btn.style.setProperty("color", "#10B981", "important");
    btn.style.setProperty("border", "2px solid #10B981", "important");
    btn.style.setProperty("font-weight", "700", "important");
    btn.querySelectorAll("p, span").forEach(function (el) {
      el.style.setProperty("color", "#10B981", "important");
    });
  }
  function styleDelete(btn, dark) {
    if (dark) {
      btn.style.setProperty("border-color", "#EF4444", "important");
      btn.style.setProperty("color", "#FCA5A5", "important");
      btn.querySelectorAll("p, span").forEach(function (el) {
        el.style.setProperty("color", "#FCA5A5", "important");
      });
    } else {
      btn.style.setProperty("border-color", "#EF4444", "important");
      btn.style.setProperty("color", "#B91C1C", "important");
      btn.querySelectorAll("p, span").forEach(function (el) {
        el.style.setProperty("color", "#B91C1C", "important");
      });
    }
  }
  function apply() {
    const dark = isDark();
    try {
      doc.querySelectorAll("button").forEach(function (btn) {
        const text = (btn.innerText || btn.textContent || "").trim();
        if (matches(btn, RED_MARKS)) {
          styleRed(btn);
        } else if (text.indexOf("Готово") >= 0 || text.indexOf("✅") >= 0) {
          styleDone(btn);
        } else if (matches(btn, [DELETE_MARK])) {
          styleDelete(btn, dark);
        }
      });
    } catch (e) {}
  }
  apply();
  if (win._logisticBtnStyleObs) win._logisticBtnStyleObs.disconnect();
  let t;
  win._logisticBtnStyleObs = new MutationObserver(function () {
    clearTimeout(t);
    t = setTimeout(apply, 50);
  });
  win._logisticBtnStyleObs.observe(doc.body, { childList: true, subtree: true });
})();
</script>
        """,
        height=0,
        width=0,
    )


def _theme_css() -> str:
    return """
<style>
html:not([data-app-theme]),
html[data-app-theme="dark"] {
  --primary: #3B82F6;
  --primary-grad: linear-gradient(135deg, #60A5FA 0%, #3B82F6 50%, #6366F1 100%);
  --danger: #EF4444;
  --success: #10B981;
  --text: #F9FAFB;
  --muted: #9CA3AF;
  --border: #374151;
  --surface: #1F2937;
  --input-bg: #111827;
  --bg: #111827;
  --bg-sidebar: #1F2937;
  --card-bg: #2E3A48;
  --card-border: #B8C9DC;
  --hint-bg: rgba(59, 130, 246, 0.18);
  --hint-border: rgba(96, 165, 250, 0.45);
  --shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  --card-shadow: 0 0 0 1px #9AA8BC, 0 10px 32px rgba(0, 0, 0, 0.5);
}
html[data-app-theme="light"] {
  --primary: #3B82F6;
  --primary-grad: linear-gradient(135deg, #60A5FA 0%, #3B82F6 55%, #2563EB 100%);
  --danger: #EF4444;
  --success: #059669;
  --text: #111827;
  --muted: #6B7280;
  --border: #D1D5DB;
  --surface: #FFFFFF;
  --input-bg: #FFFFFF;
  --bg: #F3F4F6;
  --bg-sidebar: #E5E7EB;
  --card-bg: #FFFFFF;
  --card-border: #D1D5DB;
  --hint-bg: #EFF6FF;
  --hint-border: #BFDBFE;
  --shadow: 0 4px 18px rgba(17, 24, 39, 0.08);
}
html:not([data-app-theme]) .stApp,
html[data-app-theme="dark"] .stApp {
  color-scheme: dark;
}
html[data-app-theme="light"] .stApp {
  color-scheme: light;
}
html:not([data-app-theme]) .stApp,
html:not([data-app-theme]) [data-testid="stAppViewContainer"],
html:not([data-app-theme]) .main,
html[data-app-theme="dark"] .stApp,
html[data-app-theme="dark"] [data-testid="stAppViewContainer"],
html[data-app-theme="dark"] .main,
html[data-app-theme="light"] .stApp,
html[data-app-theme="light"] [data-testid="stAppViewContainer"],
html[data-app-theme="light"] .main {
  background-color: var(--bg) !important;
}
html:not([data-app-theme]) header[data-testid="stHeader"],
html:not([data-app-theme]) [data-testid="stToolbar"],
html:not([data-app-theme]) [data-testid="stDecoration"],
html[data-app-theme="dark"] header[data-testid="stHeader"],
html[data-app-theme="dark"] [data-testid="stToolbar"],
html[data-app-theme="dark"] [data-testid="stDecoration"],
html[data-app-theme="light"] header[data-testid="stHeader"],
html[data-app-theme="light"] [data-testid="stToolbar"],
html[data-app-theme="light"] [data-testid="stDecoration"] {
  background: var(--bg) !important;
}
.block-container {
  padding-top: 1rem;
  max-width: min(96vw, 1680px);
}
h1, h2, h3, h4 { color: var(--text) !important; font-weight: 700 !important; }
p, label, .stMarkdown, span, li { color: var(--text); }
.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--muted) !important;
  opacity: 1 !important;
}
[data-testid="stSidebar"] {
  background: var(--bg-sidebar) !important;
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
  color: var(--text) !important;
}
[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
  background: var(--primary-grad) !important;
  border: none !important;
  color: #fff !important;
  font-weight: 600 !important;
  border-radius: 10px !important;
}
[data-testid="stSidebar"] div.stButton > button[kind="primary"] p {
  color: #fff !important;
}
[data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  width: 100% !important;
}
.stTextInput input,
.stTextArea textarea,
.stNumberInput input {
  background-color: var(--input-bg) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
.stTabs [data-baseweb="tab-list"] {
  gap: 6px;
  background: var(--surface);
  border-radius: 12px;
  padding: 6px;
  border: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
  border-radius: 10px;
  font-weight: 600;
  color: var(--muted) !important;
}
html[data-app-theme="light"] .stTabs [aria-selected="true"] {
  background: #DBEAFE !important;
  color: #1D4ED8 !important;
}
html:not([data-app-theme]) .stTabs [aria-selected="true"],
html[data-app-theme="dark"] .stTabs [aria-selected="true"] {
  background: rgba(59, 130, 246, 0.25) !important;
  color: #93C5FD !important;
}
button[data-baseweb="tab"] {
  font-size: 1.05rem !important;
  font-weight: 600 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius, 12px) !important;
  box-shadow: var(--shadow) !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: var(--card-bg) !important;
  border: 1px solid var(--card-border) !important;
  border-radius: 14px !important;
  padding: 1.1rem 1.25rem !important;
  margin-bottom: 0.85rem !important;
}
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #2E3A48 !important;
  border: 2px solid #B8C9DC !important;
  outline: 2px solid rgba(184, 201, 220, 0.45) !important;
  box-shadow: var(--card-shadow) !important;
}
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextInput input,
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextArea textarea,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextInput input,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextArea textarea {
  background-color: #111827 !important;
  border: 1.5px solid #4B5563 !important;
  color: #F9FAFB !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-svc-np) {
  border-left: 5px solid #10B981 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-svc-up) {
  border-left: 5px solid #3B82F6 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-svc-meest) {
  border-left: 5px solid #8B5CF6 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-svc-other) {
  border-left: 5px solid #6B7280 !important;
}
.stButton > button[kind="primary"]:not([aria-label*="Вибрати чек"]) {
  border-radius: 10px;
  font-weight: 600;
  background: var(--primary-grad) !important;
  color: #fff !important;
  border: none !important;
}
.stButton > button[kind="secondary"] {
  border-radius: 10px;
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
.stButton > button[kind="secondary"][aria-label="Вибрати чек зі списку"],
.stButton > button[kind="secondary"][aria-label*="Вибрати чек"] {
  background: linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%) !important;
  color: #fff !important;
  border: none !important;
  font-weight: 700 !important;
}
.stButton > button[kind="secondary"][aria-label*="Вибрати чек"] p {
  color: #fff !important;
}
.app-brand-wrap {
  margin: 0 0 1rem 0;
  padding: 0.9rem 1.2rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  border-left: 5px solid var(--primary);
  box-shadow: var(--shadow);
}
.app-brand-wrap .app-brand-title {
  margin: 0;
  color: var(--text) !important;
  font-size: 1.55rem;
  font-weight: 800;
}
.app-brand-wrap .app-brand-sub {
  margin: 0.25rem 0 0 0;
  color: var(--muted) !important;
  font-size: 0.9rem;
}
.tab1-queue-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem 1.5rem;
  align-items: center;
  padding: 0.75rem 1rem;
  margin-bottom: 0.75rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  font-size: 0.92rem;
}
.tab1-queue-bar strong { color: var(--text); }
.tab1-queue-live { color: var(--success); font-weight: 600; }
.tab1-hint-banner {
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  border-radius: 12px;
  border: 1px solid var(--hint-border);
  background: var(--hint-bg);
  color: var(--text);
  font-size: 0.92rem;
}
html[data-app-theme="light"] .tab1-hint-banner strong {
  color: #1E40AF;
}
html:not([data-app-theme]) [data-testid="stAlert"],
html[data-app-theme="dark"] [data-testid="stAlert"],
html[data-app-theme="light"] [data-testid="stAlert"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
html:not([data-app-theme]) [data-testid="stAlert"] p,
html[data-app-theme="dark"] [data-testid="stAlert"] p,
html[data-app-theme="light"] [data-testid="stAlert"] p {
  color: var(--text) !important;
}
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stMarkdownContainer"] p,
html:not([data-app-theme]) div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stCaptionContainer"] p,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stMarkdownContainer"] p,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stCaptionContainer"] p {
  color: #E5E7EB !important;
}
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stMarkdownContainer"] p,
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stCaptionContainer"] p {
  color: var(--text) !important;
}
.app-login-card div[data-testid="stForm"] {
  max-width: 420px;
  margin: 0 auto;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
}
</style>
"""


def _inject_dark_card_observer() -> None:
    """Підтримує контур карток tab1 після перерендеру Streamlit (лише темна тема)."""
    if not theme_is_dark():
        return
    components.html(
        """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;
  function paint() {
    if (doc.documentElement.getAttribute("data-app-theme") !== "dark") return;
    doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {
      const el = m.closest('[data-testid="stVerticalBlockBorderWrapper"]');
      if (!el) return;
      el.classList.add("tab1-shipment-frame");
      const svc = m.className.match(/tab1-svc-\\w+/);
      if (svc) el.classList.add(svc[0]);
      el.style.setProperty("background", "#2E3A48", "important");
      el.style.setProperty("border", "2px solid #B8C9DC", "important");
      el.style.setProperty("outline", "2px solid rgba(184, 201, 220, 0.5)", "important");
      el.style.setProperty(
        "box-shadow",
        "0 0 0 1px #9AA8BC, 0 10px 32px rgba(0,0,0,0.5)",
        "important"
      );
    });
  }
  paint();
  if (win._logisticDarkCardObs) win._logisticDarkCardObs.disconnect();
  let t;
  win._logisticDarkCardObs = new MutationObserver(function () {
    clearTimeout(t);
    t = setTimeout(paint, 50);
  });
  win._logisticDarkCardObs.observe(doc.body, { childList: true, subtree: true });
})();
</script>
        """,
        height=0,
        width=0,
    )


def inject_app_theme() -> None:
    if "theme_dark" not in st.session_state:
        st.session_state.theme_dark = True
    st.markdown(_theme_css(), unsafe_allow_html=True)
    _inject_theme_document_sync()
    _inject_action_button_styles()
    _inject_dark_card_observer()


def render_app_header() -> None:
    st.markdown(
        """
<div class="app-brand-wrap">
  <p class="app-brand-title">☑️ Alius Checkbox</p>
  <p class="app-brand-sub">Видача чеків · TurboSMS · Checkbox</p>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_tab1_queue_bar(n_pending: int, n_ready: int, last_sync: str = "") -> None:
    sync = last_sync or "—"
    st.markdown(
        f"""
<div class="tab1-queue-bar">
  <span>У черзі: <strong>{n_pending}</strong></span>
  <span>Готові до TurboSMS: <strong>{n_ready}</strong></span>
  <span class="tab1-queue-live">● оновлено {sync}</span>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_tab1_hint() -> None:
    st.markdown(
        """
<div class="tab1-hint-banner">
  ℹ️ Прикріпіть чек Checkbox або вставте посилання → перевірте текст SMS →
  <strong>Надіслати TurboSMS</strong> або <strong>Готово</strong>, якщо клієнт уже отримав повідомлення.
</div>
        """,
        unsafe_allow_html=True,
    )
