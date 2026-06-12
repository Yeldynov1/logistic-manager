"""Тема інтерфейсу Alius Checkbox — темна та світла (беж)."""
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

THEME_DARK = "dark"
THEME_LIGHT = "light"
_THEME_IDS = (THEME_DARK, THEME_LIGHT)

# JS / inline-стилі (окремо від CSS-змінних)
_THEME_UI: dict[str, dict[str, str]] = {
    THEME_DARK: {
        "bg_shell": "#111827",
        "header_fg": "#F9FAFB",
        "header_sub": "#9CA3AF",
        "header_box_bg": "#1F2937",
        "header_box_border": "#374151",
        "header_accent": "#3B82F6",
        "sidebar_btn_bg": "#374151",
        "sidebar_btn_fg": "#F3F4F6",
        "sidebar_btn_border": "#4B5563",
        "sidebar_text": "#E5E7EB",
        "sidebar_text_muted": "#9CA3AF",
        "sidebar_text_strong": "#F9FAFB",
        "sidebar_surface": "#1F2937",
        "sidebar_surface_raised": "#374151",
        "sidebar_border": "#4B5563",
        "tab1_card_bg": "#2E3A48",
        "tab1_card_border": "#B8C9DC",
        "tab1_card_outline": "2px solid rgba(184, 201, 220, 0.55)",
        "tab1_card_shadow": "0 0 0 1px #9AA8BC, 0 10px 32px rgba(0,0,0,0.5)",
        "delete_btn_fg": "#FCA5A5",
        "color_scheme": "dark",
    },
    THEME_LIGHT: {
        "bg_shell": "#F8FAFD",
        "header_fg": "#1F2937",
        "header_sub": "#6B7280",
        "header_box_bg": "#FFFFFF",
        "header_box_border": "#E2E8F0",
        "header_accent": "#4F46E5",
        "sidebar_btn_bg": "#2C3C63",
        "sidebar_btn_fg": "#E8EEFF",
        "sidebar_btn_border": "#435782",
        "sidebar_text": "#E8EEFF",
        "sidebar_text_muted": "#B9C8E9",
        "sidebar_text_strong": "#FFFFFF",
        "sidebar_surface": "#1A2640",
        "sidebar_surface_raised": "#223250",
        "sidebar_border": "#435782",
        "tab1_card_bg": "#FFFFFF",
        "tab1_card_border": "#D9E2EF",
        "tab1_card_outline": "1px solid rgba(148, 163, 184, 0.35)",
        "tab1_card_shadow": "0 4px 16px rgba(15, 23, 42, 0.06), 0 0 0 1px #E2E8F0",
        "delete_btn_fg": "#B91C1C",
        "color_scheme": "light",
    },
}


def get_app_theme() -> str:
    """Тема застосунку — завжди світла (беж). Перемикача більше немає."""
    st.session_state["app_theme"] = THEME_LIGHT
    return THEME_LIGHT


def render_theme_selector(*, sidebar: bool = True) -> None:
    """Перемикач теми прибрано — застосунок завжди світлий (беж)."""
    st.session_state["app_theme"] = THEME_LIGHT


def tab1_card_service_class(row) -> str:
    svc = str(row.get("Служба", "")).strip().lower()
    if "meest" in svc:
        return "tab1-svc-meest"
    if "уп" in svc or "укр" in svc:
        return "tab1-svc-up"
    if "нп" in svc or "nova" in svc:
        return "tab1-svc-np"
    return "tab1-svc-other"


def _ui_tokens(theme_id: str) -> dict[str, str]:
    return _THEME_UI.get(theme_id, _THEME_UI[THEME_DARK])


