"""Offline tests of data-integrity safeguards, not mock market results."""

import importlib.util
import unittest
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("fetch_data", Path(__file__).resolve().parents[1] / "scripts/fetch_data.py")
fetch_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_data)


class DataIntegrityTests(unittest.TestCase):
    def test_missing_observation_is_preserved(self):
        rows = fetch_data.parse_csv(b"DATE,DGS10\n2025-01-02,4.45\n2025-01-03,.\n2025-01-06,4.50\n", "DATE", "DGS10")
        selected, quality = fetch_data.validate(rows, date(2025, 1, 1), date(2025, 1, 7), allow_nonpositive=True)
        self.assertIsNone(selected[1]["value"])
        self.assertEqual(quality["missing_rows"], 1)
        self.assertEqual(quality["filled_observations"], 0)

    def test_duplicate_dates_rejected(self):
        rows = [{"date": "2025-01-02", "value": 80}, {"date": "2025-01-02", "value": 81}]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            fetch_data.validate(rows, date(2025, 1, 1), date(2025, 1, 7))

    def test_wrong_schema_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing CSV fields"):
            fetch_data.parse_csv(b"Date,monthly_average\n2025-01-01,4.0\n", "Date", "daily_yield")

    def test_bad_ohlc_rejected(self):
        row = {"date": "2025-01-02", "value": 80, "open": 81, "high": 79, "low": 78, "close": 80}
        with self.assertRaisesRegex(ValueError, "OHLC"):
            fetch_data.validate([row], date(2025, 1, 1), date(2025, 1, 7))

    def test_negative_yield_is_not_treated_as_invalid_price(self):
        row = {"date": "2025-01-02", "value": -0.1}
        selected, _ = fetch_data.validate([row], date(2025, 1, 1), date(2025, 1, 7), allow_nonpositive=True)
        self.assertEqual(selected[0]["value"], -0.1)

    def test_nonfinite_value_rejected(self):
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            fetch_data.numeric("NaN")

    def test_period_with_no_data_is_not_success(self):
        with self.assertRaisesRegex(ValueError, "No observations"):
            fetch_data.validate([{"date": "2020-01-02", "value": 80}], date(2025, 1, 1), date(2025, 1, 7))


if __name__ == "__main__":
    unittest.main()
