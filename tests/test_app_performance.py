from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AppPerformanceTests(unittest.TestCase):
    def test_auto_refresh_never_blocks_session_with_sleep(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertNotIn("time.sleep(60)", source)
        self.assertIn(
            "@st.fragment(run_every=AUTO_CYCLE_INTERVAL_SECONDS)", source
        )
        self.assertIn("auto_cycle_is_due(", source)

    def test_enabling_auto_refresh_forces_one_fresh_cycle(self):
        source = (ROOT / "ui_theme.py").read_text(encoding="utf-8")

        self.assertIn('st.session_state.pop("last_auto_cycle", None)', source)

    def test_streamlit_requirement_supports_timed_fragments(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("streamlit>=1.55.0,<2", requirements)

    def test_only_open_tab_is_rendered(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn(
            'st.tabs(_tab_names, key="_main_tabs", on_change="rerun")', source
        )
        self.assertIn("if not _tabs[_tab_i].open:", source)

    def test_ukrposhta_status_is_short_cached(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")

        marker = "@st.cache_data(ttl=240, show_spinner=False)\ndef get_up_status_smart"
        self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
