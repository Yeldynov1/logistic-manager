"""Тема інтерфейсу Alius Checkbox — темний дашборд."""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_BG = "#111827"


def tab1_card_service_class(row) -> str:
    svc = str(row.get("Служба", "")).strip().lower()
    if "meest" in svc:
        return "tab1-svc-meest"
    if "уп" in svc or "укр" in svc:
        return "tab1-svc-up"
    if "нп" in svc or "nova" in svc:
        return "tab1-svc-np"
    return "tab1-svc-other"


def _inject_theme_shell() -> None:
    components.html(
        f"""
<script>
(function () {{
  const win = window.parent;
  const doc = win.document;
  const html = doc.documentElement;
  const bg = "{_BG}";
  html.setAttribute("data-app-theme", "dark");
  html.style.colorScheme = "dark";
  try {{ localStorage.removeItem("logistic_theme"); }} catch (e) {{}}

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
    el.style.setProperty("color", "#F9FAFB", "important");
  }});

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

  doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {{
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
  }});
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
  function styleDelete(btn) {
    btn.style.setProperty("border-color", "#EF4444", "important");
    btn.style.setProperty("color", "#FCA5A5", "important");
    btn.querySelectorAll("p, span").forEach(function (el) {
      el.style.setProperty("color", "#FCA5A5", "important");
    });
  }
  function apply() {
    try {
      doc.querySelectorAll("button").forEach(function (btn) {
        const text = (btn.innerText || btn.textContent || "").trim();
        if (matches(btn, RED_MARKS)) styleRed(btn);
        else if (text.indexOf("Готово") >= 0 || text.indexOf("✅") >= 0) styleDone(btn);
        else if (matches(btn, [DELETE_MARK])) styleDelete(btn);
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
  win._logisticBtnStyleObs.observe(doc.body, { childList: true, subtree: true });
})();
</script>
        """,
        height=0,
        width=0,
    )


def _inject_theme_dom_fixes() -> None:
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
:root, html[data-app-theme="dark"] {
  --primary: #3B82F6;
  --primary-grad: linear-gradient(135deg, #60A5FA 0%, #3B82F6 50%, #6366F1 100%);
  --text: #F9FAFB;
  --muted: #9CA3AF;
  --border: #374151;
  --surface: #1F2937;
  --input-bg: #111827;
  --bg: #111827;
  --bg-sidebar: #1F2937;
  --card-bg: #2E3A48;
  --card-border: #B8C9DC;
  --radius: 12px;
  --shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
}
html { color-scheme: dark; }
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
  width: 100% !important;
}
[data-testid="stSidebar"] div.stButton > button[kind="primary"] p {
  color: #fff !important;
}
[data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) {
  background: #374151 !important;
  color: #F3F4F6 !important;
  border: 1px solid #4B5563 !important;
  border-radius: 10px !important;
  width: 100% !important;
}
.stTextInput input, .stTextArea textarea, .stNumberInput input {
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
.stTabs [aria-selected="true"] {
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
  border-radius: var(--radius) !important;
  box-shadow: var(--shadow) !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #2E3A48 !important;
  border: 3px solid #B8C9DC !important;
  outline: 2px solid rgba(184, 201, 220, 0.5) !important;
  box-shadow: 0 0 0 1px #9AA8BC, 0 10px 32px rgba(0, 0, 0, 0.55) !important;
  border-radius: 14px !important;
  padding: 1.1rem 1.25rem !important;
  margin-bottom: 0.85rem !important;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextInput input,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card) .stTextArea textarea {
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
.stButton > button[kind="secondary"][aria-label*="Вибрати чек"] {
  background: linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%) !important;
  color: #fff !important;
  border: none !important;
  font-weight: 700 !important;
}
.stButton > button[kind="secondary"][aria-label*="Вибрати чек"] p {
  color: #fff !important;
}
header[data-testid="stHeader"] a,
header[data-testid="stHeader"] span,
header[data-testid="stHeader"] p,
header[data-testid="stHeader"] label {
  color: #F9FAFB !important;
}
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] {
  background: var(--bg) !important;
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
.tab1-queue-live { color: #10B981; font-weight: 600; }
.tab1-hint-banner {
  padding: 0.85rem 1rem;
  margin-bottom: 1rem;
  border-radius: 12px;
  border: 1px solid rgba(59, 130, 246, 0.35);
  background: rgba(59, 130, 246, 0.12);
  color: var(--text);
  font-size: 0.92rem;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stMarkdownContainer"] p,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stCaptionContainer"] p {
  color: #E5E7EB !important;
}
[data-testid="stAlert"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
.app-login-card div[data-testid="stForm"] {
  max-width: 420px;
  margin: 0 auto;
  border-radius: 14px;
}
</style>
"""


def inject_app_theme() -> None:
    _inject_theme_shell()
    st.markdown(_theme_stylesheet(), unsafe_allow_html=True)
    _inject_action_button_styles()
    _inject_theme_dom_fixes()


def render_app_header() -> None:
    st.markdown(
        """
<div style="background:#1F2937;border:1px solid #374151;border-left:5px solid #3B82F6;border-radius:14px;padding:0.9rem 1.2rem;margin:0 0 1rem 0;">
  <div style="color:#F9FAFB;font-size:1.6rem;font-weight:800;margin:0;line-height:1.3;">
    ☑️ Alius Checkbox
  </div>
  <div style="color:#9CA3AF;font-size:0.9rem;margin:0.35rem 0 0 0;">
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
