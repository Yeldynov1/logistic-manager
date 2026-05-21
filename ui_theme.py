"""Тема інтерфейсу Alius Checkbox — темний дашборд (макет) + денний режим."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_BG = {"dark": "#111827", "light": "#F3F4F6"}


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


def _inject_theme_document_attr() -> None:
    """data-app-theme + фон; у світлому режимі скидає inline-стилі з темного."""
    theme = "dark" if theme_is_dark() else "light"
    bg = _BG[theme]
    components.html(
        f"""
<script>
(function () {{
  const win = window.parent;
  const doc = win.document;
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

  doc.querySelectorAll('header[data-testid="stHeader"] a, header[data-testid="stHeader"] span').forEach(function (el) {{
    el.style.setProperty("color", theme === "dark" ? "#F9FAFB" : "#111827", "important");
  }});

  if (theme === "light") {{
    if (win._logisticDarkUiFixObs) {{
      win._logisticDarkUiFixObs.disconnect();
      win._logisticDarkUiFixObs = null;
    }}
    doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
      btn.style.removeProperty("background");
      btn.style.removeProperty("color");
      btn.style.removeProperty("border");
      btn.querySelectorAll("p, span").forEach(function (el) {{
        el.style.removeProperty("color");
      }});
    }});
    doc.querySelectorAll(".tab1-shipment-frame").forEach(function (el) {{
      el.style.removeProperty("background");
      el.style.removeProperty("border");
      el.style.removeProperty("outline");
      el.style.removeProperty("box-shadow");
    }});
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
  const RED_MARKS = [
    "Вибрати чек зі списку",
    "TurboSMS",
    "Надіслати TurboSMS",
    "Видати готові чеки",
  ];
  const RED_GRAD =
    "linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%)";
  const DELETE_MARK = "Видалити відправлені";
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
    const dark = doc.documentElement.getAttribute("data-app-theme") === "dark";
    try {
      doc.querySelectorAll("button").forEach(function (btn) {
        const text = (btn.innerText || btn.textContent || "").trim();
        if (matches(btn, RED_MARKS)) styleRed(btn);
        else if (text.indexOf("Готово") >= 0 || text.indexOf("✅") >= 0) styleDone(btn);
        else if (matches(btn, [DELETE_MARK])) styleDelete(btn, dark);
      });
    } catch (e) {}
  }
  apply();
  if (win._logisticBtnStyleObs) win._logisticBtnStyleObs.disconnect();
  let t;
  win._logisticBtnStyleObs = new MutationObserver(function () {
    clearTimeout(t);
    t = setTimeout(apply, 80);
  });
  win._logisticBtnStyleObs.observe(doc.body, {
    childList: true,
    subtree: true,
  });
})();
</script>
        """,
        height=0,
        width=0,
    )


def _inject_theme_dom_fixes() -> None:
    """Лише для темної теми — кнопки сайдбару та картки tab1 (як у макеті)."""
    if not theme_is_dark():
        return
    components.html(
        """