def _inject_theme_shell(theme_id: str) -> None:
    tok = _ui_tokens(theme_id)
    bg = tok["bg_shell"]
    components.html(
        f"""
<script>
(function () {{
  const win = window.parent;
  const doc = win.document;
  const html = doc.documentElement;
  const bg = {json.dumps(bg)};
  const theme = {json.dumps(theme_id)};
  html.setAttribute("data-app-theme", theme);
  html.style.colorScheme = {json.dumps(tok["color_scheme"])};

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

  const headerFg = {json.dumps(tok["header_fg"])};
  doc.querySelectorAll('header[data-testid="stHeader"] a, header[data-testid="stHeader"] span').forEach(function (el) {{
    el.style.setProperty("color", headerFg, "important");
  }});

  const sbBg = {json.dumps(tok["sidebar_btn_bg"])};
  const sbFg = {json.dumps(tok["sidebar_btn_fg"])};
  const sbBd = {json.dumps(tok["sidebar_btn_border"])};
  function isSidebarWidgetBtn(btn) {{
    if (btn.closest('[data-baseweb="checkbox"]')) return true;
    if (btn.closest('[data-testid="stCheckbox"]')) return true;
    if (btn.closest('[data-testid="stToggle"]')) return true;
  }}
  doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
    const kind = (btn.getAttribute("kind") || "").toLowerCase();
    const text = (btn.innerText || btn.textContent || "").trim();
    if (isSidebarWidgetBtn(btn)) return;
    if (text === "ВИКЛ" || text === "ВКЛ") return;
    if (kind === "primary") return;
    if (text.indexOf("Видалити відправлені") >= 0) return;
    btn.style.setProperty("background", sbBg, "important");
    btn.style.setProperty("color", sbFg, "important");
    btn.style.setProperty("border", "1px solid " + sbBd, "important");
    btn.querySelectorAll("p, span").forEach(function (el) {{
      el.style.setProperty("color", sbFg, "important");
    }});
  }});

  const cBg = {json.dumps(tok["tab1_card_bg"])};
  const cBd = {json.dumps(tok["tab1_card_border"])};
  const cOl = {json.dumps(tok["tab1_card_outline"])};
  const cSh = {json.dumps(tok["tab1_card_shadow"])};
  doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {{
    const el = m.closest('[data-testid="stVerticalBlockBorderWrapper"]');
    if (!el) return;
    el.classList.add("tab1-shipment-frame");
    const svc = m.className.match(/tab1-svc-\\w+/);
    if (svc) el.classList.add(svc[0]);
    el.style.setProperty("background", cBg, "important");
    el.style.setProperty("border", "3px solid " + cBd, "important");
    el.style.setProperty("outline", cOl, "important");
    el.style.setProperty("border-radius", "16px", "important");
    el.style.setProperty("box-shadow", cSh, "important");
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
    btn.style.setProperty("background", RED_GRAD, "important");
    btn.style.setProperty("color", "#FFFFFF", "important");
    btn.style.setProperty("border", "none", "important");
    btn.style.setProperty("font-weight", "700", "important");
    btn.style.setProperty("box-shadow", "0 4px 14px rgba(239, 68, 68, 0.45)", "important");
    btn.querySelectorAll("p, span").forEach(function (el) {
      el.style.setProperty("color", "#FFFFFF", "important");
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


def _inject_theme_dom_fixes(theme_id: str) -> None:
    tok = _ui_tokens(theme_id)
    components.html(
        f"""
<script>
(function () {{
  const win = window.parent;
  const doc = win.document;
  const sbBg = {json.dumps(tok["sidebar_btn_bg"])};
  const sbFg = {json.dumps(tok["sidebar_btn_fg"])};
  const sbBd = {json.dumps(tok["sidebar_btn_border"])};
  const cBg = {json.dumps(tok["tab1_card_bg"])};
  const cBd = {json.dumps(tok["tab1_card_border"])};
  const cOl = {json.dumps(tok["tab1_card_outline"])};
  const cSh = {json.dumps(tok["tab1_card_shadow"])};
  function isSidebarWidgetBtn(btn) {{
    if (btn.closest('[data-baseweb="checkbox"]')) return true;
    if (btn.closest('[data-testid="stCheckbox"]')) return true;
    if (btn.closest('[data-testid="stToggle"]')) return true;
  }}
  function fixAutoRefreshButtons() {{
    doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
      const kind = (btn.getAttribute("kind") || "").toLowerCase();
      const text = (btn.innerText || btn.textContent || "").trim();
      if (kind !== "primary") return;
      if (text === "ВИКЛ") {{
        btn.style.setProperty("background", "linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%)", "important");
        btn.style.setProperty("color", "#FFFFFF", "important");
        btn.style.setProperty("border", "none", "important");
        btn.style.setProperty("box-shadow", "0 4px 14px rgba(239, 68, 68, 0.45)", "important");
      }} else if (text === "ВКЛ") {{
        btn.style.setProperty("background", "linear-gradient(135deg, #34D399 0%, #10B981 55%, #059669 100%)", "important");
        btn.style.setProperty("color", "#FFFFFF", "important");
        btn.style.setProperty("border", "none", "important");
        btn.style.setProperty("box-shadow", "0 4px 14px rgba(16, 185, 129, 0.45)", "important");
      }} else {{
        return;
      }}
      btn.querySelectorAll("p, span").forEach(function (el) {{
        el.style.setProperty("color", "#FFFFFF", "important");
      }});
    }});
  }}
  function fixSidebarButtons() {{
    doc.querySelectorAll('[data-testid="stSidebar"] button').forEach(function (btn) {{
      const kind = (btn.getAttribute("kind") || "").toLowerCase();
      const text = (btn.innerText || btn.textContent || "").trim();
      if (isSidebarWidgetBtn(btn)) return;
      if (text === "ВИКЛ" || text === "ВКЛ") return;
      if (kind === "primary" && text.indexOf("Завантажити") >= 0) return;
      if (text.indexOf("Видалити відправлені") >= 0) return;
      if (kind === "primary") {{
        btn.querySelectorAll("p, span").forEach(function (el) {{
          el.style.setProperty("color", "#FFFFFF", "important");
        }});
        return;
      }}
      btn.style.setProperty("background", sbBg, "important");
      btn.style.setProperty("color", sbFg, "important");
      btn.style.setProperty("border", "1px solid " + sbBd, "important");
      btn.querySelectorAll("p, span").forEach(function (el) {{
        el.style.setProperty("color", sbFg, "important");
      }});
    }});
  }}
  const sbText = {json.dumps(tok.get("sidebar_text", "#E8EEFF"))};
  const sbMuted = {json.dumps(tok.get("sidebar_text_muted", "#B9C8E9"))};
  const sbStrong = {json.dumps(tok.get("sidebar_text_strong", "#FFFFFF"))};
  const sbSurface = {json.dumps(tok.get("sidebar_surface", "#1A2640"))};
  function fixSidebarAdminPanels() {{
    const sb = doc.querySelector('[data-testid="stSidebar"]');
    if (!sb) return;
    sb.querySelectorAll("h1, h2, h3").forEach(function (el) {{
      el.style.setProperty("color", sbStrong, "important");
    }});
    sb.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"]').forEach(function (wrap) {{
      const hasExpander = wrap.querySelector('[data-testid="stExpander"]');
      const hasForm = wrap.querySelector('[data-testid="stForm"]');
      if (!hasExpander && !hasForm) {{
        wrap.style.setProperty("background", "transparent", "important");
        wrap.style.setProperty("border", "none", "important");
        wrap.style.setProperty("box-shadow", "none", "important");
        wrap.style.setProperty("padding", "0", "important");
      }}
    }});
    const sbRaised = {json.dumps(tok.get("sidebar_surface_raised", "#2A3D63"))};
    sb.querySelectorAll('[data-testid="stExpander"] summary').forEach(function (sum) {{
      sum.style.setProperty("background", sbRaised, "important");
      sum.style.setProperty("color", sbStrong, "important");
      sum.style.setProperty("border", "1px solid #5A72A8", "important");
      sum.querySelectorAll("p, span, div, label, .stMarkdown, [data-testid=\\"stMarkdownContainer\\"]").forEach(function (el) {{
        el.style.setProperty("color", sbText, "important");
        el.style.setProperty("-webkit-text-fill-color", sbText, "important");
        el.style.setProperty("opacity", "1", "important");
      }});
    }});
    sb.querySelectorAll('[data-testid="stExpanderDetails"]').forEach(function (panel) {{
      panel.style.setProperty("background", sbSurface, "important");
      panel.querySelectorAll("p, label, span, li, .stMarkdown").forEach(function (el) {{
        if (el.closest(".stSuccess, .stError, .stWarning, .stInfo")) return;
        el.style.setProperty("color", sbText, "important");
      }});
      panel.querySelectorAll("strong").forEach(function (el) {{
        el.style.setProperty("color", sbStrong, "important");
      }});
      panel.querySelectorAll('[data-testid="stCaptionContainer"] p, .stCaption').forEach(function (el) {{
        el.style.setProperty("color", sbMuted, "important");
      }});
    }});
    sb.querySelectorAll('[data-baseweb="checkbox"] + label, [data-baseweb="checkbox"] ~ div span').forEach(function (el) {{
      el.style.setProperty("color", sbText, "important");
    }});
  }}
  function fixTab1Cards() {{
    doc.querySelectorAll(".tab1-shipment-card").forEach(function (m) {{
      const el = m.closest('[data-testid="stVerticalBlockBorderWrapper"]');
      if (!el) return;
      el.classList.add("tab1-shipment-frame");
      const svc = m.className.match(/tab1-svc-\\w+/);
      if (svc) el.classList.add(svc[0]);
      el.style.setProperty("background", cBg, "important");
      el.style.setProperty("border", "3px solid " + cBd, "important");
      el.style.setProperty("outline", cOl, "important");
      el.style.setProperty("border-radius", "16px", "important");
      el.style.setProperty("box-shadow", cSh, "important");
    }});
  }}
  function apply() {{
    try {{
      fixAutoRefreshButtons();
      fixSidebarButtons();
      fixSidebarAdminPanels();
      fixTab1Cards();
    }} catch (e) {{}}
  }}
  apply();
  if (win._logisticUiFixObs) win._logisticUiFixObs.disconnect();
  let t;
  win._logisticUiFixObs = new MutationObserver(function () {{
    clearTimeout(t);
    t = setTimeout(apply, 60);
  }});
  win._logisticUiFixObs.observe(doc.body, {{ childList: true, subtree: true }});
}})();
</script>
        """,
        height=0,
        width=0,
    )


def _theme_stylesheet() -> str:
    return """
