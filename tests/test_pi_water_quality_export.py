import csv
from contextlib import closing
import importlib.util
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/export_pi_water_quality_samples.py"
SPEC = importlib.util.spec_from_file_location("water_export", SCRIPT)
water_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(water_export)


class WaterExportTests(unittest.TestCase):
    def test_only_complete_valid_spaced_rows_are_exported_without_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "real.sqlite3"
            output = Path(directory) / "unlabeled.csv"
            start = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
            with closing(sqlite3.connect(db)) as connection:
                connection.execute("CREATE TABLE sensor_samples (id INTEGER PRIMARY KEY, timestamp TEXT, ph REAL, ec REAL, water_temperature REAL, turbidity REAL)")
                rows = (
                    (1, start.isoformat(), 6.2, 1.5, 22.0, 1.0),
                    (2, (start + timedelta(minutes=5)).isoformat(), 6.3, 1.5, 22.0, 1.0),
                    (3, (start + timedelta(minutes=35)).isoformat(), 6.4, 1.5, None, 1.0),
                    (4, (start + timedelta(minutes=40)).isoformat(), 6.1, 1.4, 23.0, 1.1),
                    (5, (start + timedelta(minutes=75)).isoformat(), 18.0, 1.5, 22.0, 1.0),
                )
                connection.executemany("INSERT INTO sensor_samples VALUES (?,?,?,?,?,?)", rows)
                connection.commit()
            self.assertEqual(water_export.export(db, output), 2)
            with output.open(newline="", encoding="utf-8") as handle:
                exported = list(csv.DictReader(handle))
            self.assertEqual([item["sample_id"] for item in exported], ["1", "4"])
            self.assertEqual(exported[0]["ec_mScm"], "1.5")
            self.assertEqual(exported[0]["independent_reference_label"], "")
            self.assertEqual(exported[1]["reference_method"], "")
            with self.assertRaises(FileExistsError):
                water_export.export(db, output)


if __name__ == "__main__":
    unittest.main()
