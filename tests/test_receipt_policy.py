from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import Mock
from unittest.mock import patch

import pandas as pd

import utils
import sheets
from core.receipt_policy import (
    mark_created_orders_no_receipt,
    mark_np_orders_no_receipt_from_cutoff,
)


class ReceiptPolicyTests(unittest.TestCase):
    def test_new_orders_need_no_receipt_from_cutoff_date(self):
        self.assertEqual(utils.new_order_sms_status(date(2026, 10, 12)), "")
        self.assertEqual(
            utils.new_order_sms_status(date(2026, 10, 13)),
            utils.SMS_STATUS_NOT_REQUIRED,
        )
        self.assertEqual(
            utils.new_order_sms_status(date(2026, 10, 14)),
            utils.SMS_STATUS_NOT_REQUIRED,
        )

    def test_created_rows_are_marked_with_targeted_write(self):
        df = pd.DataFrame(
            [
                {"ТТН": "created-1", "Статус": "Створено", "Статус СМС": ""},
                {"ТТН": "old-1", "Статус": "В дорозі", "Статус СМС": ""},
                {
                    "ТТН": "sent-1",
                    "Статус": "Створено",
                    "Статус СМС": utils.SMS_STATUS_SENT,
                },
            ]
        )
        update = Mock(return_value=(True, ""))

        changed, errors = mark_created_orders_no_receipt(df, update)

        self.assertEqual(changed, 1)
        self.assertEqual(errors, [])
        self.assertEqual(df.at[0, "Статус СМС"], utils.SMS_STATUS_NOT_REQUIRED)
        self.assertEqual(df.at[1, "Статус СМС"], "")
        self.assertEqual(df.at[2, "Статус СМС"], utils.SMS_STATUS_SENT)
        update.assert_called_once_with(
            "created-1",
            {"Статус СМС": utils.SMS_STATUS_NOT_REQUIRED},
            silent=True,
        )

    def test_np_rows_from_cutoff_are_marked_without_touching_other_rows(self):
        df = pd.DataFrame(
            [
                {
                    "ТТН": "20450000000001",
                    "Служба": "НП",
                    "Статус": "Відправлення отримано",
                    "Дата": "2026-10-13 09:00:00",
                    "Статус СМС": "",
                },
                {
                    "ТТН": "20450000000002",
                    "Служба": "НП",
                    "Статус": "Відправлення отримано",
                    "Дата": "2026-10-12 23:59:59",
                    "Статус СМС": "",
                },
                {
                    "ТТН": "0500000000001",
                    "Служба": "УП",
                    "Статус": "Вручено",
                    "Дата": "2026-10-14 10:00:00",
                    "Статус СМС": "",
                },
                {
                    "ТТН": "20450000000003",
                    "Служба": "НП",
                    "Статус": "Відправлення отримано",
                    "Дата": "2026-10-14 10:00:00",
                    "Статус СМС": utils.SMS_STATUS_SENT,
                },
            ]
        )
        update = Mock(return_value=(True, ""))

        changed, errors = mark_np_orders_no_receipt_from_cutoff(df, update)

        self.assertEqual(changed, 1)
        self.assertEqual(errors, [])
        self.assertEqual(df.at[0, "Статус СМС"], utils.SMS_STATUS_NOT_REQUIRED)
        self.assertEqual(df.at[1, "Статус СМС"], "")
        self.assertEqual(df.at[2, "Статус СМС"], "")
        self.assertEqual(df.at[3, "Статус СМС"], utils.SMS_STATUS_SENT)
        update.assert_called_once_with(
            "20450000000001",
            {"Статус СМС": utils.SMS_STATUS_NOT_REQUIRED},
            silent=True,
        )

    def test_np_cutoff_uses_original_supabase_date_in_kyiv_timezone(self):
        df = pd.DataFrame(
            [
                {
                    "ТТН": "20450000000004",
                    "Служба": "НП",
                    "Статус": "Відправлення отримано",
                    "Дата": "2026-10-17 12:00:00",
                    "_created_at_raw": "2026-10-12T22:00:00+00:00",
                    "Статус СМС": "",
                }
            ]
        )
        update = Mock(return_value=(True, ""))

        changed, errors = mark_np_orders_no_receipt_from_cutoff(df, update)

        self.assertEqual(changed, 1)
        self.assertEqual(errors, [])
        update.assert_called_once()

    def test_not_required_row_is_never_receipt_eligible(self):
        row = {
            "ТТН": "20450000000001",
            "Служба": "НП",
            "Статус": "Відправлення отримано",
            "Статус СМС": utils.SMS_STATUS_NOT_REQUIRED,
            "Телефон": "380501234567",
            "Чек": "https://check.checkbox.ua/example",
        }

        self.assertTrue(utils.sms_status_is_done(row["Статус СМС"]))
        self.assertTrue(utils.row_receipt_not_required(row))

    def test_atomic_insert_marks_every_new_order_no_receipt(self):
        incoming = pd.DataFrame(
            [{"ТТН": "new-1", "Статус": "Нове", "Статус СМС": ""}]
        )
        with (
            patch.object(sheets, "_use_supabase_backend", return_value=True),
            patch(
                "storage.supabase_repo.insert_new_orders_df",
                return_value=(1, ""),
            ) as insert_rows,
        ):
            inserted, error = sheets.insert_new_orders(incoming, silent=True)

        self.assertEqual(inserted, 1)
        self.assertEqual(error, "")
        prepared = insert_rows.call_args.args[0]
        self.assertEqual(
            prepared.iloc[0]["Статус СМС"],
            utils.SMS_STATUS_NOT_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