<style>
html[data-app-theme="dark"] {
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
  --tab-active-bg: rgba(59, 130, 246, 0.25);
  --tab-active-fg: #93C5FD;
  --hint-bg: rgba(59, 130, 246, 0.12);
  --hint-border: rgba(59, 130, 246, 0.35);
  --tab1-card-text: #E5E7EB;
  --journal-cell: #E5E7EB;
  --journal-cell-muted: #D1D5DB;
  --journal-hdr-bg: #374151;
  --journal-hdr-fg: #F3F4F6;
  --journal-hdr-accent: #4ADE80;
  --journal-bc: #F9FAFB;
  --journal-row-active-bg: rgba(55, 65, 81, 0.55);
  --journal-row-active-border: #6B7280;
  --journal-link: #93C5FD;
  --journal-link-hover: #BFDBFE;
  --journal-postpay: #4ADE80;
  --gdg-bg-cell: #111827;
  --gdg-bg-header: #1F2937;
  --gdg-bg-header-hovered: #374151;
  --gdg-bg-header-has-focus: #4B5563;
  --gdg-text-dark: #F9FAFB;
  --gdg-text-medium: #D1D5DB;
  --gdg-text-light: #9CA3AF;
  --gdg-text-header: #F3F4F6;
  --gdg-border-color: #374151;
  --gdg-accent-color: #3B82F6;
  color-scheme: dark;
}
html[data-app-theme="light"] {
  --primary: #4F46E5;
  --primary-grad: linear-gradient(135deg, #6366F1 0%, #4F46E5 55%, #4338CA 100%);
  --text: #1F2937;
  --muted: #6B7280;
  --border: #CBD5E1;
  --surface: #FFFFFF;
  --input-bg: #FFFFFF;
  --bg: #F8FAFD;
  --bg-sidebar: #1E2A44;
  --card-bg: #FFFFFF;
  --card-border: #CBD5E1;
  --radius: 12px;
  --shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
  --tab-active-bg: rgba(79, 70, 229, 0.12);
  --tab-active-fg: #312E81;
  --hint-bg: rgba(79, 70, 229, 0.08);
  --hint-border: rgba(79, 70, 229, 0.28);
  --tab1-card-text: #334155;
  --journal-cell: #374151;
  --journal-cell-muted: #6B7280;
  --journal-hdr-bg: #EEF2F7;
  --journal-hdr-fg: #374151;
  --journal-hdr-accent: #4F46E5;
  --journal-bc: #1F2937;
  --journal-row-active-bg: rgba(79, 70, 229, 0.08);
  --journal-row-active-border: #A5B4FC;
  --journal-link: #2563EB;
  --journal-link-hover: #1D4ED8;
  --journal-postpay: #16A34A;
  --gdg-bg-cell: #FFFFFF;
  --gdg-bg-header: #EEF3FA;
  --gdg-bg-header-hovered: #E2E8F0;
  --gdg-bg-header-has-focus: #D6DFED;
  --gdg-text-dark: #1F2937;
  --gdg-text-medium: #475569;
  --gdg-text-light: #6B7280;
  --gdg-text-header: #334155;
  --gdg-border-color: #DCE3EE;
  --gdg-accent-color: #4F46E5;
  color-scheme: light;
}
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
html[data-app-theme="dark"] [data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) {
  background: #374151 !important;
  color: #F3F4F6 !important;
  border: 1px solid #4B5563 !important;
  border-radius: 10px !important;
  width: 100% !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) {
  background: #2C3C63 !important;
  color: #E8EEFF !important;
  border: 1px solid #435782 !important;
  border-radius: 10px !important;
  width: 100% !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] label,
html[data-app-theme="light"] [data-testid="stSidebar"] .stMarkdown,
html[data-app-theme="light"] [data-testid="stSidebar"] span,
html[data-app-theme="light"] [data-testid="stSidebar"] .stCaption {
  color: #DCE6FF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] input,
html[data-app-theme="light"] [data-testid="stSidebar"] textarea,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-baseweb="select"] > div,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-baseweb="input"] > div {
  background: #243455 !important;
  color: #EEF4FF !important;
  border: 1px solid #4C6190 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] input::placeholder,
html[data-app-theme="light"] [data-testid="stSidebar"] textarea::placeholder {
  color: #AFC0E6 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-baseweb="checkbox"] > div {
  border-color: #6C83B4 !important;
  background: #243455 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-baseweb="radio"] > div {
  border-color: #6C83B4 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary {
  background: #2A3D63 !important;
  border: 1px solid #5A72A8 !important;
  color: #F4F7FF !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary p,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary span,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary div,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary label,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary .stMarkdown,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"],
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {
  color: #F4F7FF !important;
  -webkit-text-fill-color: #F4F7FF !important;
  opacity: 1 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
  background: #1A2640 !important;
  border: 1px solid #435782 !important;
  border-top: none !important;
  border-radius: 0 0 10px 10px !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] label,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] span,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] li,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] .stMarkdown,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-testid="stCaptionContainer"] {
  color: #E8EEFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] strong {
  color: #FFFFFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-baseweb="checkbox"] span,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-baseweb="checkbox"] label {
  color: #E8EEFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-testid="stAlert"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-testid="stAlert"] span {
  color: inherit !important;
}
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpander"] summary {
  background: #374151 !important;
  border: 1px solid #4B5563 !important;
  color: #F3F4F6 !important;
  border-radius: 10px !important;
}
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpander"] summary p,
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpander"] summary span {
  color: #F3F4F6 !important;
}
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
  background: #1F2937 !important;
  border: 1px solid #4B5563 !important;
  border-top: none !important;
  border-radius: 0 0 10px 10px !important;
}
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] p,
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] label,
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] span,
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] .stMarkdown,
html[data-app-theme="dark"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] [data-testid="stCaptionContainer"] {
  color: #E5E7EB !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] hr {
  border-color: rgba(184, 201, 230, 0.25) !important;
}
/* CRM look: dark sidebar + clean light workspace */
html[data-app-theme="light"] [data-testid="stSidebar"] {
  background: linear-gradient(180deg, #16233B 0%, #1B2A46 55%, #172236 100%) !important;
  border-right: 1px solid #2E3D5F !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {
  background: rgba(99, 102, 241, 0.22) !important;
  border: 1px solid #4E5FB4 !important;
  border-radius: 999px !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stButton > button {
  border-radius: 12px !important;
  font-weight: 600 !important;
  min-height: 2.25rem !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #6D5DF6 0%, #5B46F2 55%, #4632D9 100%) !important;
  box-shadow: 0 6px 16px rgba(91, 70, 242, 0.35) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
  margin-bottom: 0 !important;
}
html[data-app-theme="light"] .stApp,
html[data-app-theme="light"] [data-testid="stAppViewContainer"],
html[data-app-theme="light"] .main {
  background: #F7F9FD !important;
}
html[data-app-theme="light"] .block-container {
  padding-top: 0.8rem !important;
}
html[data-app-theme="light"] section.main [data-testid="stVerticalBlockBorderWrapper"] {
  background: #FFFFFF !important;
  border: 1px solid #E2E8F0 !important;
  border-radius: 14px !important;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06) !important;
}
html[data-app-theme="light"] [data-testid="stMetric"] {
  background: #F8FAFD !important;
  border: 1px solid #E4EAF3 !important;
  border-radius: 12px !important;
  padding: 0.55rem 0.7rem !important;
}
html[data-app-theme="light"] .stTabs [data-baseweb="tab-list"] {
  background: #FFFFFF !important;
  border: 1px solid #E3E8F2 !important;
  border-radius: 12px !important;
  padding: 0.28rem 0.35rem !important;
  gap: 0.32rem !important;
}
html[data-app-theme="light"] .stTabs [data-baseweb="tab"] {
  background: #F3F6FB !important;
  border: 1px solid #E3E8F2 !important;
  color: #475569 !important;
  border-radius: 10px !important;
  font-size: 0.9rem !important;
  padding: 0.25rem 0.75rem !important;
}
html[data-app-theme="light"] .stTabs [aria-selected="true"] {
  background: linear-gradient(135deg, #EEF2FF 0%, #E6ECFF 100%) !important;
  border-color: #C8D3FE !important;
  color: #3730A3 !important;
}
html[data-app-theme="light"] .stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #6D5DF6 0%, #5B46F2 55%, #4632D9 100%) !important;
  box-shadow: 0 6px 14px rgba(91, 70, 242, 0.25) !important;
}
html[data-app-theme="light"] .stButton > button[kind="secondary"] {
  background: #FFFFFF !important;
  border: 1px solid #D8E0EC !important;
  color: #334155 !important;
}
/* ===== Dashboard layout overrides (full look, not only colors) ===== */
html[data-app-theme="light"] .block-container {
  max-width: min(97vw, 1780px) !important;
  padding: 0.7rem 1rem 1.1rem 1rem !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] {
  width: 320px !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stExpander"]) {
  margin-bottom: 0.45rem !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stTextInput input,
html[data-app-theme="light"] [data-testid="stSidebar"] .stNumberInput input,
html[data-app-theme="light"] [data-testid="stSidebar"] .stTextArea textarea {
  border-radius: 10px !important;
  min-height: 2.25rem !important;
  font-size: 0.9rem !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stButton > button {
  width: 100% !important;
  min-height: 2.45rem !important;
  border-radius: 12px !important;
  font-size: 0.92rem !important;
  letter-spacing: 0.01em !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stCaption,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
  font-size: 0.78rem !important;
  color: #B9C8E9 !important;
}
html[data-app-theme="light"] h1,
html[data-app-theme="light"] h2,
html[data-app-theme="light"] h3 {
  letter-spacing: -0.01em !important;
}
html[data-app-theme="light"] section.main div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 16px !important;
  border: 1px solid #CED9E8 !important;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.09) !important;
}
html[data-app-theme="light"] [data-testid="stMetric"] {
  border-radius: 14px !important;
  background: linear-gradient(180deg, #FFFFFF 0%, #F2F7FF 100%) !important;
  border: 1px solid #D4E1F3 !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.7) !important;
}
html[data-app-theme="light"] [data-testid="stMetricValue"] {
  font-size: 1.55rem !important;
  font-weight: 700 !important;
  color: #172554 !important;
}
html[data-app-theme="light"] [data-testid="stMetricLabel"] {
  font-size: 0.86rem !important;
  color: #64748B !important;
}
html[data-app-theme="light"] .stTabs [data-baseweb="tab-list"] {
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.65) !important;
}
html[data-app-theme="light"] .stTabs [data-baseweb="tab"] {
  min-height: 2.05rem !important;
  font-weight: 600 !important;
}
html[data-app-theme="light"] .stTextInput input,
html[data-app-theme="light"] .stNumberInput input,
html[data-app-theme="light"] .stTextArea textarea,
html[data-app-theme="light"] .stSelectbox div[data-baseweb="select"] > div {
  border-radius: 11px !important;
  border: 1px solid #DCE5F0 !important;
}
html[data-app-theme="light"] .stButton > button[kind="primary"] {
  min-height: 2.45rem !important;
  border-radius: 12px !important;
  font-weight: 700 !important;
}
html[data-app-theme="light"] .stButton > button[kind="secondary"] {
  min-height: 2.3rem !important;
  border-radius: 11px !important;
}
html[data-app-theme="light"] [data-testid="stAlert"] {
  border-radius: 12px !important;
}
.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div {
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
  background: var(--tab-active-bg) !important;
  color: var(--tab-active-fg) !important;
}
button[data-baseweb="tab"] {
  font-size: 1.05rem !important;
  font-weight: 600 !important;
}
section.main div[data-testid="stVerticalBlockBorderWrapper"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  box-shadow: var(--shadow) !important;
}
/* ===== Sidebar / admin panel (темний сайдбар, світлий текст) ===== */
html[data-app-theme="light"] [data-testid="stSidebar"] h1,
html[data-app-theme="light"] [data-testid="stSidebar"] h2,
html[data-app-theme="light"] [data-testid="stSidebar"] h3 {
  color: #FFFFFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .lm-auto-refresh-panel {
  margin: 0.1rem 0 0.45rem 0;
  background: transparent !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .lm-auto-refresh-title {
  color: #F4F7FF !important;
  font-size: 1.05rem !important;
  font-weight: 700 !important;
  line-height: 1.35 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .lm-auto-refresh-hint {
  color: #B9C8E9 !important;
  font-size: 0.8rem !important;
  margin-top: 0.12rem !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
  min-height: 3rem !important;
  font-size: 1.1rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.05em !important;
  border-radius: 12px !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"]:first-child .stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #F87171 0%, #EF4444 55%, #DC2626 100%) !important;
  color: #FFFFFF !important;
  border: none !important;
  box-shadow: 0 4px 14px rgba(239, 68, 68, 0.45) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] [data-testid="column"]:last-child .stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #34D399 0%, #10B981 55%, #059669 100%) !important;
  color: #FFFFFF !important;
  border: none !important;
  box-shadow: 0 4px 14px rgba(16, 185, 129, 0.45) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="primary"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="primary"] span {
  color: #FFFFFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="secondary"] {
  background: rgba(30, 45, 74, 0.85) !important;
  color: #9EB0D4 !important;
  border: 1px solid #4A5F8C !important;
  box-shadow: none !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="secondary"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.lm-auto-refresh-panel) ~ [data-testid="stVerticalBlockBorderWrapper"] .stButton > button[kind="secondary"] span {
  color: #9EB0D4 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stForm"] label,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stForm"] p {
  color: #DCE6FF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] {
  background: transparent !important;
  border: none !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] div[data-testid="stVerticalBlockBorderWrapper"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] h4,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] code {
  color: #E8EEFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stSuccess {
  background: rgba(6, 78, 59, 0.55) !important;
  border: 1px solid rgba(52, 211, 153, 0.55) !important;
  color: #D1FAE5 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stSuccess p,
html[data-app-theme="light"] [data-testid="stSidebar"] .stSuccess span {
  color: #D1FAE5 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stError {
  background: rgba(127, 29, 29, 0.55) !important;
  border: 1px solid rgba(248, 113, 113, 0.55) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stError p,
html[data-app-theme="light"] [data-testid="stSidebar"] .stError span {
  color: #FECACA !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stWarning {
  background: rgba(120, 53, 15, 0.55) !important;
  border: 1px solid rgba(251, 191, 36, 0.55) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stWarning p,
html[data-app-theme="light"] [data-testid="stSidebar"] .stWarning span {
  color: #FDE68A !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stInfo {
  background: rgba(30, 58, 138, 0.5) !important;
  border: 1px solid rgba(96, 165, 250, 0.5) !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stInfo p,
html[data-app-theme="light"] [data-testid="stSidebar"] .stInfo span {
  color: #DBEAFE !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button[kind="primary"] p,
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button[kind="primary"] span {
  color: #FFFFFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) p,
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button:not([kind="primary"]) span {
  color: #E8EEFF !important;
}
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html[data-app-theme="dark"] div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #2E3A48 !important;
  border: 3px solid #B8C9DC !important;
  outline: 2px solid rgba(184, 201, 220, 0.5) !important;
  box-shadow: 0 0 0 1px #9AA8BC, 0 10px 32px rgba(0, 0, 0, 0.55) !important;
  border-radius: 14px !important;
  padding: 1.1rem 1.25rem !important;
  margin-top: 0.25rem !important;
  margin-bottom: 0.5rem !important;
}
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card),
html[data-app-theme="light"] div[data-testid="stVerticalBlockBorderWrapper"].tab1-shipment-frame {
  background: #FFFBF5 !important;
  border: 2px solid #C9B896 !important;
  outline: 1px solid rgba(201, 184, 150, 0.45) !important;
  box-shadow: 0 4px 14px rgba(61, 52, 40, 0.1), 0 0 0 1px #E8DFD0 !important;
  border-radius: 14px !important;
  padding: 1.1rem 1.25rem !important;
  margin-top: 0.35rem !important;
  margin-bottom: 0.5rem !important;
}
hr.tab1-card-divider {
  border: none;
  border-top: 2px solid var(--border);
  margin: 0.85rem 0 1.1rem 0;
  opacity: 1;
}
html[data-app-theme="light"] hr.tab1-card-divider {
  border-top-color: #C9B896;
  border-top-style: dashed;
}
html[data-app-theme="dark"] hr.tab1-card-divider {
  border-top-color: #4B5563;
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
  border-left: 5px solid #9CA3AF !important;
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
html[data-app-theme="dark"] header[data-testid="stHeader"] a,
html[data-app-theme="dark"] header[data-testid="stHeader"] span,
html[data-app-theme="dark"] header[data-testid="stHeader"] p,
html[data-app-theme="dark"] header[data-testid="stHeader"] label {
  color: #F9FAFB !important;
}
html[data-app-theme="light"] header[data-testid="stHeader"] a,
html[data-app-theme="light"] header[data-testid="stHeader"] span,
html[data-app-theme="light"] header[data-testid="stHeader"] p,
html[data-app-theme="light"] header[data-testid="stHeader"] label {
  color: #3D3428 !important;
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
  border: 1px solid var(--hint-border);
  background: var(--hint-bg);
  color: var(--text);
  font-size: 0.92rem;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stMarkdownContainer"] p,
div[data-testid="stVerticalBlockBorderWrapper"]:has(.tab1-shipment-card)
  [data-testid="stCaptionContainer"] p {
  color: var(--tab1-card-text) !important;
}
[data-testid="stAlert"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {
  border: 1px solid #D4C4A8;
  border-radius: 10px;
  background-color: #FFFBF5 !important;
}
html[data-app-theme="light"] [data-testid="stDataEditor"],
html[data-app-theme="light"] [data-testid="stDataFrame"],
html[data-app-theme="light"] [data-testid="stDataEditor"] [data-testid="glideDataEditor"],
html[data-app-theme="light"] [data-testid="stDataFrame"] [data-testid="glideDataEditor"] {
  --gdg-bg-cell: #FFFFFF !important;
  --gdg-bg-cell-medium: #F3F6FC !important;
  --gdg-bg-header: #EEF3FA !important;
  --gdg-bg-header-hovered: #E2E8F0 !important;
  --gdg-bg-header-has-focus: #D6DFED !important;
  --gdg-text-dark: #1F2937 !important;
  --gdg-text-medium: #475569 !important;
  --gdg-text-light: #6B7280 !important;
  --gdg-text-header: #334155 !important;
  --gdg-border-color: #DCE3EE !important;
  --gdg-accent-color: #4F46E5 !important;
  --gdg-accent-fg: #FFFFFF !important;
  --gdg-accent-light: rgba(79, 70, 229, 0.18) !important;
  background-color: #FFFFFF !important;
  color-scheme: light !important;
}
html[data-app-theme="dark"] [data-testid="stDataEditor"],
html[data-app-theme="dark"] [data-testid="stDataFrame"],
html[data-app-theme="dark"] [data-testid="stDataEditor"] [data-testid="glideDataEditor"],
html[data-app-theme="dark"] [data-testid="stDataFrame"] [data-testid="glideDataEditor"] {
  --gdg-bg-cell: #111827 !important;
  --gdg-bg-cell-medium: #1F2937 !important;
  --gdg-bg-header: #1F2937 !important;
  --gdg-bg-header-hovered: #374151 !important;
  --gdg-bg-header-has-focus: #4B5563 !important;
  --gdg-text-dark: #F9FAFB !important;
  --gdg-text-medium: #D1D5DB !important;
  --gdg-text-light: #9CA3AF !important;
  --gdg-text-header: #F3F4F6 !important;
  --gdg-border-color: #374151 !important;
  --gdg-accent-color: #3B82F6 !important;
  --gdg-accent-fg: #FFFFFF !important;
  --gdg-accent-light: rgba(59, 130, 246, 0.25) !important;
  background-color: #111827 !important;
  color-scheme: dark !important;
}
html[data-app-theme="light"] [data-testid="stDataEditor"] .dvn-underlay,
html[data-app-theme="light"] [data-testid="stDataFrame"] .dvn-underlay {
  background: #FFFBF5 !important;
}
html[data-app-theme="dark"] [data-testid="stDataEditor"] .dvn-underlay,
html[data-app-theme="dark"] [data-testid="stDataFrame"] .dvn-underlay {
  background: #111827 !important;
}
html[data-app-theme="light"] section.main [data-testid="stExpander"] summary {
  background-color: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
html[data-app-theme="light"] section.main [data-testid="stExpander"] summary p,
html[data-app-theme="light"] section.main [data-testid="stExpander"] summary span {
  color: var(--text) !important;
}
html[data-app-theme="light"] section.main [data-testid="stExpanderDetails"] {
  background: var(--bg) !important;
  border: 1px solid var(--border) !important;
  border-top: none !important;
  border-radius: 0 0 10px 10px !important;
}
html[data-app-theme="light"] section.main [data-testid="stExpander"] {
  border: none !important;
  background: transparent !important;
}
/* Sidebar expanders — після глобальних правил, вища специфічність */
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary * {
  color: #F4F7FF !important;
  -webkit-text-fill-color: #F4F7FF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpander"] summary {
  background: #2A3D63 !important;
  border: 1px solid #5A72A8 !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
  background: #1A2640 !important;
  border: 1px solid #435782 !important;
  border-top: none !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] .stCaption,
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
html[data-app-theme="light"] [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
  color: #B9C8E9 !important;
  opacity: 1 !important;
}
html[data-app-theme="light"] [data-baseweb="popover"],
html[data-app-theme="light"] [data-baseweb="menu"] {
  background-color: var(--input-bg) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
html[data-app-theme="light"] [data-baseweb="menu"] li {
  color: var(--text) !important;
  background-color: var(--input-bg) !important;
}
html[data-app-theme="light"] [data-baseweb="menu"] li:hover {
  background-color: var(--surface) !important;
}
html[data-app-theme="light"] [data-testid="stToolbar"] button,
html[data-app-theme="light"] [data-testid="stToolbar"] span {
  color: var(--text) !important;
}
html[data-app-theme="light"] .up-journal-cell {
  color: var(--journal-cell) !important;
}
html[data-app-theme="light"] .up-journal-multiline {
  color: var(--journal-cell-muted) !important;
}
html[data-app-theme="light"] .up-journal-bc {
  color: var(--journal-bc) !important;
}
html[data-app-theme="light"] .up-journal-hdr {
  background: var(--journal-hdr-bg) !important;
  color: var(--journal-hdr-fg) !important;
  border-bottom-color: var(--journal-hdr-accent) !important;
}
html[data-app-theme="light"] .up-journal-postpay {
  color: var(--journal-postpay) !important;
}
html[data-app-theme="light"] .up-journal-row-active {
  background: var(--journal-row-active-bg) !important;
  border-color: var(--journal-row-active-border) !important;
}
html[data-app-theme="light"] div:has(> .up-journal-bc-click) + div button {
  color: var(--journal-link) !important;
}
html[data-app-theme="light"] div:has(> .up-journal-bc-click) + div button:hover {
  color: var(--journal-link-hover) !important;
  background: rgba(166, 124, 82, 0.12) !important;
}
html[data-app-theme="light"] div:has(> .up-journal-bc-click) + div button p,
html[data-app-theme="light"] div:has(> .up-journal-bc-click) + div button span {
  color: var(--journal-link) !important;
}
html[data-app-theme="light"] button[aria-label="Редагувати"],
html[data-app-theme="light"] button[aria-label="Перегляд / друк PDF"] {
  background: var(--surface) !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
}
html[data-app-theme="light"] button[aria-label="Видалити"] {
  background: #DC2626 !important;
  border: 1px solid #B91C1C !important;
  box-shadow: 0 2px 8px rgba(220, 38, 38, 0.35) !important;
  color: #FFFFFF !important;
}
html[data-app-theme="light"] button[aria-label="Видалити"] p,
html[data-app-theme="light"] button[aria-label="Видалити"] span {
  color: #FFFFFF !important;
}
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover,
html[data-app-theme="light"] [data-testid="stSidebar"] div.stButton > button:not([kind="primary"]):hover {
  filter: brightness(1.08);
}
html[data-app-theme="dark"] .up-journal-cell { color: var(--journal-cell) !important; }
html[data-app-theme="dark"] .up-journal-multiline { color: var(--journal-cell-muted) !important; }
html[data-app-theme="dark"] .up-journal-bc { color: var(--journal-bc) !important; }
html[data-app-theme="dark"] .up-journal-hdr {
  background: var(--journal-hdr-bg) !important;
  color: var(--journal-hdr-fg) !important;
  border-bottom-color: var(--journal-hdr-accent) !important;
}
html[data-app-theme="dark"] .up-journal-postpay { color: var(--journal-postpay) !important; }
html[data-app-theme="dark"] .up-journal-row-active {
  background: var(--journal-row-active-bg) !important;
  border-color: var(--journal-row-active-border) !important;
}
.app-login-card div[data-testid="stForm"] {
  max-width: 420px;
  margin: 0 auto;
  border-radius: 14px;
}
</style>
"""


_GLIDE_VARS_LIGHT = {
    "--gdg-bg-cell": "#FFFFFF",
    "--gdg-bg-cell-medium": "#F3F6FC",
    "--gdg-bg-header": "#EEF3FA",
    "--gdg-bg-header-hovered": "#E2E8F0",
    "--gdg-bg-header-has-focus": "#D6DFED",
    "--gdg-text-dark": "#1F2937",
    "--gdg-text-medium": "#475569",
    "--gdg-text-light": "#6B7280",
    "--gdg-text-header": "#334155",
    "--gdg-border-color": "#DCE3EE",
    "--gdg-accent-color": "#4F46E5",
    "--gdg-accent-fg": "#FFFFFF",
    "--gdg-accent-light": "rgba(79, 70, 229, 0.18)",
}
_GLIDE_VARS_DARK = {
    "--gdg-bg-cell": "#111827",
    "--gdg-bg-cell-medium": "#1F2937",
    "--gdg-bg-header": "#1F2937",
    "--gdg-bg-header-hovered": "#374151",
    "--gdg-bg-header-has-focus": "#4B5563",
    "--gdg-text-dark": "#F9FAFB",
    "--gdg-text-medium": "#D1D5DB",
    "--gdg-text-light": "#9CA3AF",
    "--gdg-text-header": "#F3F4F6",
    "--gdg-border-color": "#374151",
    "--gdg-accent-color": "#3B82F6",
    "--gdg-accent-fg": "#FFFFFF",
    "--gdg-accent-light": "rgba(59, 130, 246, 0.25)",
}


def _inject_glide_grid_theme(theme_id: str) -> None:
    """Glide Data Grid — CSS-змінні, відповідні поточній темі застосунку."""
    vars_map = _GLIDE_VARS_DARK if theme_id == THEME_DARK else _GLIDE_VARS_LIGHT
    underlay = "#111827" if theme_id == THEME_DARK else "#FFFBF5"
    scheme = "dark" if theme_id == THEME_DARK else "light"
    components.html(
        f"""
<script>
(function () {{
  const doc = window.parent.document;
  const vars = {json.dumps(vars_map)};
  const underlayBg = {json.dumps(underlay)};
  const scheme = {json.dumps(scheme)};
  function paint(el) {{
    Object.keys(vars).forEach(function (k) {{
      el.style.setProperty(k, vars[k]);
    }});
    el.style.setProperty("color-scheme", scheme, "important");
  }}
  function apply() {{
    doc.querySelectorAll(
      '[data-testid="stDataEditor"], [data-testid="stDataFrame"], [data-testid="glideDataEditor"]'
    ).forEach(paint);
    doc.querySelectorAll(".dvn-underlay").forEach(function (el) {{
      el.style.setProperty("background", underlayBg, "important");
    }});
  }}
  apply();
  if (window.parent._logisticGlideObs) window.parent._logisticGlideObs.disconnect();
  let t;
  window.parent._logisticGlideObs = new MutationObserver(function () {{
    clearTimeout(t);
    t = setTimeout(apply, 80);
  }});
  window.parent._logisticGlideObs.observe(doc.body, {{ childList: true, subtree: true }});
}})();
</script>
        """,
        height=0,
        width=0,
    )


def inject_app_theme() -> None:
    theme = get_app_theme()
    _inject_theme_shell(theme)
    st.markdown(_theme_stylesheet(), unsafe_allow_html=True)
    _inject_action_button_styles()
    _inject_theme_dom_fixes(theme)
    _inject_glide_grid_theme(theme)


def render_app_header() -> None:
    tok = _ui_tokens(get_app_theme())
    st.markdown(
        f"""
<div style="background:{tok['header_box_bg']};border:1px solid {tok['header_box_border']};
  border-left:5px solid {tok['header_accent']};border-radius:14px;padding:0.9rem 1.2rem;margin:0 0 1rem 0;">
  <div style="color:{tok['header_fg']};font-size:1.6rem;font-weight:800;margin:0;line-height:1.3;">
    ☑️ Alius Checkbox
  </div>
  <div style="color:{tok['header_sub']};font-size:0.9rem;margin:0.35rem 0 0 0;">
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


def render_sidebar_auto_refresh() -> None:
    """Авто-пошук: великі кнопки ВИКЛ/ВКЛ замість toggle (без артефактів теми)."""
    st.sidebar.markdown(
        """
<div class="lm-auto-refresh-panel">
  <div class="lm-auto-refresh-title">🔄 Авто-пошук</div>
  <div class="lm-auto-refresh-hint">ВКЛ / ВИКЛ</div>
</div>
        """,
        unsafe_allow_html=True,
    )
    active = bool(st.session_state.get("auto_refresh", False))
    col_off, col_on = st.sidebar.columns(2, gap="small")
    with col_off:
        if st.button(
            "ВИКЛ",
            key="_lm_auto_refresh_off",
            use_container_width=True,
            type="primary" if not active else "secondary",
        ):
            if active:
                st.session_state.auto_refresh = False
                st.rerun()
    with col_on:
        if st.button(
            "ВКЛ",
            key="_lm_auto_refresh_on",
            use_container_width=True,
            type="primary" if active else "secondary",
        ):
            if not active:
                st.session_state.auto_refresh = True
                st.rerun()


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
