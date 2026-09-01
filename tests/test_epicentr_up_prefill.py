from __future__ import annotations

import unittest
from unittest.mock import patch

from services import epicentr


def _v6_order() -> dict:
    return {
        "id": "dec9761c-9ed0-403f-a01a-5e25154ebcab",
        "number": "1000000373",
        "subtotal": 174.0,
        "address": {
            "firstName": "Сергій",
            "lastName": "Федченко",
            "patronymic": "Олександрович",
            "phone": "0501234567",
            "recipient": {
                "firstName": "",
                "lastName": "",
                "patronymic": "",
                "phone": "",
            },
            "shipment": {
                "provider": "ukrposhta",
                "paymentProvider": "pay_on_delivery",
                "settlementId": "78aa6000-2c16-430d-824c-db2f70e96ad9",
                "officeId": "78aa6000-2c16-430d-824c-db2f70e96ada",
            },
        },
        "settlement": {
            "id": "78aa6000-2c16-430d-824c-db2f70e96ad9",
            "title": "Павлоград",
            "region": "Дніпропетровська",
            "district": "Павлоградський",
        },
        "office": {
            "id": "78aa6000-2c16-430d-824c-db2f70e96ada",
            "number": "12",
            "title": "Відділення Укрпошти",
        },
    }


class EpicentrOrderDetailTests(unittest.TestCase):
    def test_fetch_order_prefers_current_v6(self):
        order = _v6_order()
        oid = order["id"]
        with (
            patch.object(epicentr, "_api_request", return_value=(order, "")) as request,
            patch.object(epicentr, "enrich_order_delivery", side_effect=lambda value: value),
        ):
            result, error = epicentr.fetch_order(oid)

        self.assertEqual(error, "")
        self.assertEqual(result, order)
        request.assert_called_once_with("GET", f"/v6/oms/orders/{oid}")

    def test_fetch_order_falls_back_to_v5(self):
        order = _v6_order()
        oid = order["id"]
        with (
            patch.object(
                epicentr,
                "_api_request",
                side_effect=[(None, "V6 unavailable"), (order, "")],
            ) as request,
            patch.object(epicentr, "enrich_order_delivery", side_effect=lambda value: value),
        ):
            result, error = epicentr.fetch_order(oid)

        self.assertEqual(error, "")
        self.assertEqual(result, order)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args, ("GET", f"/v5/oms/orders/{oid}"))

    def test_missing_location_blocks_are_loaded_by_current_exact_endpoints(self):
        order = _v6_order()
        expected_settlement = order.pop("settlement")
        expected_office = order.pop("office")
        with (
            patch.object(
                epicentr,
                "_fetch_settlement_by_id",
                return_value=(expected_settlement, ""),
            ) as settlement_fetch,
            patch.object(
                epicentr,
                "_fetch_office_by_id",
                return_value=(expected_office, ""),
            ) as office_fetch,
        ):
            enriched = epicentr.enrich_order_delivery(order)

        self.assertEqual(enriched["settlement"], expected_settlement)
        self.assertEqual(enriched["office"], expected_office)
        settlement_fetch.assert_called_once_with(
            "ukrposhta",
            "78aa6000-2c16-430d-824c-db2f70e96ad9",
        )
        office_fetch.assert_called_once_with(
            "ukrposhta",
            "78aa6000-2c16-430d-824c-db2f70e96ad9",
            "78aa6000-2c16-430d-824c-db2f70e96ada",
        )

    def test_office_list_uses_current_non_participant_route(self):
        with patch.object(
            epicentr,
            "_api_request",
            return_value=({"items": [{"id": "office"}]}, ""),
        ) as request:
            offices, error = epicentr._fetch_offices_for_settlement(
                "ukrposhta",
                "78aa6000-2c16-430d-824c-db2f70e96ad9",
            )

        self.assertEqual(error, "")
        self.assertEqual(offices, [{"id": "office"}])
        path = request.call_args.args[1]
        self.assertEqual(
            path,
            "/v3/deliveries/providers/ukrposhta/settlements/"
            "78aa6000-2c16-430d-824c-db2f70e96ad9/offices",
        )
        self.assertNotIn("participants", path)


class EpicentrUkrposhtaPrefillTests(unittest.TestCase):
    def test_v6_office_number_resolves_postcode_and_keeps_buyer_data(self):
        order = _v6_order()
        location = {
            "region": "Дніпропетровська область",
            "district": "Павлоградський район",
            "city": "м. Павлоград",
        }
        with patch.object(
            epicentr,
            "_resolve_up_branch_postcode",
            return_value=("51400", location),
        ) as resolve:
            prefill = epicentr.build_up_prefill(order)

        resolve.assert_called_once_with("Павлоград", "Дніпропетровська", "12")
        self.assertEqual(prefill["lastname"], "Федченко")
        self.assertEqual(prefill["firstname"], "Сергій")
        self.assertEqual(prefill["middlename"], "Олександрович")
        self.assertEqual(prefill["phone"], "380501234567")
        self.assertEqual(prefill["place_number"], "12")
        self.assertEqual(prefill["postcode"], "51400")
        self.assertEqual(prefill["city"], "Павлоград")

    def test_explicit_postcode_from_epicentr_is_preserved(self):
        order = _v6_order()
        order["office"]["postIndex"] = "27224"

        prefill = epicentr.build_up_prefill(order)

        self.assertEqual(prefill["postcode"], "27224")

    def test_nested_settlement_and_office_are_supported(self):
        order = _v6_order()
        order["address"]["settlement"] = order.pop("settlement")
        order["address"]["office"] = order.pop("office")
        with patch.object(
            epicentr,
            "_resolve_up_branch_postcode",
            return_value=("51400", None),
        ):
            prefill = epicentr.build_up_prefill(order)

        self.assertEqual(prefill["place_number"], "12")
        self.assertEqual(prefill["postcode"], "51400")
        self.assertEqual(prefill["city"], "Павлоград")


if __name__ == "__main__":
    unittest.main()
