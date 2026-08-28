from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class RozetkaUpPrefillTests(unittest.TestCase):
    def test_force_refresh_replaces_incomplete_cached_order(self):
        from tabs import tab_rozetka

        summary = {"id": 42, "delivery": {"place_number": "1"}}
        full = {
            "id": 42,
            "user_phone": "+380991112233",
            "delivery": {
                "recipient_title": "Тестова Олена Іванівна",
                "place_number": "1",
                "postcode": "65001",
            },
        }
        state = _SessionState(rozetka_order_detail_cache={"42": summary})
        fake_st = SimpleNamespace(session_state=state)
        get_order = Mock(return_value=({"content": full}, ""))

        with (
            patch.object(tab_rozetka, "st", fake_st),
            patch.object(tab_rozetka.rozetka, "get_order", get_order),
            patch.object(tab_rozetka.rozetka, "order_content", return_value=full),
        ):
            result, error = tab_rozetka._rz_get_order_cached(
                42,
                force_refresh=True,
            )

        self.assertEqual(error, "")
        self.assertEqual(result, full)
        self.assertEqual(state["rozetka_order_detail_cache"]["42"], full)
        get_order.assert_called_once_with(42)

    def test_create_flow_does_not_put_list_item_into_full_order_cache(self):
        source = (ROOT / "tabs" / "tab_rozetka.py").read_text(encoding="utf-8")

        self.assertNotIn('_rz_order_cache()[str(oid)] = order', source)
        self.assertIn("force_refresh=True", source)


if __name__ == "__main__":
    unittest.main()
