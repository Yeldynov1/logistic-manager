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

    def test_auto_refresh_edit_lock_helpers_exist(self):
        source = (ROOT / "ui_theme.py").read_text(encoding="utf-8")
        self.assertIn("def is_auto_refresh_edit_locked()", source)
        self.assertIn("data-lm-auto-locked", source)

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

    def test_auto_cycle_updates_statuses_without_full_table_save(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        start = source.index("def _run_auto_cycle_fragment()")
        end = source.index("\n\n_run_auto_cycle_fragment()", start)
        auto_cycle = source[start:end]

        self.assertIn("merge_status_fields(", auto_cycle)
        self.assertIn("drop_completed_receipt_rows(", auto_cycle)
        self.assertIn("_refresh_auto_carrier_statuses()", auto_cycle)
        self.assertNotIn("process_status_updates(", auto_cycle)
        self.assertNotIn("sheets.save_manual(", auto_cycle)

        helper_start = source.index("def _refresh_auto_carrier_statuses()")
        helper_end = source.index("\n\n@st.fragment", helper_start)
        helper = source[helper_start:helper_end]
        self.assertIn("run_status_cycle(", helper)
        self.assertIn("sheets.update_order_statuses_by_ttn(", helper)
        self.assertIn("plan_missing_up_invoice_updates(", helper)
        self.assertIn("sheets.fill_missing_order_invoices_by_ttn(", helper)
        self.assertIn("merge_missing_invoice_fields(", helper)

    def test_manual_status_refresh_also_fills_missing_up_invoices(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        start = source.index("def process_status_updates(")
        end = source.index("\nload_data()", start)
        helper = source[start:end]

        self.assertIn("plan_missing_up_invoice_updates(", helper)
        self.assertIn("sheets.fill_missing_order_invoices_by_ttn(", helper)

    def test_auto_search_inserts_new_orders_without_full_table_save(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        helper_start = source.index("def _persist_discovered_orders(")
        helper_end = source.index("\n\n@st.fragment", helper_start)
        helper = source[helper_start:helper_end]
        cycle_start = source.index("def _run_auto_cycle_fragment()")
        cycle_end = source.index("\n\n_run_auto_cycle_fragment()", cycle_start)
        cycle = source[cycle_start:cycle_end]

        self.assertIn("sheets.insert_new_orders(", helper)
        self.assertIn("_persist_discovered_orders(all_new)", cycle)
        self.assertNotIn("sheets.save_manual(", cycle)


if __name__ == "__main__":
    unittest.main()
