from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AutoRefreshStatusTests(unittest.TestCase):
    def _module(self):
        import core.auto_refresh_status as module

        return module

    def test_manager_activity_reports_recent_cycle_as_running(self):
        module = self._module()
        status = {
            "enabled": True,
            "last_cycle_at": "2026-08-28 10:00:00",
        }
        self.assertEqual(
            module.manager_auto_refresh_activity(
                status,
                now=datetime(2026, 8, 28, 10, 10, 0),
            ),
            "працює зараз",
        )

    def test_manager_activity_reports_stale_open_setting(self):
        module = self._module()
        status = {
            "enabled": True,
            "last_cycle_at": "2026-08-28 09:30:00",
        }
        self.assertIn(
            "неактивна",
            module.manager_auto_refresh_activity(
                status,
                now=datetime(2026, 8, 28, 10, 0, 0),
            ),
        )

    def test_manager_activity_reports_disabled(self):
        module = self._module()
        self.assertEqual(
            module.manager_auto_refresh_activity(
                {"enabled": False},
                now=datetime(2026, 8, 28, 10, 0, 0),
            ),
            "вимкнено",
        )

    def test_app_records_completed_cycle_heartbeat(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("persist_auto_refresh_cycle_completed", calls)


if __name__ == "__main__":
    unittest.main()
