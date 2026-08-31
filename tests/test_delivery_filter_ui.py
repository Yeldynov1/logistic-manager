from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from ui import delivery_logos


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.buttons = []
        self.column_counts = []

    def button(self, label, *, key, type, use_container_width):
        self.buttons.append((label, key, type, use_container_width))
        return False

    def columns(self, count):
        self.column_counts.append(count)
        return [_Column() for _ in range(count)]

    def rerun(self, **_kwargs):
        raise AssertionError("rerun was not expected")


class DeliveryFilterUiTests(unittest.TestCase):
    def test_ukrposhta_is_default_and_show_all_is_above_service_row(self):
        fake = _FakeStreamlit()

        with patch.dict(sys.modules, {"streamlit": fake}):
            kinds = delivery_logos.render_delivery_service_filter(
                key="rz_delivery_filter",
                counts={"all": 11, "УП": 5, "НП": 6},
                fragment=True,
            )

        self.assertEqual(kinds, ["УП"])
        self.assertEqual(fake.session_state["rz_delivery_filter_active"], "УП")
        self.assertTrue(fake.buttons[0][0].startswith("Показати всі"))
        self.assertEqual(fake.buttons[1][0], "Укрпошта · 5")
        self.assertEqual(fake.column_counts, [len(delivery_logos.DELIVERY_KIND_OPTIONS)])

    def test_existing_non_all_selection_is_preserved(self):
        fake = _FakeStreamlit()
        fake.session_state["prom_delivery_filter_active"] = "НП"

        with patch.dict(sys.modules, {"streamlit": fake}):
            kinds = delivery_logos.render_delivery_service_filter(
                key="prom_delivery_filter",
            )

        self.assertEqual(kinds, ["НП"])
        self.assertEqual(fake.session_state["prom_delivery_filter_active"], "НП")


if __name__ == "__main__":
    unittest.main()
