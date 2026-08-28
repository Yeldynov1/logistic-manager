from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from storage import supabase_repo


class _FakeOrdersClient:
    def __init__(self, existing: list[str]):
        self.existing = set(existing)
        self.inserted: list[dict] = []
        self.mode = ""
        self.pending = None

    def table(self, name):
        assert name == "orders"
        return self

    def select(self, _columns):
        self.mode = "select"
        return self

    def in_(self, _column, _values):
        return self

    def eq(self, _column, value):
        self.pending = value
        return self

    def limit(self, _value):
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.pending = dict(payload)
        return self

    def execute(self):
        if self.mode == "insert":
            payload = dict(self.pending)
            self.inserted.append(payload)
            self.existing.add(payload["ttn"])
            return SimpleNamespace(data=[payload])
        if self.pending and isinstance(self.pending, str):
            rows = [{"ttn": self.pending}] if self.pending in self.existing else []
            self.pending = None
            return SimpleNamespace(data=rows)
        return SimpleNamespace(data=[{"ttn": value} for value in sorted(self.existing)])


class SupabaseOrderInsertTests(unittest.TestCase):
    def test_insert_new_orders_keeps_existing_rows_and_inserts_only_missing(self):
        client = _FakeOrdersClient(["TTN-A"])
        df = pd.DataFrame(
            [
                {"ТТН": "TTN-A", "Статус": "Нове"},
                {"ТТН": "TTN-B", "Статус": "Нове"},
            ]
        )

        with patch.object(supabase_repo, "get_client", return_value=client):
            inserted, error = supabase_repo.insert_new_orders_df(df)

        self.assertEqual(error, "")
        self.assertEqual(inserted, 1)
        self.assertEqual([row["ttn"] for row in client.inserted], ["TTN-B"])
        self.assertEqual(client.existing, {"TTN-A", "TTN-B"})


if __name__ == "__main__":
    unittest.main()
