from __future__ import annotations

import unittest
from unittest.mock import patch

import config
from services import novaposhta, ukrposhta_tracking


class _Response:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class NovaPoshtaStatusSourceTests(unittest.TestCase):
    def test_tracking_statuses_are_mapped_for_worker(self):
        with patch.object(
            novaposhta,
            "_np_call",
            return_value=(
                [
                    {
                        "Number": "20450000000001",
                        "Status": "Відправлення отримано",
                        "AnnouncedPrice": "125.50",
                        "RecipientPhone": "0501234567",
                        "ClientBarcode": "12345",
                    }
                ],
                "",
            ),
        ) as api_call:
            result = novaposhta.fetch_tracking_statuses(["20450000000001"])

        status = result["20450000000001"]
        self.assertEqual(status.status, "Відправлення отримано")
        self.assertEqual(status.cost, 125.5)
        self.assertEqual(status.phone, "0501234567")
        self.assertEqual(status.invoice, "12345")
        api_call.assert_called_once_with(
            "TrackingDocument",
            "getStatusDocuments",
            {"Documents": [{"DocumentNumber": "20450000000001"}]},
        )

    def test_tracking_api_error_is_not_silently_accepted(self):
        with patch.object(
            novaposhta, "_np_call", return_value=(None, "Помилка НП")
        ):
            with self.assertRaisesRegex(RuntimeError, "Помилка НП"):
                novaposhta.fetch_tracking_statuses(["20450000000001"])


class UkrposhtaStatusSourceTests(unittest.TestCase):
    def test_ecom_status_is_used_first(self):
        response = _Response(
            {
                "lifecycle": {
                    "status": "DELIVERED",
                    "eventName": "Final delivery",
                    "date": "2026-08-27T12:30:00",
                },
                "recipient": {"phoneNumber": "0501234567"},
            }
        )
        with (
            patch.object(config, "UP_USER_TOKEN", "user-token"),
            patch.object(config, "UP_BEARER_TOKEN", "bearer-token"),
            patch.object(config, "UP_TRACKING_TOKEN", "tracking-token"),
            patch.object(ukrposhta_tracking.utils, "make_request", return_value=response) as request,
        ):
            result = ukrposhta_tracking.fetch_tracking_status("123456789012")

        self.assertEqual(result.status, "Вручено")
        self.assertEqual(result.phone, "380501234567")
        self.assertEqual(result.date, "2026-08-27T12:30:00")
        self.assertEqual(request.call_count, 1)
        self.assertIn("0123456789012", request.call_args.args[1])

    def test_tracking_api_is_fallback(self):
        tracking_response = _Response(
            [{"eventName": "Вручено", "date": "2026-08-27T13:00:00"}]
        )
        with (
            patch.object(config, "UP_USER_TOKEN", "user-token"),
            patch.object(config, "UP_TRACKING_TOKEN", "tracking-token"),
            patch.object(
                ukrposhta_tracking.utils,
                "make_request",
                side_effect=[None, tracking_response],
            ) as request,
        ):
            result = ukrposhta_tracking.fetch_tracking_status("0123456789012")

        self.assertEqual(result.status, "Вручено")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args.kwargs["params"],
            {"barcode": "0123456789012", "lang": "UA"},
        )

    def test_missing_tokens_make_no_request(self):
        with (
            patch.object(config, "UP_USER_TOKEN", ""),
            patch.object(config, "UP_TRACKING_TOKEN", ""),
            patch.object(ukrposhta_tracking.utils, "make_request") as request,
        ):
            result = ukrposhta_tracking.fetch_tracking_status("0123456789012")

        self.assertIsNone(result)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
