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

    def test_auto_cycle_reads_ready_statuses_instead_of_polling_carriers(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        start = source.index("def _run_auto_cycle_fragment()")
        end = source.index("\n\n_run_auto_cycle_fragment()", start)
        auto_cycle = source[start:end]

        self.assertIn("merge_status_fields(", auto_cycle)
        self.assertIn("drop_completed_receipt_rows(", auto_cycle)
        self.assertNotIn("process_status_updates(", auto_cycle)


if __name__ == "__main__":
    unittest.main()
