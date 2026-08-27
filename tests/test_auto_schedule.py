from __future__ import annotations

import unittest

from core.auto_schedule import AUTO_CYCLE_INTERVAL_SECONDS, auto_cycle_is_due


class AutoScheduleTests(unittest.TestCase):
    def test_interval_is_five_minutes(self):
        self.assertEqual(AUTO_CYCLE_INTERVAL_SECONDS, 300)

    def test_first_cycle_is_due_immediately(self):
        self.assertTrue(auto_cycle_is_due(None, 1000))

    def test_ui_rerun_does_not_repeat_cycle_before_interval(self):
        self.assertFalse(auto_cycle_is_due(1000, 1299.9))
        self.assertTrue(auto_cycle_is_due(1000, 1300))

    def test_clock_reset_does_not_block_cycle(self):
        self.assertTrue(auto_cycle_is_due(2000, 1000))


if __name__ == "__main__":
    unittest.main()
