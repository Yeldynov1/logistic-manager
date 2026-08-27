from __future__ import annotations

import unittest

import pandas as pd

from core.status_sync import merge_status_fields


class StatusSyncTests(unittest.TestCase):
    def test_updates_only_status_and_date_and_preserves_local_work(self):
        local = pd.DataFrame(
            [
                {
                    "ТТН": "20450000000001",
                    "Статус": "В дорозі",
                    "Дата": "",
                    "Телефон": "0501112233",
                    "Чек": "https://receipt.test/1",
                    "Повідомлення": "мій текст",
                    "Вартість": 321.5,
                }
            ]
        )
        remote = pd.DataFrame(
            [
                {
                    "ТТН": "20450000000001",
                    "Статус": "Відправлення отримано",
                    "Дата": "2026-08-27 12:30:00",
                    "Телефон": "інший",
                    "Чек": "інший чек",
                    "Повідомлення": "інший текст",
                    "Вартість": 999,
                }
            ]
        )

        merged, changed = merge_status_fields(local, remote)

        self.assertEqual(changed, 1)
        self.assertEqual(merged.at[0, "Статус"], "Відправлення отримано")
        self.assertEqual(merged.at[0, "Дата"], "2026-08-27 12:30:00")
        self.assertEqual(merged.at[0, "Телефон"], "0501112233")
        self.assertEqual(merged.at[0, "Чек"], "https://receipt.test/1")
        self.assertEqual(merged.at[0, "Повідомлення"], "мій текст")
        self.assertEqual(merged.at[0, "Вартість"], 321.5)

    def test_matches_ukrposhta_ttn_with_missing_leading_zero(self):
        local = pd.DataFrame([{"ТТН": "123456789012", "Статус": "В дорозі"}])
        remote = pd.DataFrame([{"ТТН": "0123456789012", "Статус": "Вручено"}])

        merged, changed = merge_status_fields(local, remote)

        self.assertEqual(changed, 1)
        self.assertEqual(merged.at[0, "Статус"], "Вручено")

    def test_duplicate_remote_ttn_is_skipped(self):
        local = pd.DataFrame([{"ТТН": "20450000000001", "Статус": "В дорозі"}])
        remote = pd.DataFrame(
            [
                {"ТТН": "20450000000001", "Статус": "Статус 1"},
                {"ТТН": "20450000000001", "Статус": "Статус 2"},
            ]
        )

        merged, changed = merge_status_fields(local, remote)

        self.assertEqual(changed, 0)
        self.assertEqual(merged.at[0, "Статус"], "В дорозі")


if __name__ == "__main__":
    unittest.main()
