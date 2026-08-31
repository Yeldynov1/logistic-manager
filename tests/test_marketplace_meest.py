from __future__ import annotations

import unittest
from unittest.mock import patch

from services import marketplace_meest


class MarketplaceMeestDiscoveryTests(unittest.TestCase):
    def _collect(self, *, rozetka_orders=None, prom_orders=None, epic_orders=None, existing=()):
        with (
            patch.object(
                marketplace_meest,
                "_rozetka_orders",
                return_value=(rozetka_orders or [], ""),
            ),
            patch.object(
                marketplace_meest,
                "_prom_orders",
                return_value=(prom_orders or [], ""),
            ),
            patch.object(
                marketplace_meest,
                "_epicentr_orders",
                return_value=(epic_orders or [], ""),
            ),
        ):
            return marketplace_meest.collect_marketplace_meest_orders(existing)

    def test_imports_meest_from_all_marketplaces_and_leaves_invoice_empty(self):
        result = self._collect(
            rozetka_orders=[
                {
                    "ttn": "722-1000001",
                    "user_phone": "+380501111111",
                    "cost_with_discount": "101.50",
                    "created": "2026-08-30T10:00:00",
                    "delivery_service": {"name": "Meest Пошта"},
                }
            ],
            prom_orders=[
                {
                    "id": 22,
                    "phone": "+380502222222",
                    "price": "202,00 грн",
                    "date_created": "2026-08-30T11:00:00",
                    "delivery_option": {"name": "Meest"},
                    "delivery_provider_data": {
                        "provider": "meest",
                        "declaration_number": "722-2000002",
                    },
                }
            ],
            epic_orders=[
                {
                    "id": "epic-33",
                    "createdAt": "2026-08-30T12:00:00",
                    "subtotal": 303,
                    "address": {
                        "phone": "+380503333333",
                        "shipment": {"provider": "meest", "number": "722-3000003"},
                    },
                }
            ],
        )

        self.assertEqual(len(result.rows), 3)
        self.assertEqual([row["Служба"] for row in result.rows], ["Meest"] * 3)
        self.assertEqual([row["Статус"] for row in result.rows], ["Нове"] * 3)
        self.assertEqual([row["Номер накладної"] for row in result.rows], [""] * 3)
        self.assertEqual([row["Вартість"] for row in result.rows], [101.5, 202.0, 303.0])
        self.assertEqual(
            [row["Телефон"] for row in result.rows],
            ["380501111111", "380502222222", "380503333333"],
        )

    def test_ignores_non_meest_and_rows_without_ttn(self):
        result = self._collect(
            rozetka_orders=[
                {
                    "ttn": "20450000000001",
                    "delivery_service": {"name": "Нова пошта"},
                },
                {"ttn": "", "delivery_service": {"name": "Meest"}},
            ]
        )

        self.assertEqual(result.rows, [])

    def test_hyphen_variant_is_not_added_twice(self):
        result = self._collect(
            rozetka_orders=[
                {
                    "ttn": "722-1000001",
                    "delivery_service": {"name": "Meest"},
                }
            ],
            existing=["7221000001"],
        )

        self.assertEqual(result.rows, [])

    def test_same_ttn_from_two_marketplaces_is_added_once(self):
        result = self._collect(
            rozetka_orders=[
                {"ttn": "722-1000001", "delivery_service": {"name": "Meest"}}
            ],
            prom_orders=[
                {
                    "delivery_option": {"name": "Meest"},
                    "delivery_provider_data": {"declaration_number": "7221000001"},
                }
            ],
        )

        self.assertEqual(len(result.rows), 1)

    def test_one_marketplace_error_does_not_block_the_others(self):
        with (
            patch.object(
                marketplace_meest,
                "_rozetka_orders",
                return_value=([], "Rozetka unavailable"),
            ),
            patch.object(
                marketplace_meest,
                "_prom_orders",
                return_value=(
                    [
                        {
                            "delivery_option": {"name": "Meest"},
                            "delivery_provider_data": {"declaration_number": "7221000002"},
                        }
                    ],
                    "",
                ),
            ),
            patch.object(marketplace_meest, "_epicentr_orders", return_value=([], "")),
        ):
            result = marketplace_meest.collect_marketplace_meest_orders([])

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("Rozetka", result.errors[0])


if __name__ == "__main__":
    unittest.main()
