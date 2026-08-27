from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock
from unittest.mock import patch

from scripts import status_dry_run
from services.status_worker import CarrierStatus


class StatusDryRunCommandTests(unittest.TestCase):
    def test_transient_google_error_is_retried_then_succeeds(self):
        sheet = Mock()
        sheet.get_all_records.side_effect = [
            RuntimeError("APIError: [503]: service unavailable"),
            [{"ТТН": "20450000000003"}],
        ]
        client = Mock()
        client.open.return_value.sheet1 = sheet
        sleep = Mock()

        rows = status_dry_run._read_google_rows(
            client,
            "Orders",
            attempts=3,
            sleep_fn=sleep,
        )

        self.assertEqual(rows, [{"ТТН": "20450000000003"}])
        self.assertEqual(client.open.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_non_transient_google_error_is_not_retried(self):
        client = Mock()
        client.open.side_effect = RuntimeError("APIError: [403]: forbidden")
        sleep = Mock()

        with self.assertRaisesRegex(RuntimeError, "403"):
            status_dry_run._read_google_rows(
                client,
                "Orders",
                attempts=3,
                sleep_fn=sleep,
            )

        client.open.assert_called_once_with("Orders")
        sleep.assert_not_called()

    def test_environment_credentials_load_orders_read_only(self):
        sheet = Mock()
        sheet.get_all_records.return_value = [{"ТТН": "20450000000001"}]
        client = Mock()
        client.open.return_value.sheet1 = sheet

        with (
            patch.dict(
                os.environ,
                {
                    "GCP_SERVICE_ACCOUNT_JSON": '{"type":"service_account"}',
                    "ORDERS_SPREADSHEET_NAME": "Orders-Test",
                },
                clear=False,
            ),
            patch("gspread.service_account_from_dict", return_value=client) as connect,
        ):
            rows = status_dry_run._load_rows()

        self.assertEqual(rows, [{"ТТН": "20450000000001"}])
        connect.assert_called_once_with({"type": "service_account"})
        client.open.assert_called_once_with("Orders-Test")
        sheet.get_all_records.assert_called_once_with()
        self.assertFalse(sheet.method_calls[-1][0].startswith("update"))

    def test_streamlit_toml_credentials_load_orders_read_only(self):
        sheet = Mock()
        sheet.get_all_records.return_value = [{"ТТН": "20450000000002"}]
        client = Mock()
        client.open.return_value.sheet1 = sheet
        credentials_toml = """
[gcp_service_account]
type = "service_account"
project_id = "test-project"
private_key = "test-key"
client_email = "worker@example.test"
"""

        with (
            patch.dict(
                os.environ,
                {
                    "GCP_SERVICE_ACCOUNT_TOML": credentials_toml,
                    "ORDERS_SPREADSHEET_NAME": "Orders-Test",
                },
                clear=True,
            ),
            patch("gspread.service_account_from_dict", return_value=client) as connect,
        ):
            rows = status_dry_run._load_rows()

        self.assertEqual(rows, [{"ТТН": "20450000000002"}])
        connect.assert_called_once_with(
            {
                "type": "service_account",
                "project_id": "test-project",
                "private_key": "test-key",
                "client_email": "worker@example.test",
            }
        )
        client.open.assert_called_once_with("Orders-Test")
        sheet.get_all_records.assert_called_once_with()
        self.assertFalse(sheet.method_calls[-1][0].startswith("update"))

    def test_command_reads_only_limited_rows_and_reports_plan(self):
        rows = [
            {"ТТН": "20450000000001", "Служба": "НП", "Статус": "В дорозі"},
            {"ТТН": "20450000000002", "Служба": "НП", "Статус": "В дорозі"},
            {"ТТН": "20450000000003", "Служба": "НП", "Статус": "В дорозі"},
        ]
        np_fetch = Mock(
            return_value={
                "20450000000001": CarrierStatus(status="У відділенні"),
                "20450000000002": CarrierStatus(status="Відправлення отримано"),
            }
        )
        output = io.StringIO()

        with redirect_stdout(output):
            code = status_dry_run.main(
                ["--limit", "2", "--service", "np"],
                load_rows=lambda: rows,
                np_fetch_many=np_fetch,
                up_fetch_one=Mock(),
            )

        self.assertEqual(code, 0)
        np_fetch.assert_called_once_with(["20450000000001", "20450000000002"])
        text = output.getvalue()
        self.assertIn("DRY-RUN", text)
        self.assertIn("пропозицій: 2", text)
        self.assertNotIn("20450000000001", text)
        self.assertIn("…000001", text)

    def test_invalid_limit_stops_before_loading_rows(self):
        load_rows = Mock()
        output = io.StringIO()

        with redirect_stdout(output):
            code = status_dry_run.main(["--limit", "0"], load_rows=load_rows)

        self.assertEqual(code, 2)
        load_rows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
