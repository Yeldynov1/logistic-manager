from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

import sheets


class _FakeSpreadsheet:
    def __init__(self):
        self.requests = []

    def batch_update(self, body):
        self.requests.append(body)


class _FakeOrdersSheet:
    id = 77

    def __init__(self, ttn_values):
        self._headers = ["ТТН", "Статус СМС", "Чек"]
        self._ttn_values = ["ТТН"] + list(ttn_values)
        self.cell_updates = []
        self.appended_rows = []
        self.spreadsheet = _FakeSpreadsheet()

    def row_values(self, row):
        return list(self._headers) if row == 1 else []

    def col_values(self, column):
        return list(self._ttn_values) if column == 1 else []

    def batch_update(self, batch, value_input_option=None):
        self.cell_updates.append((batch, value_input_option))

    def append_rows(self, rows, value_input_option=None):
        self.appended_rows.append((rows, value_input_option))


class _FakeStatusSheet(_FakeOrdersSheet):
    def __init__(self, ttn_values):
        super().__init__(ttn_values)
        self._headers = ["ТТН", "Статус", "Дата", "Телефон"]


class _FakeInvoiceSheet(_FakeOrdersSheet):
    def __init__(self, ttn_values, invoice_values):
        super().__init__(ttn_values)
        self._headers = ["ТТН", "Статус", "Номер накладної"]
        self._invoice_values = ["Номер накладної"] + list(invoice_values)

    def col_values(self, column):
        if column == 1:
            return list(self._ttn_values)
        if column == 3:
            return list(self._invoice_values)
        return []


class _FakeUpShipmentsSheet:
    def __init__(self, barcodes):
        self._barcodes = ["ШКІ"] + list(barcodes)
        self.cell_updates = []

    def col_values(self, column):
        return list(self._barcodes) if column == sheets._UP_BC_COL else []

    def batch_update(self, batch, value_input_option=None):
        self.cell_updates.append((batch, value_input_option))


class _FakeUpRecordSheet:
    def __init__(self, printed_mark):
        self.printed_mark = printed_mark
        self.updated = []

    def cell(self, _row, column):
        value = ""
        if column == sheets.UP_SHIPMENTS_HEADERS.index("Надруковано") + 1:
            value = self.printed_mark
        return type("Cell", (), {"value": value})()

    def update(self, cell_range, rows):
        self.updated.append((cell_range, rows))

    def delete_rows(self, _row):
        raise AssertionError("duplicate row was not expected")


class _FakeLegacyUpSheet:
    def __init__(self):
        self.col_count = 15
        self.headers = list(sheets.UP_SHIPMENTS_HEADERS[:-1])
        self.resized_to = None
        self.updated = []

    def resize(self, *, cols):
        self.resized_to = cols
        self.col_count = cols

    def row_values(self, row):
        return list(self.headers) if row == 1 else []

    def update(self, cell_range, rows):
        self.updated.append((cell_range, rows))


class _FakeUpWorkbook:
    def __init__(self, worksheet):
        self._worksheet = worksheet

    def worksheet(self, _title):
        return self._worksheet