<script>
(function () {
  const win = window.parent;
  const doc = win.document;
  function fixSidebarButtons() {
    doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {
      const kind = (btn.getAttribute("kind") || "").toLowerCase();
      const text = (btn.innerText || btn.textContent || "").trim();
      if (kind === "primary" && text.indexOf("Завантажити") >= 0) return;
      if (text.indexOf("Видалити відправлені") >= 0) return;
      if (kind === "primary") {
        btn.querySelectorAll("p, span").forEach(function (el) {
          el.style.setProperty("color", "#FFFFFF", "important");
        });
        return;
      }
      btn.style.setProperty("background", "#374151", "important");
      btn.style.setProperty("color", "#F3F4F6", "important");
      btn.style.setProperty("border", "1px solid #4B5563", "important");
      btn.querySelectorAll("p, span").forEach(function (el) {
        el.style.setProperty("color", "#F3F4F6", "important");
      });
    });
  }
  function fixTab1Cards() {
    doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {
      const el = m.closest('[data-testid="stVerticalBlockBorderWrapper"]');
      if (!el) return;
      el.classList.add("tab1-shipment-frame");
      const svc = m.className.match(/tab1-svc-\\w+/);
      if (svc) el.classList.add(svc[0]);
      el.style.setProperty("background", "#2E3A48", "important");
      el.style.setProperty("border", "3px solid #B8C9DC", "important");
      el.style.setProperty("outline", "2px solid rgba(184, 201, 220, 0.55)", "important");
      el.style.setProperty("border-radius", "16px", "important");
      el.style.setProperty(
        "box-shadow",
        "0 0 0 1px #9AA8BC, 0 10px 32px rgba(0,0,0,0.5)",
        "important"
      );
    });
  }
  function apply() {
    if (doc.documentElement.getAttribute("data-app-theme") !== "dark") return;
    try {
      fixSidebarButtons();
      fixTab1Cards();
    } catch (e) {}
  }
  apply();
  if (win._logisticDarkUiFixObs) win._logisticDarkUiFixObs.disconnect();
  let t;
  win._logisticDarkUiFixObs = new MutationObserver(function () {
    clearTimeout(t);
    t = setTimeout(apply, 60);
  });
  win._logisticDarkUiFixObs.observe(doc.body, { childList: true, subtree: true });
})();
</script>
        """,
        height=0,
        width=0,
    )


def _theme_stylesheet() -> str:
    return """
