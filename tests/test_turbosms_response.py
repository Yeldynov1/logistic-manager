from __future__ import annotations

import unittest
from unittest.mock import patch

import utils


class _TurboSmsResponse:
    status_code = 200
    text = ""

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class TurboSmsResponseTests(unittest.TestCase):
    def test_send_keeps_token_out_of_url_parameters(self):
        response = _TurboSmsResponse(
            {
                "response_code": 800,
                "response_status": "SUCCESS_MESSAGE_ACCEPTED",
                "response_result": None,
            }
        )

        with (
            patch("config.TURBOSMS_TOKEN", "test-secret-token"),
            patch("config.TURBOSMS_SENDER", "TestSender"),
            patch.object(utils, "make_request", return_value=response) as request,
        ):
            ok, message_id, error = utils.turbosms_send(
                "+380501234567", "Тестове повідомлення"
            )

        self.assertTrue(ok)
        self.assertIsNone(message_id)
        self.assertEqual(error, "")
        request.assert_called_once()
        method, url = request.call_args.args
        request_kwargs = request.call_args.kwargs
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.turbosms.ua/message/send.json")
        self.assertNotIn("params", request_kwargs)
        self.assertNotIn("test-secret-token", url)
        self.assertTrue(request_kwargs["_single_attempt"])
        self.assertEqual(
            request_kwargs["headers"]["Authorization"],
            "Bearer test-secret-token",
        )
        sequence_id = request_kwargs["json"]["sequence_id"]
        self.assertEqual(len(sequence_id), 40)
        self.assertEqual(
            sequence_id,
            utils._turbosms_sequence_id(
                "380501234567", "Тестове повідомлення", ""
            ),
        )

    def test_sequence_id_is_stable_and_changes_with_order(self):
        first = utils._turbosms_sequence_id(
            "380501234567", "Ваш чек", "20450000000001"
        )
        repeated = utils._turbosms_sequence_id(
            "380501234567", "Ваш чек", "20450000000001"
        )
        other_order = utils._turbosms_sequence_id(
            "380501234567", "Ваш чек", "20450000000002"
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other_order)
        self.assertEqual(len(first), 40)

    def test_single_attempt_does_not_fall_back_to_second_post(self):
        with (
            patch.object(utils, "HAS_CURL", True),
            patch.object(utils, "curl_requests") as curl,
            patch.object(utils.std_requests, "request") as standard_request,
            patch.object(utils, "_urllib_request") as urllib_request,
        ):
            curl.request.side_effect = TimeoutError("simulated timeout")
            response = utils._make_request_once(
                "POST",
                "https://api.turbosms.ua/message/send.json",
                json={"sequence_id": "test"},
                _single_attempt=True,
            )

        self.assertIsNone(response)
        curl.request.assert_called_once()
        standard_request.assert_not_called()
        urllib_request.assert_not_called()

    def test_empty_values_are_not_success(self):
        self.assertFalse(utils._turbosms_response_ok(None, ""))
        self.assertFalse(utils._turbosms_response_ok("", ""))
        self.assertFalse(utils._turbosms_response_ok(False, ""))

    def test_explicit_acceptance_values_are_success(self):
        self.assertTrue(utils._turbosms_response_ok(0, ""))
        self.assertTrue(utils._turbosms_response_ok(None, "OK"))
        self.assertTrue(utils._turbosms_response_ok(800, ""))
        self.assertTrue(utils._turbosms_response_ok(None, "SUCCESS_MESSAGE_SENT"))

    def test_contradictory_code_and_status_are_not_success(self):
        self.assertFalse(utils._turbosms_response_ok(999, "OK"))
        self.assertFalse(utils._turbosms_response_ok(800, "FATAL_ERROR"))

        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 999,
                "response_status": "OK",
                "response_result": [
                    {
                        "response_code": 0,
                        "response_status": "OK",
                        "message_id": "sms-should-not-be-used",
                    }
                ],
            }
        )

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("999", error)

    def test_partial_top_level_result_is_not_enough(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 802,
                "response_status": "SUCCESS_MESSAGE_PARTIAL_ACCEPTED",
                "response_result": [
                    {
                        "response_code": 406,
                        "response_status": "NOT_ALLOWED_RECIPIENT_COUNTRY",
                        "message_id": None,
                    }
                ],
            }
        )

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("NOT_ALLOWED_RECIPIENT_COUNTRY", error)

    def test_duplicate_response_uses_previous_success_without_resending(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 507,
                "response_status": "FAILED_DUPLICATE_REQUEST",
                "response_result": [
                    {
                        "response_code": 0,
                        "response_status": "OK",
                        "message_id": "previous-sms-123",
                    }
                ],
            }
        )

        self.assertTrue(ok)
        self.assertEqual(message_id, "previous-sms-123")
        self.assertEqual(error, "")

    def test_duplicate_without_previous_result_is_rejected(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 507,
                "response_status": "FAILED_DUPLICATE_REQUEST",
                "response_result": None,
            }
        )

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("не підтвердив", error)

    def test_recipient_message_id_confirms_acceptance(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 802,
                "response_status": "SUCCESS_MESSAGE_PARTIAL_ACCEPTED",
                "response_result": [
                    {
                        "response_code": 0,
                        "response_status": "OK",
                        "message_id": "sms-123",
                    }
                ],
            }
        )

        self.assertTrue(ok)
        self.assertEqual(message_id, "sms-123")
        self.assertEqual(error, "")

    def test_empty_response_is_rejected(self):
        ok, message_id, error = utils._parse_turbosms_send_response({})

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("порожню", error)

    def test_recipient_without_message_id_is_rejected(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 800,
                "response_status": "SUCCESS_MESSAGE_ACCEPTED",
                "response_result": [{"response_code": 0, "response_status": "OK"}],
            }
        )

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("ідентифікатор", error)

    def test_full_top_level_acceptance_without_details_is_accepted(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 800,
                "response_status": "SUCCESS_MESSAGE_ACCEPTED",
                "response_result": None,
            }
        )

        self.assertTrue(ok)
        self.assertIsNone(message_id)
        self.assertEqual(error, "")

    def test_general_ok_without_recipient_result_is_rejected(self):
        ok, message_id, error = utils._parse_turbosms_send_response(
            {
                "response_code": 0,
                "response_status": "OK",
                "response_result": None,
            }
        )

        self.assertFalse(ok)
        self.assertIsNone(message_id)
        self.assertIn("не підтвердив", error)


if __name__ == "__main__":
    unittest.main()
