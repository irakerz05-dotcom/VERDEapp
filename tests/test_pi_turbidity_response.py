"""Check the guarded project display conversion and record migration."""

import json
import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_turbidity_response import preflight, transform_record, transform_source


SOURCE = '''import math
TURBIDITY_REFERENCE_NTU = 1.0
def classify_turbidity(value_ntu):
    if value_ntu < 5.0:
        return "OPTIMAL"
    if value_ntu <= 20.0:
        return "SUBOPTIMAL"
    return "CRITICAL"
def load():
    record = {"ads_channel": "A0"}
    if record.get("ads_channel") != "A0":
        raise ValueError("turbidity calibration is not for ADS1115 A0")
    if float(record.get("reference_ntu", 0)) != TURBIDITY_REFERENCE_NTU:
        raise ValueError("reference NTU must be exactly 1.00")
def calculate_turbidity_ntu(reference_voltage, measured_voltage):
    values = (reference_voltage, measured_voltage)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value == 0 for value in values):
        return None
    return TURBIDITY_REFERENCE_NTU * abs(reference_voltage) / abs(measured_voltage)
'''


class TurbidityResponseTests(unittest.TestCase):
    def test_reference_and_opaque_response(self):
        source = transform_source(SOURCE)
        scope = {}
        exec(source, scope)
        convert = scope["calculate_turbidity_ntu"]
        self.assertAlmostEqual(convert(1.776375, 1.776375), 0.3)
        self.assertGreater(convert(1.776375, 1.776375 / 8.3), 20)
        self.assertIsNone(convert(1.776375, 0))
        self.assertEqual(scope["classify_turbidity"](5.0), "SUBOPTIMAL")
        self.assertEqual(scope["classify_turbidity"](20.0), "CRITICAL")
        with self.assertRaises(ValueError):
            transform_source(source)

    def test_record_migration_requires_uncertified_a0_reference(self):
        record = {"ads_channel": "A0", "calibration_status": "CALIBRATED",
                  "reference_ntu": 1.0, "reference_voltage_V": 1.776375,
                  "reference_provenance": "USER_ASSIGNED_UNCERTIFIED"}
        updated = transform_record(record)
        self.assertEqual(updated["reference_ntu"], 0.3)
        self.assertEqual(updated["conversion_version"], "PROJECT_RELATIVE_SQUARED_V1")
        self.assertEqual(record["reference_ntu"], 1.0)
        with self.assertRaises(ValueError):
            transform_record(updated)

    def test_configured_critical_limit_blocks_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, record, config = (root / name for name in ("service.py", "record.json", "config.json"))
            source.write_text(SOURCE, encoding="utf-8")
            record.write_text(json.dumps({"ads_channel": "A0", "calibration_status": "CALIBRATED",
                                          "reference_ntu": 1.0, "reference_voltage_V": 1.776375,
                                          "reference_provenance": "USER_ASSIGNED_UNCERTIFIED"}))
            config.write_text(json.dumps({"limits": {"turbidity_critical": 20}}))
            with self.assertRaisesRegex(ValueError, "safety/SMS"):
                preflight(source, record, config)


if __name__ == "__main__":
    unittest.main()