<style>
html:not([data-app-theme]),
html[data-app-theme="light"] {
  --primary: #3B82F6;
  --primary-grad: linear-gradient(135deg, #60A5FA 0%, #3B82F6 55%, #2563EB 100%);
  --danger: #EF4444;
  --success: #10B981;
  --viber: #7C3AED;
  --text: #111827;
  --muted: #6B7280;
  --border: #E5E7EB;
  --surface: #FFFFFF;
  --bg: #F3F4F6;
  --bg-sidebar: #E5E7EB;
  --card-bg: #FFFFFF;
  --card-border: #D1D5DB;
  --radius: 12px;
  --shadow: 0 4px 18px rgba(17, 24, 39, 0.08);
}
html[data-app-theme="dark"] {
  --primary: #3B82F6;
  --primary-grad: linear-gradient(135deg, #60A5FA 0%, #3B82F6 50%, #6366F1 100%);
  --danger: #EF4444;
  --success: #10B981;
  --viber: #7C3AED;
  --text: #F9FAFB;
  --muted: #9CA3AF;
  --border: #374151;
  --surface: #1F2937;
  --input-bg: #111827;
  --bg: #111827;
  --bg-sidebar: #1F2937;
  --card-bg: #1F2937;
  --card-border: #374151;
  --shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}
html[data-app-theme="dark"] .stApp { color-scheme: dark; }
html[data-app-theme="light"] .stApp { color-scheme: light; }
.stApp, [data-testid="stAppViewContainer"], .main {
  background-color: var(--bg) !important;
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
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] span {
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
.stTextInput input, .stTextArea textarea, .stNumberInput input {
  background-color: var(--input-bg, var(--surface)) !important;
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
.stTabs [aria-selected="true"] {
  background: rgba(59, 130, 246, 0.2) !important;
  color: #93C5FD !important;
}
html[data-app-theme="light"] .stTabs [aria-selected="true"] {
  background: #DBEAFE !important;
  color: #1D4ED8 !important;
}
button[data-baseweb="tab"] {
  font-size: 1.05rem !important;
  font-weight: 600 !important;
}
div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
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
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #2E3A48 !important;
  border: 3px solid #B8C9DC !important;
  outline: 2px solid rgba(184, 201, 220, 0.5) !important;
  box-shadow: 0 0 0 1px #9AA8BC, 0 10px 32px rgba(0, 0, 0, 0.55) !important;
}
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextInput input,
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextArea textarea {
  background-color: var(--input-bg) !important;
  border: 1.5px solid var(--border) !important;
  color: var(--text) !important;
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
.stButton > button[kind="primary"] {
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
.app-brand-wrap .app-brand-title,
.app-brand-wrap h1.app-brand-title,
[data-testid="stMarkdownContainer"] .app-brand-wrap .app-brand-title,
[data-testid="stMarkdownContainer"] .app-brand-wrap h1 {
  margin: 0;
  color: #F9FAFB !important;
  font-size: 1.55rem;
  font-weight: 800;
  line-height: 1.3;
  opacity: 1 !important;
}
html[data-app-theme="light"] .app-brand-wrap .app-brand-title,
html[data-app-theme="light"] .app-brand-wrap h1.app-brand-title,
html[data-app-theme="light"] [data-testid="stMarkdownContainer"] .app-brand-wrap .app-brand-title,
html[data-app-theme="light"] [data-testid="stMarkdownContainer"] .app-brand-wrap h1 {
  color: #111827 !important;
}
.app-brand-wrap .app-brand-sub {
  margin: 0.25rem 0 0 0;
  color: var(--muted) !important;
  font-size: 0.9rem;
}
/* Назва програми у верхній панелі Streamlit */
header[data-testid="stHeader"] {
  z-index: 999;
}
header[data-testid="stHeader"] a,
header[data-testid="stHeader"] span,
header[data-testid="stHeader"] p,
header[data-testid="stHeader"] label,
header[data-testid="stHeader"] [data-testid="stHeaderActionElements"] button {
  color: #F9FAFB !important;
}
html[data-app-theme="light"] header[data-testid="stHeader"] a,
html[data-app-theme="light"] header[data-testid="stHeader"] span,
html[data-app-theme="light"] header[data-testid="stHeader"] p,
html[data-app-theme="light"] header[data-testid="stHeader"] label {
  color: #111827 !important;
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
.tab1-queue-live {
  color: var(--success);
  font-weight: 600;
}
.tab1-hint-banner {
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  border-radius: 12px;
  border: 1px solid rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.12);
  color: var(--text);
  font-size: 0.92rem;
}
html[data-app-theme="light"] .tab1-hint-banner {
  background: #EFF6FF;
  border-color: #BFDBFE;
  color: #1E3A8A;
}
html[data-app-theme="light"] header[data-testid="stHeader"],
html[data-app-theme="light"] [data-testid="stToolbar"],
html[data-app-theme="light"] [data-testid="stDecoration"] {
  background: var(--bg) !important;
}
html[data-app-theme="dark"] header[data-testid="stHeader"],
html[data-app-theme="dark"] [data-testid="stToolbar"],
html[data-app-theme="dark"] [data-testid="stDecoration"] {
  background: var(--bg) !important;
}
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
html[data-app-theme="dark"] [data-testid="stAlert"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
html[data-app-theme="light"] [data-testid="stAlert"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
.app-login-card div[data-testid="stForm"] {
  max-width: 420px;
  margin: 0 auto;
  border-radius: 14px;
}
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #FFFFFF !important;
  border: 1px solid #D1D5DB !important;
  outline: none !important;
  box-shadow: 0 4px 18px rgba(17, 24, 39, 0.08) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] {
  background: #E5E7EB !important;
}
</style>
"""


def inject_app_theme() -> None:
    _inject_theme_document_attr()
    st.markdown(_theme_stylesheet(), unsafe_allow_html=True)
    _inject_action_button_styles()
    if theme_is_dark():
        _inject_theme_dom_fixes()


def render_app_header() -> None:
    dark = theme_is_dark()
    title_c = "#F9FAFB" if dark else "#111827"
    sub_c = "#9CA3AF" if dark else "#6B7280"
    bg_c = "#1F2937" if dark else "#FFFFFF"
    border_c = "#374151" if dark else "#D1D5DB"
    st.markdown(
        f"""
<div class="app-brand-wrap" style="background:{bg_c};border:1px solid {border_c};border-left:5px solid #3B82F6;border-radius:14px;padding:0.9rem 1.2rem;margin:0 0 1rem 0;">
  <div style="color:{title_c};font-size:1.6rem;font-weight:800;margin:0;line-height:1.3;">
    ☑️ Alius Checkbox
  </div>
  <div style="color:{sub_c};font-size:0.9rem;margin:0.35rem 0 0 0;">
    Видача чеків · TurboSMS · Checkbox
  </div>
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
