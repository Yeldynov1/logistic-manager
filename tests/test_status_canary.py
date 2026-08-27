from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from scripts import status_canary
from services.status_sheet_writer import OrdersStatusBatchWriter
from services.status_worker import CarrierStatus


class _FakeWorksheet:
    def __init__(self, ttns):
        self.headers = ["ТТН", "Статус", "Дата", "Чек", "Статус СМС"]
        self.ttns = ["ТТН"] + list(ttns)
        self.batch_updates = []

    def row_values(self, row):
        return list(self.headers) if row == 1 else []

    def col_values(self, column):
        return list(self.ttns) if column == 1 else []

    def batch_update(self, batch, value_input_option=None):
        self.batch_updates.append((batch, value_input_option))


def _canary_context():
    worksheet = _FakeWorksheet(["20450000000001", "123456789012"])
    rows = [
        {
            "ТТН": "20450000000001",
            "Служба": "НП",
            "Статус": "В дорозі",
            "Дата": "",
        },
        {
            "ТТН": "123456789012",
            "Служба": "УП",
            "Статус": "В дорозі",
            "Дата": "",
        },
    ]
    return worksheet, rows


def _np_fetch(ttns):
    return {
        ttns[0]: CarrierStatus(
            status="Відправлення отримано",
            invoice="SHOULD-NOT-BE-WRITTEN",
        )
    }


def _up_fetch(_ttn):
    return CarrierStatus(status="Вручено", date="27.08.2026 12:30:00")


class StatusSheetWriterTests(unittest.TestCase):
    def test_forbidden_receipt_or_sms_columns_cancel_entire_batch(self):
        worksheet, _ = _canary_context()
        writer = OrdersStatusBatchWriter(worksheet)

        prepared, error = writer.prepare(
            [("20450000000001", {"Статус": "Вручено", "Чек": "secret"})]
        )

        self.assertEqual(prepared.row_count, 0)
        self.assertIn("Чек", error)
        self.assertEqual(worksheet.batch_updates, [])

    def test_duplicate_sheet_ttn_cancels_before_write(self):
        worksheet = _FakeWorksheet(["20450000000001", "20450000000001"])
        writer = OrdersStatusBatchWriter(worksheet)

        prepared, error = writer.prepare(
            [("20450000000001", {"Статус": "Вручено"})]
        )

        self.assertEqual(prepared.row_count, 0)
        self.assertIn("дублюється", error)
        self.assertEqual(worksheet.batch_updates, [])


class StatusCanaryCommandTests(unittest.TestCase):
    def test_preview_validates_targets_without_batch_update(self):
        worksheet, rows = _canary_context()
        output = io.StringIO()

        with redirect_stdout(output):
            code = status_canary.main(
                ["--candidate-limit", "1"],
                load_context=lambda: (worksheet, rows),
                np_fetch_many=_np_fetch,
                up_fetch_one=_up_fetch,
            )

        self.assertEqual(code, 0)
        self.assertEqual(worksheet.batch_updates, [])
        text = output.getvalue()
        self.assertIn("CANARY PREVIEW", text)
        self.assertIn("PREVIEW OK", text)
        self.assertNotIn("20450000000001", text)
        self.assertNotIn("SHOULD-NOT-BE-WRITTEN", text)

    def test_apply_requires_exact_second_confirmation(self):
        worksheet, rows = _canary_context()

        code = status_canary.main(
            ["--apply", "--confirmation", "wrong"],
            load_context=lambda: (worksheet, rows),
            np_fetch_many=_np_fetch,
            up_fetch_one=_up_fetch,
        )

        self.assertEqual(code, 2)
        self.assertEqual(worksheet.batch_updates, [])

    def test_confirmed_apply_uses_one_batch_and_only_status_date_cells(self):
        worksheet, rows = _canary_context()

        code = status_canary.main(
            [
                "--candidate-limit",
                "1",
                "--apply",
                "--confirmation",
                "WRITE-1-NP-1-UP",
            ],
            load_context=lambda: (worksheet, rows),
            np_fetch_many=_np_fetch,
            up_fetch_one=_up_fetch,
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(worksheet.batch_updates), 1)
        batch, value_mode = worksheet.batch_updates[0]
        self.assertEqual(value_mode, "USER_ENTERED")
        self.assertEqual({item["range"] for item in batch}, {"B2", "B3", "C3"})
        self.assertTrue(all(not item["range"].startswith(("D", "E")) for item in batch))


class StatusCanaryWorkflowTests(unittest.TestCase):
    def test_preview_workflow_has_no_write_switch_or_turbosms(self):
        workflow = (
            status_canary.ROOT
            / ".github"
            / "workflows"
            / "status-canary-preview.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn(
            "python scripts/status_canary.py --candidate-limit 5", workflow
        )
        self.assertNotIn("--apply", workflow)
        self.assertNotIn("TURBOSMS", workflow.upper())
        self.assertIn("persist-credentials: false", workflow)


if __name__ == "__main__":
    unittest.main()
