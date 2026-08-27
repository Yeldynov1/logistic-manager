from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.ukrposhta_tracking import _request_timeout_seconds


class UkrposhtaTrackingTests(unittest.TestCase):
    def test_background_timeout_can_be_shortened_but_not_below_five_seconds(self):
        with patch.dict(
            os.environ,
            {"UP_TRACKING_REQUEST_TIMEOUT_SECONDS": "15"},
            clear=False,
        ):
            self.assertEqual(_request_timeout_seconds(), 15.0)

        with patch.dict(
            os.environ,
            {"UP_TRACKING_REQUEST_TIMEOUT_SECONDS": "1"},
            clear=False,
        ):
            self.assertEqual(_request_timeout_seconds(), 5.0)

    def test_manual_default_keeps_existing_timeout(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_request_timeout_seconds(), 45.0)


if __name__ == "__main__":
    unittest.main()
