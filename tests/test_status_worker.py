from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.status_worker import CarrierStatus, run_status_cycle


class StatusWorkerTests(unittest.TestCase):
    def test_dry_run_plans_changes_without_writing_or_sms_fields(self):
        rows = [
            {
                "ТТН": "20450000000001",
                "Служба": "НП",
                "Статус": "В дорозі",
                "Дата": "2026-08-20 10:00:00",
                "Телефон": "",
                "Вартість": 100,
                "Номер накладної": "",
                "Чек": "https://example.test/receipt",
                "Статус СМС": "",
            }
        ]
        writer = Mock()

        result = run_status_cycle(
            rows,
            np_fetch_many=lambda ttns: {
                ttns[0]: CarrierStatus(
                    status="Відправлення отримано",
                    cost=120,
                    phone="0501234567",
                    invoice="12345",
                )
            },
            write_changes=writer,
            dry_run=True,
        )

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.eligible, 1)
        self.assertEqual(result.written, 0)
        self.assertEqual(len(result.planned), 1)
        changes = result.planned[0].changes
        self.assertEqual(changes["Статус"], "Відправлення отримано")
        self.assertEqual(changes["Телефон"], "380501234567")
        self.assertEqual(changes["Номер накладної"], "012345")
        self.assertNotIn("Чек", changes)
        self.assertNotIn("Статус СМС", changes)
        writer.assert_not_called()

    def test_final_status_is_not_requested(self):
        np_fetch = Mock(return_value={})

        result = run_status_cycle(
            [
                {
                    "ТТН": "20450000000001",
                    "Служба": "НП",
                    "Статус": "Відправлення отримано",
                }
            ],
            np_fetch_many=np_fetch,
        )

        self.assertEqual(result.skipped_final, 1)
        self.assertEqual(result.eligible, 0)
        np_fetch.assert_not_called()

    def test_ukrposhta_restores_leading_zero_and_writes_by_original_ttn(self):
        up_fetch = Mock(
            return_value=CarrierStatus(
                status="Вручено",
                date="27.08.2026 12:30:00",
            )
        )
        writer = Mock(return_value=(True, ""))

        result = run_status_cycle(
            [{"ТТН": "123456789012", "Служба": "УП", "Статус": "В дорозі"}],
            up_fetch_one=up_fetch,
            write_changes=writer,
            dry_run=False,
        )

        up_fetch.assert_called_once_with("0123456789012")
        writer.assert_called_once_with(
            "123456789012",
            {"Статус": "Вручено", "Дата": "2026-08-27 12:30:00"},
        )
        self.assertEqual(result.written, 1)

    def test_one_failed_write_does_not_cancel_other_ttn(self):
        rows = [
            {"ТТН": "20450000000001", "Служба": "НП", "Статус": "В дорозі"},
            {"ТТН": "20450000000002", "Служба": "НП", "Статус": "В дорозі"},
        ]

        def np_fetch(ttns):
            return {ttn: CarrierStatus(status="У відділенні") for ttn in ttns}

        writer = Mock(side_effect=[(False, "ТТН дублюється"), (True, "")])
        result = run_status_cycle(
            rows,
            np_fetch_many=np_fetch,
            write_changes=writer,
            dry_run=False,
        )

        self.assertEqual(writer.call_count, 2)
        self.assertEqual(result.written, 1)
        self.assertTrue(any("дублюється" in error for error in result.errors))

    def test_max_rows_limits_first_safe_trial(self):
        rows = [
            {"ТТН": f"2045000000000{i}", "Служба": "НП", "Статус": "В дорозі"}
            for i in range(5)
        ]
        np_fetch = Mock(return_value={})

        result = run_status_cycle(rows, np_fetch_many=np_fetch, max_rows=2)

        self.assertEqual(result.scanned, 2)
        np_fetch.assert_called_once_with(["20450000000000", "20450000000001"])

    def test_not_found_status_is_never_planned_or_written(self):
        writer = Mock()
        result = run_status_cycle(
            [{"ТТН": "20450000000001", "Служба": "НП", "Статус": "В дорозі"}],
            np_fetch_many=lambda ttns: {
                ttns[0]: CarrierStatus(status="Номер не знайдено")
            },
            write_changes=writer,
            dry_run=False,
        )

        self.assertEqual(result.ignored_statuses, 1)
        self.assertEqual(result.planned, [])
        self.assertEqual(result.written, 0)
        writer.assert_not_called()

    def test_limit_counts_selected_service_candidates_not_unrelated_rows(self):
        rows = [
            {"ТТН": "20450000000001", "Служба": "НП", "Статус": "В дорозі"},
            {"ТТН": "20450000000002", "Служба": "НП", "Статус": "В дорозі"},
            {"ТТН": "123456789012", "Служба": "УП", "Статус": "В дорозі"},
            {"ТТН": "123456789013", "Служба": "УП", "Статус": "В дорозі"},
            {"ТТН": "123456789014", "Служба": "УП", "Статус": "В дорозі"},
        ]
        up_fetch = Mock(return_value=None)

        result = run_status_cycle(
            rows,
            up_fetch_one=up_fetch,
            services=("УП",),
            max_rows=2,
        )

        self.assertEqual(result.scanned, 4)
        self.assertEqual(result.eligible, 2)
        self.assertEqual(up_fetch.call_count, 2)
        up_fetch.assert_any_call("0123456789012")
        up_fetch.assert_any_call("0123456789013")


if __name__ == "__main__":
    unittest.main()
