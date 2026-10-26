import csv
import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/capture_pi_water_batch.py"
SPEC = importlib.util.spec_from_file_location("batch_capture", SCRIPT)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


def snapshot(timestamp, sample=5):
    return {"timestamp": timestamp.isoformat(),
            "system": {"sample": sample, "csv_path": "/home/verde/logs/sensors/session.csv"},
            "sensors": {
                "ph": {"value": 6.2, "status": "OK", "valid": True},
                "ec": {"value_mScm": 1.5, "status": "OK", "valid": True},
                "water_temperature": {"value_C": 22.0, "status": "OK"},
                "turbidity": {"value_ntu": 1.0, "status": "CALIBRATED"},
            }}


class BatchCaptureTests(unittest.TestCase):
    def test_requires_new_complete_four_sensor_acquisition(self):
        started = datetime.now(timezone.utc)
        current = started + timedelta(seconds=1)
        data = snapshot(current)
        sample_id, timestamp, values = capture.reading(data, started, current)
        self.assertEqual(sample_id, "session.csv#5")
        self.assertEqual(values, [6.2, 1.5, 22.0, 1.0])
        with self.assertRaisesRegex(ValueError, "next sensor acquisition"):
            capture.reading(snapshot(started), started, current)
        data["sensors"]["water_temperature"]["value_C"] = None
        with self.assertRaisesRegex(ValueError, "water_temperature"):
            capture.reading(data, started, current)
        data = snapshot(current)
        data["sensors"]["ec"]["retained"] = True
        with self.assertRaisesRegex(ValueError, "ec"):
            capture.reading(data, started, current)
        data = snapshot(current)
        data["sensors"]["turbidity"]["spike"] = True
        with self.assertRaisesRegex(ValueError, "turbidity"):
            capture.reading(data, started, current)

    def test_saves_unlabeled_batch_and_rejects_duplicate_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "batches.csv"
            taken = ("session.csv#5", "2026-10-26T08:00:00+08:00", [6.2, 1.5, 22.0, 1.0])
            capture.save_row(path, "solution-one", taken)
            with self.assertRaisesRegex(ValueError, "already captured"):
                capture.save_row(path, "solution-one", taken)
            capture.save_row(path, "solution-one", ("session.csv#6", taken[1], taken[2]))
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(row["water_sample_batch_id"] == "solution-one" for row in rows))
            self.assertTrue(all(row["independent_reference_label"] == "" for row in rows))


if __name__ == "__main__":
    unittest.main()
