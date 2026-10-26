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
        self.assertAlmostEqual(record["voltage_divider"]["adc_fraction_of_sensor_output"], 2 / 3)
        self.assertAlmostEqual(record["reference_sensor_output_estimate_V"], 0.5762 * 1.5)

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

    def test_explicit_a0_replacement_preserves_old_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "turbidity_calibration_ntu.json"
            old = {"ads_channel": "A0", "reference_voltage_V": 0.575875}
            new = {"ads_channel": "A0", "reference_voltage_V": 0.8125}
            path.write_text(json.dumps(old))
            backup = save_record(new, path, replace_existing=True)
            self.assertEqual(json.loads(path.read_text()), new)
            self.assertEqual(json.loads(backup.read_text()), old)

    def test_new_a3_record_replaces_a0_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "turbidity_calibration_ntu.json"
            old = {"ads_channel": "A0", "reference_voltage_V": 0.575875}
            path.write_text(json.dumps(old))
            readings = [validate_snapshot(self.snapshot(sample=index + 1), channel="A3")
                        for index in range(SAMPLES)]
            new = record_for(readings, summarize(readings), channel="A3")
            backup = save_record(new, path)
            self.assertEqual(json.loads(path.read_text())["ads_channel"], "A3")
            self.assertEqual(json.loads(backup.read_text()), old)

    def test_a3_near_supply_capture_has_strict_upper_bound(self):
        reading = validate_snapshot(self.snapshot(raw=3.282875, filtered=3.282875),
                                    channel="A3")
        self.assertAlmostEqual(reading["raw_voltage_V"], 3.282875)
        for voltage in (3.29, 3.3, 3.6705):
            with self.assertRaisesRegex(ValueError, "guarded capture range"):
                validate_snapshot(self.snapshot(raw=voltage, filtered=voltage),
                                  channel="A3")


if __name__ == "__main__":
    unittest.main()
