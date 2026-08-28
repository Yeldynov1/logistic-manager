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

    def test_full_prefill_does_not_erase_postcode_from_order_list(self):
        from tabs import tab_rozetka

        merged = tab_rozetka._rz_merge_up_prefills(
            {
                "rozetka_order_id": 904448573,
                "postcode": "27224",
                "city": "Павлогірківка",
            },
            {
                "rozetka_order_id": 904448573,
                "postcode": "",
                "city": "Павлогірківка",
                "phone": "380982011235",
            },
        )

        self.assertEqual(merged["postcode"], "27224")
        self.assertEqual(merged["phone"], "380982011235")

    def test_five_digit_place_number_is_postcode_not_branch_label(self):
        from services import rozetka

        order = {"delivery": {"place_number": "27224"}}

        self.assertEqual(rozetka.delivery_postcode_display(order), "27224")
        self.assertEqual(rozetka.delivery_place_hint(order), "")
        self.assertEqual(
            rozetka.explicit_postcode_from_prefill({"place_number": "27224"}),
            "27224",
        )

    def test_prefill_keeps_explicit_postcode_when_classifier_misses_it(self):
        from services import rozetka

        state = _SessionState()
        fake_st = SimpleNamespace(session_state=state)
        prefill = {
            "rozetka_order_id": 904448573,
            "delivery_service": "Укрпошта",
            "lastname": "Ферченко",
            "firstname": "Сергій",
            "middlename": "Олександрович",
            "phone": "380982011235",
            "postcode": "",
            "region": "Кіровоградська",
            "district": "Кропивницький",
            "city": "Павлогірківка",
            "place_number": "27224",
            "delivery_to_branch": True,
        }

        with (
            patch.object(rozetka, "st", fake_st),
            patch.object(rozetka, "up_postcode_if_known", return_value=("", None)),
        ):
            rozetka.apply_up_wizard_prefill(prefill)

        self.assertEqual(state["upwiz_postcode_value"], "27224")
        self.assertEqual(state["upwiz_lastname"], "Ферченко")
        self.assertEqual(state["upwiz_phone"], "+380982011235")
        self.assertEqual(state["upwiz_city"], "Павлогірківка")
        self.assertTrue(state["upwiz_postcode_lookup_ok"])

    def test_resolve_postcode_returns_explicit_index_without_classifier(self):
        from services import rozetka

        prefill = {
            "rozetka_order_id": 904448573,
            "postcode": "",
            "region": "Кіровоградська",
            "city": "Павлогірківка",
            "place_number": "27224",
        }
        with patch.object(rozetka, "up_postcode_if_known", return_value=("", None)):
            pc, loc = rozetka.resolve_postcode_from_prefill(prefill)

        self.assertEqual(pc, "27224")
        self.assertEqual(loc["region"], "Кіровоградська")
        self.assertEqual(loc["city"], "Павлогірківка")

    def test_consume_queued_prefill_resets_widget_keys(self):
        from services import rozetka

        state = _SessionState(
            upwiz_lastname="",
            upwiz_postcode="",
            rozetka_up_prefill={
                "rozetka_order_id": 1,
                "lastname": "Тест",
                "firstname": "Олена",
                "phone": "380991112233",
                "region": "Київська",
                "city": "Київ",
                "postcode": "01001",
            },
        )
        fake_st = SimpleNamespace(session_state=state)
        with (
            patch.object(rozetka, "st", fake_st),
            patch.object(rozetka, "register_up_journal_draft"),
            patch.object(rozetka, "up_postcode_if_known", return_value=("", None)),
        ):
            applied = rozetka.consume_queued_up_wizard_prefill(register_draft=False)

        self.assertTrue(applied)
        self.assertNotIn("rozetka_up_prefill", state)
        self.assertEqual(state["upwiz_lastname"], "Тест")
        self.assertEqual(state["upwiz_postcode_value"], "01001")
        self.assertTrue(state["upwiz_form_open"])

    def test_failed_create_queues_prefill_until_up_tab_opens(self):
        from services import rozetka

        state = _SessionState()
        fake_st = SimpleNamespace(session_state=state)
        prefill = {"rozetka_order_id": 904448573, "postcode": "27224"}

        with (
            patch.object(rozetka, "st", fake_st),
            patch.object(rozetka, "register_up_journal_draft") as register,
        ):
            rozetka.queue_up_wizard_prefill(prefill)

        self.assertEqual(state["rozetka_up_prefill"], prefill)
        self.assertNotIn("upwiz_lastname", state)
        register.assert_called_once_with(prefill)


if __name__ == "__main__":
    unittest.main()
