"""Guard rails for the Pi's project-relative A0 reference capture."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from deploy.calibrate_pi_turbidity_a0 import (
    SAMPLES, record_for, save_record, summarize, validate_snapshot,
)


class TurbidityReferenceTests(unittest.TestCase):
    def snapshot(self, raw=0.576, filtered=0.576, sample=1, spike=False):
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": {"sample": sample, "ads1115_address": "0x48", "ads1115_gain": 1},
            "sensors": {"turbidity": {"raw_voltage_V": raw,
                                       "filtered_voltage_V": filtered, "spike": spike}},
        }

    def test_stable_distinct_a0_samples_produce_uncertified_reference(self):
        readings = [validate_snapshot(self.snapshot(raw=0.576 + index * 0.0001,
                                                    filtered=0.576 + index * 0.0001,
                                                    sample=index + 1))
                    for index in range(SAMPLES)]
        summary = summarize(readings)
        record = record_for(readings, summary)
        self.assertAlmostEqual(record["reference_voltage_V"], 0.5762)
        self.assertEqual(record["ads_channel"], "A0")
        self.assertEqual(record["reference_provenance"], "USER_ASSIGNED_UNCERTIFIED")

    def test_unstable_duplicate_and_invalid_samples_never_make_a_reference(self):
        readings = [validate_snapshot(self.snapshot(sample=index + 1,
                                                    raw=0.576 + index * 0.01,
                                                    filtered=0.576 + index * 0.01))
                    for index in range(SAMPLES)]
        with self.assertRaisesRegex(ValueError, "unstable"):
            summarize(readings)
        readings[1]["sample"] = 1
        with self.assertRaisesRegex(ValueError, "distinct"):
            summarize(readings)
        for bad in (self.snapshot(raw=0, filtered=0), self.snapshot(spike=True)):
            with self.assertRaises(ValueError):
                validate_snapshot(bad)

    def test_save_backs_up_old_a3_record_and_rejects_a0_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "turbidity_calibration_ntu.json"
            path.write_text(json.dumps({"ads_channel": "A3", "reference_voltage_V": 1.76825}))
            record = {"ads_channel": "A0", "reference_voltage_V": 0.5762}
            backup = save_record(record, path)
            self.assertEqual(json.loads(path.read_text()), record)
            self.assertEqual(json.loads(backup.read_text())["ads_channel"], "A3")
            with self.assertRaisesRegex(ValueError, "already exists"):
                save_record(record, path)


if __name__ == "__main__":
    unittest.main()
