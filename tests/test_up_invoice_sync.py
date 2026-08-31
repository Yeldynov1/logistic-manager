from __future__ import annotations

import unittest

import pandas as pd

from core.up_invoice_sync import (
    merge_missing_invoice_fields,
    plan_missing_up_invoice_updates,
    up_invoice_candidate,
)


class UkrposhtaInvoiceSyncTests(unittest.TestCase):
    def test_exact_journal_barcode_fills_blank_invoice(self):
        orders = pd.DataFrame(
            [{"ТТН": "0123456789012", "Номер накладної": ""}]
        )
        journal = pd.DataFrame(
            [{"ШКІ": "0123456789012", "Дод. інфо": "904448573"}]
        )

        self.assertEqual(
            plan_missing_up_invoice_updates(orders, journal),
            [("0123456789012", "904448573")],
        )

    def test_leading_zero_barcode_variant_matches(self):
        orders = pd.DataFrame(
            [{"ТТН": "123456789012", "Номер накладної": ""}]
        )
        journal = pd.DataFrame(
            [{"ШКІ": "0123456789012", "Дод. інфо": "INV-42"}]
        )

        self.assertEqual(
            plan_missing_up_invoice_updates(orders, journal),
            [("123456789012", "INV-42")],
        )

    def test_existing_invoice_is_never_planned(self):
        orders = pd.DataFrame(
            [{"ТТН": "0123456789012", "Номер накладної": "EXISTING"}]
        )
        journal = pd.DataFrame(
            [{"ШКІ": "0123456789012", "Дод. інфо": "NEW-42"}]
        )

        self.assertEqual(plan_missing_up_invoice_updates(orders, journal), [])

    def test_tracking_import_description_is_not_an_invoice(self):
        self.assertEqual(
            up_invoice_candidate(
                "Імпорт із трекінгу (повний доступ обмежено 123)."
            ),
            "",
        )

    def test_shipment_barcode_itself_is_not_an_invoice(self):
        self.assertEqual(
            up_invoice_candidate("0123456789012", "123456789012"),
            "",
        )

    def test_numeric_invoice_may_have_twelve_digits_when_not_the_barcode(self):
        self.assertEqual(
            up_invoice_candidate("999999999999", "0123456789012"),
            "999999999999",
        )

    def test_conflicting_journal_values_are_skipped(self):
        orders = pd.DataFrame(
            [{"ТТН": "0123456789012", "Номер накладної": ""}]
        )
        journal = pd.DataFrame(
            [
                {"ШКІ": "0123456789012", "Дод. інфо": "INV-1"},
                {"ШКІ": "0123456789012", "Дод. інфо": "INV-2"},
            ]
        )

        self.assertEqual(plan_missing_up_invoice_updates(orders, journal), [])

    def test_duplicate_order_ttns_are_skipped(self):
        orders = pd.DataFrame(
            [
                {"ТТН": "0123456789012", "Номер накладної": ""},
                {"ТТН": "123456789012", "Номер накладної": ""},
            ]
        )
        journal = pd.DataFrame(
            [{"ШКІ": "0123456789012", "Дод. інфо": "INV-1"}]
        )

        self.assertEqual(plan_missing_up_invoice_updates(orders, journal), [])

    def test_merge_only_fills_blank_local_invoice(self):
        local = pd.DataFrame(
            [
                {"ТТН": "0123456789012", "Номер накладної": ""},
                {"ТТН": "0123456789013", "Номер накладної": "KEEP"},
            ]
        )
        remote = pd.DataFrame(
            [
                {"ТТН": "123456789012", "Номер накладної": "INV-1"},
                {"ТТН": "0123456789013", "Номер накладної": "REPLACE"},
            ]
        )

        merged, changed = merge_missing_invoice_fields(local, remote)

        self.assertEqual(changed, 1)
        self.assertEqual(merged["Номер накладної"].tolist(), ["INV-1", "KEEP"])


if __name__ == "__main__":
    unittest.main()