class SheetsOrderWriteTests(unittest.TestCase):
    def test_legacy_up_sheet_is_resized_before_printed_header_is_added(self):
        worksheet = _FakeLegacyUpSheet()

        result = sheets._ensure_up_shipments_ws(_FakeUpWorkbook(worksheet))

        self.assertIs(result, worksheet)
        self.assertEqual(worksheet.resized_to, len(sheets.UP_SHIPMENTS_HEADERS))
        self.assertEqual(worksheet.updated[0][0], "A1:P1")
        self.assertEqual(worksheet.updated[0][1], [sheets.UP_SHIPMENTS_HEADERS])

    def test_update_finds_current_sheet_row_by_ttn(self):
        sheet = _FakeOrdersSheet(["TTN-A", "TTN-NEW", "TTN-B"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
            patch.object(sheets.load_data_from_gsheets, "clear"),
        ):
            ok, error = sheets.update_order_cells_by_ttn(
                "TTN-B", {"Статус СМС": "Видано вручну"}, silent=True
            )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertEqual(sheet.cell_updates[0][0][0]["range"], "B4")

    def test_update_duplicate_ttn_does_not_write(self):
        sheet = _FakeOrdersSheet(["TTN-A", "TTN-A"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
        ):
            ok, error = sheets.update_order_cells_by_ttn(
                "TTN-A", {"Статус СМС": "x"}, silent=True
            )

        self.assertFalse(ok)
        self.assertIn("дублюється", error)
        self.assertEqual(sheet.cell_updates, [])

    def test_delete_resolves_all_rows_before_single_batch(self):
        sheet = _FakeOrdersSheet(["TTN-A", "TTN-X", "TTN-B"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
            patch.object(sheets.load_data_from_gsheets, "clear"),
        ):
            ok, error = sheets.delete_orders_by_ttns(
                ["TTN-A", "TTN-B"], silent=True
            )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        requests = sheet.spreadsheet.requests[0]["requests"]
        starts = [r["deleteDimension"]["range"]["startIndex"] for r in requests]
        self.assertEqual(starts, [3, 1])

    def test_delete_missing_ttn_does_not_delete_anything(self):
        sheet = _FakeOrdersSheet(["TTN-A"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
        ):
            ok, error = sheets.delete_orders_by_ttns(
                ["TTN-A", "TTN-MISSING"], silent=True
            )

        self.assertFalse(ok)
        self.assertIn("не знайдено", error)
        self.assertEqual(sheet.spreadsheet.requests, [])

    def test_insert_new_orders_appends_only_missing_ttn(self):
        sheet = _FakeOrdersSheet(["TTN-A"])
        df = pd.DataFrame(
            [
                {"ТТН": "TTN-A", "Статус СМС": "", "Чек": ""},
                {"ТТН": "TTN-B", "Статус СМС": "", "Чек": ""},
            ]
        )
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
            patch.object(sheets.load_data_from_gsheets, "clear"),
        ):
            inserted, error = sheets.insert_new_orders(df, silent=True)

        self.assertEqual(error, "")
        self.assertEqual(inserted, 1)
        self.assertEqual(sheet.appended_rows[0][0], [["TTN-B", "", ""]])

    def test_status_batch_updates_only_status_and_date_by_current_ttn_row(self):
        sheet = _FakeStatusSheet(["TTN-A", "TTN-X", "TTN-B"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
            patch.object(sheets.load_data_from_gsheets, "clear"),
        ):
            written, error = sheets.update_order_statuses_by_ttn(
                [
                    (
                        "TTN-B",
                        {
                            "Статус": "Відправлення отримано",
                            "Дата": "2026-08-31 10:00:00",
                            "Телефон": "380000000000",
                        },
                    )
                ],
                silent=True,
            )

        self.assertEqual(written, 1)
        self.assertEqual(error, "")
        batch, value_mode = sheet.cell_updates[0]
        self.assertEqual(value_mode, "USER_ENTERED")
        self.assertEqual([cell["range"] for cell in batch], ["B4", "C4"])

    def test_status_batch_duplicate_ttn_writes_nothing(self):
        sheet = _FakeStatusSheet(["TTN-A", "TTN-A"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
        ):
            written, error = sheets.update_order_statuses_by_ttn(
                [("TTN-A", {"Статус": "Вручено"})],
                silent=True,
            )

        self.assertEqual(written, 0)
        self.assertIn("дублюється", error)
        self.assertEqual(sheet.cell_updates, [])

    def test_fill_missing_invoice_writes_only_exact_empty_row_as_raw(self):
        sheet = _FakeInvoiceSheet(
            ["0123456789012", "0123456789013"],
            ["", "EXISTING"],
        )
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
            patch.object(sheets.load_data_from_gsheets, "clear"),
        ):
            written, error = sheets.fill_missing_order_invoices_by_ttn(
                [("123456789012", "012345")],
                silent=True,
            )

        self.assertEqual(written, 1)
        self.assertEqual(error, "")
        batch, value_mode = sheet.cell_updates[0]
        self.assertEqual(value_mode, "RAW")
        self.assertEqual(batch, [{"range": "C2", "values": [["012345"]]}])

    def test_fill_missing_invoice_never_overwrites_existing_value(self):
        sheet = _FakeInvoiceSheet(["0123456789012"], ["KEEP"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
        ):
            written, error = sheets.fill_missing_order_invoices_by_ttn(
                [("0123456789012", "NEW")],
                silent=True,
            )

        self.assertEqual(written, 0)
        self.assertEqual(error, "")
        self.assertEqual(sheet.cell_updates, [])

    def test_fill_missing_invoice_duplicate_ttn_writes_nothing(self):
        sheet = _FakeInvoiceSheet(
            ["0123456789012", "123456789012"],
            ["", ""],
        )
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "get_google_sheet", return_value=sheet),
        ):
            written, error = sheets.fill_missing_order_invoices_by_ttn(
                [("0123456789012", "INV-1")],
                silent=True,
            )

        self.assertEqual(written, 0)
        self.assertIn("дублюється", error)
        self.assertEqual(sheet.cell_updates, [])

    def test_up_print_mark_is_written_to_exact_barcode_row(self):
        sheet = _FakeUpShipmentsSheet(["0123456789012", "0123456789013"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "_open_orders_spreadsheet", return_value=object()),
            patch.object(sheets, "_ensure_up_shipments_ws", return_value=sheet),
        ):
            marked = sheets.mark_up_shipments_printed(
                ["123456789013"],
                username="manager",
            )

        self.assertEqual(marked, 1)
        batch, value_mode = sheet.cell_updates[0]
        self.assertEqual(value_mode, "USER_ENTERED")
        self.assertEqual(batch[0]["range"], "P3")
        self.assertIn("manager", batch[0]["values"][0][0])

    def test_up_print_mark_updates_all_legacy_duplicate_barcode_rows(self):
        sheet = _FakeUpShipmentsSheet(["0123456789012", "0123456789012"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "_open_orders_spreadsheet", return_value=object()),
            patch.object(sheets, "_ensure_up_shipments_ws", return_value=sheet),
        ):
            marked = sheets.mark_up_shipments_printed(["0123456789012"])

        self.assertEqual(marked, 1)
        batch, value_mode = sheet.cell_updates[0]
        self.assertEqual(value_mode, "USER_ENTERED")
        self.assertEqual([cell["range"] for cell in batch], ["P2", "P3"])

    def test_up_print_mark_returns_specific_error_when_barcode_is_missing(self):
        sheet = _FakeUpShipmentsSheet(["0123456789012"])
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "_open_orders_spreadsheet", return_value=object()),
            patch.object(sheets, "_ensure_up_shipments_ws", return_value=sheet),
        ):
            marked, error = sheets.mark_up_shipments_printed(
                ["0123456789013"],
                return_error=True,
            )

        self.assertEqual(marked, 0)
        self.assertIn("не знайдено", error)
        self.assertEqual(sheet.cell_updates, [])

    def test_up_sync_preserves_existing_print_mark(self):
        sheet = _FakeUpRecordSheet("2026-08-31 17:00:00 · manager")
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=False),
            patch.object(sheets, "_open_orders_spreadsheet", return_value=object()),
            patch.object(sheets, "_ensure_up_shipments_ws", return_value=sheet),
            patch.object(sheets, "_find_up_shipment_sheet_rows", return_value=[2]),
        ):
            saved = sheets.append_up_shipment_record(
                {"ШКІ": "0123456789012", "Статус УП": "Створено"}
            )

        self.assertTrue(saved)
        cell_range, rows = sheet.updated[0]
        self.assertEqual(cell_range, "A2:P2")
        printed_index = sheets.UP_SHIPMENTS_HEADERS.index("Надруковано")
        self.assertEqual(rows[0][printed_index], "2026-08-31 17:00:00 · manager")


if __name__ == "__main__":
    unittest.main()
