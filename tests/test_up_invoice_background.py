from __future__ import annotations

import unittest

from scripts import up_invoice_background


class _FakeWorksheet:
    def __init__(self, headers, records):
        self.headers = list(headers)
        self.records = [dict(row) for row in records]
        self.writes = []

    def get_all_records(self):
        return [dict(row) for row in self.records]

    def row_values(self, row):
        return list(self.headers) if row == 1 else []

    def col_values(self, column):
        name = self.headers[column - 1]
        return [name] + [row.get(name, "") for row in self.records]

    def batch_update(self, batch, value_input_option=None):
        self.writes.append((batch, value_input_option))


class UkrposhtaInvoiceBackgroundTests(unittest.TestCase):
    def _context(self):
        orders = _FakeWorksheet(
            ["ТТН", "Номер накладної"],
            [{"ТТН": "0123456789012", "Номер накладної": ""}],
        )
        journal = _FakeWorksheet(
            ["ШКІ", "Дод. інфо"],
            [{"ШКІ": "123456789012", "Дод. інфо": "INV-42"}],
        )
        return orders, journal

    def test_preview_never_writes(self):
        orders, journal = self._context()

        result = up_invoice_background.main(
            ["--limit", "20"],
            load_context=lambda: (orders, journal),
        )

        self.assertEqual(result, 0)
        self.assertEqual(orders.writes, [])

    def test_apply_writes_only_invoice_cell_as_raw(self):
        orders, journal = self._context()

        result = up_invoice_background.main(
            [
                "--limit",
                "20",
                "--apply",
                "--confirmation",
                "FILL-UP-INVOICES-20",
            ],
            load_context=lambda: (orders, journal),
        )

        self.assertEqual(result, 0)
        batch, value_mode = orders.writes[0]
        self.assertEqual(value_mode, "RAW")
        self.assertEqual(batch, [{"range": "B2", "values": [["INV-42"]]}])

    def test_apply_requires_exact_confirmation(self):
        orders, journal = self._context()

        result = up_invoice_background.main(
            ["--limit", "20", "--apply", "--confirmation", "WRONG"],
            load_context=lambda: (orders, journal),
        )

        self.assertEqual(result, 2)
        self.assertEqual(orders.writes, [])


if __name__ == "__main__":
    unittest.main()
