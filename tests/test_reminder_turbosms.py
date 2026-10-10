from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from tabs import tab5_reminders


class _SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def _reminder_df(status: str = "") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ТТН": "20450000000001",
                "Служба": "НП",
                "Статус": "Прибуло у відділення",
                "Дата": "2026-10-01 10:00:00",
                "Телефон": "380501234567",
                "Статус Нагадування": status,
            }
        ]
    )


class ReminderTurboSmsTests(unittest.TestCase):
    def test_success_marks_only_reminder_status_after_turbosms_acceptance(self):
        df = _reminder_df()
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab5_reminders.st, "session_state", session),
            patch.object(
                tab5_reminders.sheets,
                "validate_order_ttns",
                return_value=(True, ""),
            ),
            patch.object(
                tab5_reminders.utils,
                "turbosms_send",
                return_value=(True, "sms-123", ""),
            ) as send_sms,
            patch.object(
                tab5_reminders.sheets,
                "update_order_cells_by_ttn",
                return_value=(True, ""),
            ) as update_cells,
            patch.object(tab5_reminders, "audit_log") as audit,
        ):
            accepted, saved, error = tab5_reminders._send_reminder_turbosms(
                0, row, "Заберіть, будь ласка, посилку."
            )

        self.assertTrue(accepted)
        self.assertTrue(saved)
        self.assertEqual(error, "")
        self.assertEqual(df.at[0, "Статус Нагадування"], "Отправлено")
        send_sms.assert_called_once_with(
            "380501234567",
            "Заберіть, будь ласка, посилку.",
            idempotency_key="reminder:20450000000001",
        )
        update_cells.assert_called_once_with(
            "20450000000001",
            {"Статус Нагадування": "Отправлено"},
            silent=True,
        )
        audit.assert_called_once_with(
            "смс_нагадування",
            "20450000000001",
            "TurboSMS · id=sms-123",
        )

    def test_rejected_sms_does_not_mark_reminder_sent(self):
        df = _reminder_df()
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab5_reminders.st, "session_state", session),
            patch.object(
                tab5_reminders.sheets,
                "validate_order_ttns",
                return_value=(True, ""),
            ),
            patch.object(
                tab5_reminders.utils,
                "turbosms_send",
                return_value=(False, None, "Недостатньо коштів"),
            ),
            patch.object(
                tab5_reminders.sheets, "update_order_cells_by_ttn"
            ) as update_cells,
            patch.object(tab5_reminders, "audit_log") as audit,
        ):
            accepted, saved, error = tab5_reminders._send_reminder_turbosms(
                0, row, "Нагадування"
            )

        self.assertFalse(accepted)
        self.assertFalse(saved)
        self.assertIn("Недостатньо", error)
        self.assertEqual(df.at[0, "Статус Нагадування"], "")
        update_cells.assert_not_called()
        audit.assert_not_called()

    def test_already_sent_reminder_never_calls_turbosms(self):
        df = _reminder_df("Отправлено")
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab5_reminders.st, "session_state", session),
            patch.object(tab5_reminders.sheets, "validate_order_ttns") as validate,
            patch.object(tab5_reminders.utils, "turbosms_send") as send_sms,
        ):
            accepted, saved, error = tab5_reminders._send_reminder_turbosms(
                0, row, "Нагадування"
            )

        self.assertFalse(accepted)
        self.assertFalse(saved)
        self.assertIn("вже", error)
        validate.assert_not_called()
        send_sms.assert_not_called()

    def test_ambiguous_ttn_never_calls_turbosms(self):
        df = _reminder_df()
        row = df.loc[0].copy()
        session = _SessionState(df=df)

        with (
            patch.object(tab5_reminders.st, "session_state", session),
            patch.object(
                tab5_reminders.sheets,
                "validate_order_ttns",
                return_value=(False, "ТТН дублюється"),
            ),
            patch.object(tab5_reminders.utils, "turbosms_send") as send_sms,
            patch.object(
                tab5_reminders.sheets, "update_order_cells_by_ttn"
            ) as update_cells,
        ):
            accepted, saved, error = tab5_reminders._send_reminder_turbosms(
                0, row, "Нагадування"
            )

        self.assertFalse(accepted)
        self.assertFalse(saved)
        self.assertIn("дублюється", error)
        send_sms.assert_not_called()
        update_cells.assert_not_called()


if __name__ == "__main__":
    unittest.main()
