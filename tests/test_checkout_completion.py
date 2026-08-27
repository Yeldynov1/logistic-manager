from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

import utils
from tabs import tab1_checkout


class _SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def _orders_df(statuses):
    return pd.DataFrame(
        [
            {
                "ТТН": f"2045000000000{i}",
                "Служба": "НП",
                "Статус": "Відправлення отримано",
                "Дата": "2026-08-18 10:00:00",
                "Телефон": "380501234567",
                "Вартість": 100.0,
                "Номер накладної": f"INV-{i}",
                "Чек": "",
                "Повідомлення": "",
                "Статус СМС": status,
                "Статус Нагадування": "",
                "Дія": False,
            }
            for i, status in enumerate(statuses)
        ]
    )


class CheckoutCompletionTests(unittest.TestCase):
    def test_done_statuses_are_not_pending(self):
        df = _orders_df(
            ["", utils.SMS_STATUS_MANUAL_DONE, utils.SMS_STATUS_SENT]
        )

        self.assertEqual(
            tab1_checkout._tab1_pending_mask(df).tolist(),
            [True, False, False],
        )

    def test_delete_sent_filter_removes_only_manual_done(self):
        df = _orders_df(
            [utils.SMS_STATUS_MANUAL_DONE, utils.SMS_STATUS_SENT, ""]
        )

        cleaned = tab1_checkout._tab1_without_manual_done_rows(df)

        self.assertEqual(cleaned["Статус СМС"].tolist(), [utils.SMS_STATUS_SENT, ""])

    def test_receipt_not_required_waits_for_manual_done(self):
        df = _orders_df([""])
        df.at[0, "Номер накладної"] = "*NO-RECEIPT"

        changed = utils.apply_no_receipt_auto_sent(df)

        self.assertEqual(changed, 0)
        self.assertEqual(df.at[0, "Статус СМС"], "")
        self.assertTrue(tab1_checkout._tab1_pending_mask(df).iloc[0])
        self.assertFalse(tab1_checkout._tab1_ready_for_turbosms(df.loc[0]))

    def test_manual_done_updates_sheet_without_deleting_row(self):
        df = _orders_df([""])
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab1_checkout.st, "session_state", session),
            patch.object(
                tab1_checkout.sheets,
                "update_order_cells_by_ttn",
                return_value=(True, ""),
            ) as update_cells,
            patch.object(tab1_checkout.sheets, "delete_orders_by_ttns") as delete_rows,
            patch.object(tab1_checkout.threading, "Thread") as thread,
        ):
            ok = tab1_checkout._tab1_mark_done(0, row)

        self.assertTrue(ok)
        self.assertEqual(len(session["df"]), 1)
        self.assertEqual(
            session["df"].at[0, "Статус СМС"], utils.SMS_STATUS_MANUAL_DONE
        )
        update_cells.assert_called_once()
        delete_rows.assert_not_called()
        thread.assert_called_once()

    def test_turbosms_completion_deletes_only_accepted_row(self):
        df = _orders_df([utils.SMS_STATUS_MANUAL_DONE, ""])
        row = df.loc[1].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab1_checkout.st, "session_state", session),
            patch.object(
                tab1_checkout.sheets,
                "delete_orders_by_ttns",
                return_value=(True, ""),
            ) as delete_rows,
        ):
            tab1_checkout._tab1_finalize_turbosms_sent(1, row)

        self.assertEqual(len(session["df"]), 1)
        self.assertEqual(
            session["df"].at[0, "Статус СМС"], utils.SMS_STATUS_MANUAL_DONE
        )
        delete_rows.assert_called_once_with(["20450000000001"], silent=True)

    def test_bulk_turbosms_does_not_send_when_ttn_is_ambiguous(self):
        df = _orders_df([""])
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab1_checkout.st, "session_state", session),
            patch.object(
                tab1_checkout.sheets,
                "validate_order_ttns",
                return_value=(False, "ТТН дублюється"),
            ),
            patch.object(tab1_checkout.utils, "turbosms_send") as send_sms,
        ):
            sent, errors = tab1_checkout._tab1_bulk_send_turbosms(
                [(0, row, "test")]
            )

        self.assertEqual(sent, 0)
        self.assertTrue(errors)
        send_sms.assert_not_called()


if __name__ == "__main__":
    unittest.main()
