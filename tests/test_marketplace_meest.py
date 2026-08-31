from __future__ import annotations

import unittest
from datetime import datetime
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

    def test_history_keeps_only_last_seven_days(self):
        orders = [
            {"created": "2026-08-30T10:00:00"},
            {"created": "2026-08-20T10:00:00"},
            {"created": ""},
        ]
        with patch.object(
            marketplace_meest.utils,
            "now_kyiv_naive",
            return_value=datetime(2026, 8, 31, 12, 0, 0),
        ):
            cutoff = marketplace_meest._history_cutoff(7)
            filtered = marketplace_meest._within_history(
                orders,
                marketplace_meest._rozetka_created,
                cutoff,
            )

        self.assertEqual(filtered, [orders[0]])

    def test_epicentr_history_requests_all_statuses(self):
        with (
            patch.object(marketplace_meest.epicentr, "token_configured", return_value=True),
            patch.object(
                marketplace_meest.epicentr,
                "fetch_orders",
                return_value=([], {"next": ""}, ""),
            ) as fetch,
        ):
            marketplace_meest._epicentr_orders(history_days=7)

        self.assertEqual(fetch.call_args.kwargs["status_codes"], ())

    def test_history_reads_details_when_list_omits_ttn(self):
        rozetka_summary = {
            "id": 11,
            "created": "2026-08-30T10:00:00",
            "delivery_service": {"name": "Meest"},
        }
        prom_summary = {
            "id": 22,
            "date_created": "2026-08-30T11:00:00",
            "delivery_option": {"name": "Meest"},
        }
        epic_summary = {
            "id": "epic-33",
            "createdAt": "2026-08-30T12:00:00",
            "address": {"shipment": {"provider": "meest", "number": ""}},
        }
        with (
            patch.object(
                marketplace_meest.rozetka,
                "get_order",
                return_value=({"content": {"ttn": "722-1000001"}}, ""),
            ),
            patch.object(
                marketplace_meest.promua,
                "fetch_order",
                return_value=(
                    {
                        "delivery_provider_data": {
                            "provider": "meest",
                            "declaration_number": "722-2000002",
                        }
                    },
                    "",
                ),
            ),
            patch.object(
                marketplace_meest.epicentr,
                "fetch_order",
                return_value=(
                    {
                        "address": {
                            "shipment": {
                                "provider": "meest",
                                "number": "722-3000003",
                            }
                        }
                    },
                    "",
                ),
            ),
        ):
            rz_rows, rz_lookups, rz_failures = (
                marketplace_meest._hydrate_missing_rozetka_ttns([rozetka_summary])
            )
            prom_rows, prom_lookups, prom_failures = (
                marketplace_meest._hydrate_missing_prom_ttns([prom_summary])
            )
            epic_rows, epic_lookups, epic_failures = (
                marketplace_meest._hydrate_missing_epicentr_ttns([epic_summary])
            )

        self.assertEqual(rz_rows[0]["ttn"], "722-1000001")
        self.assertEqual(marketplace_meest.promua.order_ttn(prom_rows[0]), "722-2000002")
        self.assertEqual(marketplace_meest.epicentr.order_ttn(epic_rows[0]), "7223000003")
        self.assertEqual((rz_lookups, prom_lookups, epic_lookups), (1, 1, 1))
        self.assertEqual((rz_failures, prom_failures, epic_failures), (0, 0, 0))

    def test_history_report_counts_each_marketplace_separately(self):
        with (
            patch.object(
                marketplace_meest,
                "_rozetka_orders",
                return_value=(
                    [{"ttn": "7221000001", "delivery_service": {"name": "Meest"}}],
                    "",
                ),
            ),
            patch.object(marketplace_meest, "_prom_orders", return_value=([], "")),
            patch.object(marketplace_meest, "_epicentr_orders", return_value=([], "")),
            patch.object(
                marketplace_meest,
                "_hydrate_missing_rozetka_ttns",
                side_effect=lambda orders: (orders, 0, 0),
            ),
        ):
            result = marketplace_meest.collect_marketplace_meest_orders(
                [], history_days=7
            )

        self.assertEqual(result.added["Rozetka"], 1)
        self.assertEqual(result.added["Prom.ua"], 0)
        self.assertEqual(result.added["Епіцентр"], 0)


if __name__ == "__main__":
    unittest.main()
