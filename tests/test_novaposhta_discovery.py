from __future__ import annotations

import unittest
from unittest.mock import patch

from services import novaposhta


class NovaPoshtaDiscoveryTests(unittest.TestCase):
    def test_outgoing_rows_survive_incoming_api_error(self):
        outgoing = [{"IntDocNumber": "20400000000001"}]
        with patch.object(
            novaposhta,
            "_np_call",
            side_effect=[(outgoing, ""), (None, "temporary incoming error")],
        ):
            out_rows, in_rows, errors = novaposhta.fetch_account_documents(
                "01.08.2026",
                "28.08.2026",
            )

        self.assertEqual(out_rows, outgoing)
        self.assertEqual(in_rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("вхідні", errors[0])

    def test_invalid_items_are_ignored_without_losing_valid_rows(self):
        with patch.object(
            novaposhta,
            "_np_call",
            side_effect=[([None, {"IntDocNumber": "1"}], ""), ({"bad": True}, "")],
        ):
            out_rows, in_rows, errors = novaposhta.fetch_account_documents("a", "b")

        self.assertEqual(out_rows, [{"IntDocNumber": "1"}])
        self.assertEqual(in_rows, [])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
