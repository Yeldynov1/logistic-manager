from __future__ import annotations

import unittest

from core.order_identity import order_ttn_match_keys, resolve_order_ttn_rows


class OrderIdentityTests(unittest.TestCase):
    def test_exact_ttn(self):
        rows, error = resolve_order_ttn_rows(
            ["ТТН", "20450000000001", "20450000000002"],
            ["20450000000002"],
        )
        self.assertEqual(error, "")
        self.assertEqual(rows, {"20450000000002": 3})

    def test_ukrposhta_leading_zero_is_preserved(self):
        rows, error = resolve_order_ttn_rows(
            ["ТТН", "500000000001"],
            ["0500000000001"],
        )
        self.assertEqual(error, "")
        self.assertEqual(rows, {"0500000000001": 2})

    def test_meest_hyphen_variant_matches(self):
        self.assertTrue(
            order_ttn_match_keys("721-000-111")
            & order_ttn_match_keys("721000111")
        )

    def test_missing_ttn_cancels_whole_operation(self):
        rows, error = resolve_order_ttn_rows(
            ["ТТН", "20450000000001"],
            ["20450000000001", "20450000000002"],
        )
        self.assertEqual(rows, {})
        self.assertIn("не знайдено", error)

    def test_duplicate_ttn_cancels_operation(self):
        rows, error = resolve_order_ttn_rows(
            ["ТТН", "20450000000001", "20450000000001"],
            ["20450000000001"],
        )
        self.assertEqual(rows, {})
        self.assertIn("дублюється", error)


if __name__ == "__main__":
    unittest.main()
