from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from scripts import prom_ttn_background
from services import prom_ttn_queue


class _FakeWorksheet:
    def __init__(self, records=None):
        self.records = list(records or [])
        self.appended = []
        self.batch_updates = []

    def get_all_records(self):
        return list(self.records)

    def append_row(self, row, value_input_option=None):
        self.appended.append((list(row), value_input_option))

    def batch_update(self, batch, value_input_option=None):
        self.batch_updates.append((list(batch), value_input_option))


def _record(*, due="2026-09-01 10:20:00", status="pending", ttn="0123456789012"):
    return {
        "Створено": "2026-09-01 10:00:00",
        "Передати після": due,
        "Prom ID": "12345",
        "ТТН": ttn,
        "Статус": status,
        "Спроб": "0",
        "Остання спроба": "",
        "Помилка": "",
    }


class PromTtnQueueTests(unittest.TestCase):
    def test_enqueue_schedules_transfer_after_twenty_minutes(self):
        worksheet = _FakeWorksheet()

        ok, message = prom_ttn_queue.enqueue_transfer(
            worksheet,
            12345,
            "0123456789012",
            now=datetime(2026, 9, 1, 10, 0, 0),
        )

        self.assertTrue(ok)
        self.assertIn("10:20", message)
        row, mode = worksheet.appended[0]
        self.assertEqual(mode, "RAW")
        self.assertEqual(row[1], "2026-09-01 10:20:00")
        self.assertEqual(row[2:5], ["12345", "0123456789012", "pending"])

    def test_enqueue_does_not_duplicate_same_order_and_ttn(self):
        worksheet = _FakeWorksheet([_record()])

        ok, message = prom_ttn_queue.enqueue_transfer(
            worksheet,
            12345,
            "0123456789012",
            now=datetime(2026, 9, 1, 10, 1, 0),
        )

        self.assertTrue(ok)
        self.assertIn("уже є", message)
        self.assertEqual(worksheet.appended, [])

    def test_enqueue_blocks_different_pending_ttn_for_same_order(self):
        worksheet = _FakeWorksheet([_record()])

        ok, message = prom_ttn_queue.enqueue_transfer(
            worksheet,
            12345,
            "0999999999999",
            now=datetime(2026, 9, 1, 10, 1, 0),
        )

        self.assertFalse(ok)
        self.assertIn("інша ТТН", message)
        self.assertEqual(worksheet.appended, [])

    def test_only_due_pending_rows_are_selected(self):
        records = [
            _record(due="2026-09-01 10:19:59"),
            _record(due="2026-09-01 10:21:00", ttn="0123456789013"),
            _record(due="2026-09-01 10:00:00", status="done", ttn="0123456789014"),
        ]

        selected = prom_ttn_queue.select_due_transfers(
            records,
            now=datetime(2026, 9, 1, 10, 20, 0),
            limit=5,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].row_number, 2)
        self.assertEqual(selected[0].ttn, "0123456789012")


class PromTtnBackgroundTests(unittest.TestCase):
    def test_preview_does_not_call_prom_or_write_queue(self):
        worksheet = _FakeWorksheet([_record()])
        calls = []

        code = prom_ttn_background.main(
            ["--limit", "5"],
            load_context=lambda: (worksheet, worksheet.records),
            fetch_order=lambda _oid: calls.append("fetch"),
            send_ttn=lambda *_args, **_kwargs: calls.append("send"),
            now=datetime(2026, 9, 1, 10, 30, 0),
        )

        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertEqual(worksheet.batch_updates, [])

    def test_apply_sends_due_ttn_and_marks_exact_queue_row_done(self):
        worksheet = _FakeWorksheet([_record()])
        sent = []

        code = prom_ttn_background.main(
            [
                "--limit",
                "5",
                "--apply",
                "--confirmation",
                "SEND-PROM-TTNS-5",
            ],
            load_context=lambda: (worksheet, worksheet.records),
            fetch_order=lambda _oid: ({"id": 12345}, ""),
            send_ttn=lambda oid, ttn, **kwargs: (
                sent.append((oid, ttn, kwargs)) or {},
                "",
            ),
            now=datetime(2026, 9, 1, 10, 30, 0),
        )

        self.assertEqual(code, 0)
        self.assertEqual(sent[0][0:2], (12345, "0123456789012"))
        self.assertEqual(sent[0][2]["delivery_type"], "ukrposhta")
        batch, mode = worksheet.batch_updates[0]
        self.assertEqual(mode, "USER_ENTERED")
        self.assertEqual([item["range"] for item in batch], ["E2", "F2", "G2", "H2"])
        self.assertEqual(batch[0]["values"], [["done"]])

    def test_existing_different_prom_ttn_is_not_overwritten(self):
        worksheet = _FakeWorksheet([_record()])
        sent = []

        code = prom_ttn_background.main(
            [
                "--limit",
                "5",
                "--apply",
                "--confirmation",
                "SEND-PROM-TTNS-5",
            ],
            load_context=lambda: (worksheet, worksheet.records),
            fetch_order=lambda _oid: (
                {
                    "delivery_provider_data": {
                        "declaration_number": "0999999999999"
                    }
                },
                "",
            ),
            send_ttn=lambda *_args, **_kwargs: sent.append(True),
            now=datetime(2026, 9, 1, 10, 30, 0),
        )

        self.assertEqual(code, 0)
        self.assertEqual(sent, [])
        batch, _mode = worksheet.batch_updates[0]
        self.assertEqual(batch[0]["values"], [["conflict"]])

    def test_prom_too_early_error_keeps_item_pending_for_next_run(self):
        worksheet = _FakeWorksheet([_record()])

        code = prom_ttn_background.main(
            [
                "--limit",
                "5",
                "--apply",
                "--confirmation",
                "SEND-PROM-TTNS-5",
            ],
            load_context=lambda: (worksheet, worksheet.records),
            fetch_order=lambda _oid: ({"id": 12345}, ""),
            send_ttn=lambda *_args, **_kwargs: (None, "Prom.ua ще не готовий"),
            now=datetime(2026, 9, 1, 10, 30, 0),
        )

        self.assertEqual(code, 0)
        batch, _mode = worksheet.batch_updates[0]
        self.assertEqual(batch[0]["values"], [["pending"]])
        self.assertIn("ще не готовий", batch[3]["values"][0][0])

    def test_app_queues_prom_transfer_instead_of_sending_immediately(self):
        source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
            encoding="utf-8"
        )
        flush = source.split("def _flush_rozetka_pending_up_create", 1)[1].split(
            "def _up_enrich_wizard_address_from_postcode", 1
        )[0]

        self.assertIn("_queue_prom_ttn_transfer(pending, bc)", flush)
        self.assertNotIn("promua.save_declaration_id", flush)


if __name__ == "__main__":
    unittest.main()
