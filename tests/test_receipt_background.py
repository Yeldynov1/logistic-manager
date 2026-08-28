from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock

from scripts import receipt_background
from services.receipt_worker import (
    process_receipt_candidates,
    select_ready_receipts,
)


def _ready_row(ttn="20450000000001"):
    return {
        "ТТН": ttn,
        "Служба": "НП",
        "Статус": "Відправлення отримано",
        "Дата": "2026-08-28 07:00:00",
        "Телефон": "380501234567",
        "Вартість": 250.0,
        "Номер накладної": "INV-1",
        "Чек": "https://check.checkbox.ua/receipt/abc",
        "Повідомлення": "",
        "Статус СМС": "Не отправлено",
    }


class _FakeSpreadsheet:
    def __init__(self):
        self.batch_updates = []

    def batch_update(self, body):
        self.batch_updates.append(body)


class _FakeWorksheet:
    id = 42

    def __init__(self, rows):
        self.headers = [
            "ТТН",
            "Служба",
            "Статус",
            "Дата",
            "Телефон",
            "Вартість",
            "Номер накладної",
            "Чек",
            "Повідомлення",
            "Статус СМС",
        ]
        self.rows = [dict(row) for row in rows]
        self.spreadsheet = _FakeSpreadsheet()

    def row_values(self, row_number):
        if row_number == 1:
            return list(self.headers)
        row = self.rows[row_number - 2]
        return [row.get(header, "") for header in self.headers]

    def col_values(self, column_number):
        header = self.headers[column_number - 1]
        return [header] + [row.get(header, "") for row in self.rows]


class ReceiptSelectionTests(unittest.TestCase):
    def test_only_customer_delivery_with_check_phone_and_pending_sms_is_ready(self):
        ready = _ready_row()
        returned = _ready_row("20450000000002")
        returned["Статус"] = "Повернення. Вручено Відправнику"
        no_check = _ready_row("20450000000003")
        no_check["Чек"] = ""
        manual_done = _ready_row("20450000000004")
        manual_done["Статус СМС"] = "Видано вручну"

        selection = select_ready_receipts(
            [ready, returned, no_check, manual_done],
            limit=3,
        )

        self.assertEqual(selection.scanned, 4)
        self.assertEqual(selection.eligible, 1)
        self.assertEqual([c.ttn for c in selection.candidates], [ready["ТТН"]])

    def test_duplicate_ttn_rows_are_all_skipped(self):
        first = _ready_row("123456789012")
        first["Служба"] = "УП"
        first["Статус"] = "Вручено"
        duplicate = dict(first)
        duplicate["ТТН"] = "0123456789012"

        selection = select_ready_receipts([first, duplicate], limit=3)

        self.assertEqual(selection.eligible, 0)
        self.assertEqual(selection.duplicate_rows, 2)
        self.assertEqual(selection.candidates, ())

    def test_limit_never_selects_more_than_three(self):
        rows = [_ready_row(f"2045000000000{i}") for i in range(6)]

        selection = select_ready_receipts(rows, limit=3)

        self.assertEqual(selection.eligible, 6)
        self.assertEqual(len(selection.candidates), 3)

    def test_audited_sent_row_is_selected_for_cleanup_without_resending(self):
        row = _ready_row()
        row["Статус СМС"] = "Отправлено"

        selection = select_ready_receipts(
            [row],
            limit=1,
            completed_ttns=[row["ТТН"]],
        )

        self.assertEqual(len(selection.candidates), 1)


class ReceiptProcessTests(unittest.TestCase):
    def test_acceptance_is_audited_before_exact_row_deletion(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        candidate = select_ready_receipts([row], limit=1).candidates[0]
        events = []

        def send(phone, text, *, idempotency_key):
            events.append(("send", phone, text, idempotency_key))
            return True, "sms-123", ""

        def audit(_worksheet, current, message_id):
            events.append(("audit", current.ttn, message_id))
            return True

        def delete(_worksheet, ttn):
            events.append(("delete", ttn))
            return True, ""

        result = process_receipt_candidates(
            worksheet,
            [candidate],
            send_func=send,
            audit_func=audit,
            delete_func=delete,
        )

        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual([event[0] for event in events], ["send", "audit", "delete"])
        self.assertEqual(events[0][3], row["ТТН"])

    def test_existing_audit_only_finishes_delete_without_second_sms(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        candidate = select_ready_receipts([row], limit=1).candidates[0]
        send = Mock()
        audit = Mock()
        delete = Mock(return_value=(True, ""))

        result = process_receipt_candidates(
            worksheet,
            [candidate],
            send_func=send,
            completed_ttns=[row["ТТН"]],
            audit_func=audit,
            delete_func=delete,
        )

        self.assertEqual(result.accepted, 0)
        self.assertEqual(result.recovered, 1)
        self.assertEqual(result.removed, 1)
        send.assert_not_called()
        audit.assert_not_called()
        delete.assert_called_once()

    def test_failed_audit_keeps_row_for_idempotent_retry(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        candidate = select_ready_receipts([row], limit=1).candidates[0]
        delete = Mock()

        result = process_receipt_candidates(
            worksheet,
            [candidate],
            send_func=lambda *_args, **_kwargs: (True, "sms-123", ""),
            audit_func=lambda *_args: False,
            delete_func=delete,
        )

        self.assertEqual(result.accepted, 1)
        self.assertEqual(result.removed, 0)
        self.assertTrue(result.errors)
        delete.assert_not_called()

    def test_changed_phone_after_read_cancels_before_sms(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        candidate = select_ready_receipts([row], limit=1).candidates[0]
        worksheet.rows[0]["Телефон"] = "380671112233"
        send = Mock()

        result = process_receipt_candidates(
            worksheet,
            [candidate],
            send_func=send,
        )

        self.assertEqual(result.accepted, 0)
        self.assertTrue(result.errors)
        send.assert_not_called()


class ReceiptBackgroundCommandTests(unittest.TestCase):
    def test_preview_masks_ttn_and_never_calls_turbosms(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        send = Mock()
        output = io.StringIO()

        with redirect_stdout(output):
            code = receipt_background.main(
                ["--limit", "1"],
                load_context=lambda: (worksheet, [row]),
                send_func=send,
            )

        self.assertEqual(code, 0)
        send.assert_not_called()
        text = output.getvalue()
        self.assertIn("RECEIPT PREVIEW", text)
        self.assertIn("PREVIEW OK", text)
        self.assertNotIn(row["ТТН"], text)
        self.assertNotIn(row["Телефон"], text)
        self.assertNotIn(row["Чек"], text)

    def test_apply_requires_limit_specific_confirmation(self):
        row = _ready_row()
        worksheet = _FakeWorksheet([row])
        send = Mock()

        code = receipt_background.main(
            ["--limit", "3", "--apply", "--confirmation", "SEND-RECEIPTS-1"],
            load_context=lambda: (worksheet, [row]),
            send_func=send,
        )

        self.assertEqual(code, 2)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
