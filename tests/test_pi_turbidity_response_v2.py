"""Verify the guarded transition to the stronger project turbidity response."""

import json
import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_turbidity_response import transform_record as v1_record
from deploy.apply_pi_turbidity_response import transform_source as v1_source
from deploy.apply_pi_turbidity_response_v2 import preflight, transform_record, transform_source
from tests.test_pi_turbidity_response import SOURCE


class TurbidityResponseV2Tests(unittest.TestCase):
    def setUp(self):
        self.source = v1_source(SOURCE)
        self.record = v1_record({
            "ads_channel": "A0", "calibration_status": "CALIBRATED",
            "reference_ntu": 1.0, "reference_voltage_V": 1.776375,
            "reference_provenance": "USER_ASSIGNED_UNCERTIFIED",
        })

    def test_clear_reference_and_milk_sample_bands(self):
        updated = transform_source(self.source)
        scope = {}
        exec(updated, scope)
        convert = scope["calculate_turbidity_ntu"]
        classify = scope["classify_turbidity"]
        self.assertAlmostEqual(convert(1.776375, 1.776375), 0.3)
        milk = convert(1.776375, 0.279)
        self.assertGreater(milk, 20)
        self.assertEqual(classify(milk), "CRITICAL")
        self.assertIsNone(convert(1.776375, 0))
        with self.assertRaises(ValueError):
            transform_source(updated)

    def test_migration_preserves_drinking_water_voltage(self):
        updated = transform_record(self.record)
        self.assertEqual(updated["reference_voltage_V"], self.record["reference_voltage_V"])
        self.assertEqual(updated["reference_ntu"], 0.3)
        self.assertEqual(updated["conversion_version"], "PROJECT_RELATIVE_POWER_2_4_V2")
        self.assertEqual(self.record["conversion_version"], "PROJECT_RELATIVE_SQUARED_V1")
        with self.assertRaises(ValueError):
            transform_record(updated)

    def test_configured_critical_limit_blocks_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, record, config = (root / name for name in ("service.py", "record.json", "config.json"))
            source.write_text(self.source, encoding="utf-8")
            record.write_text(json.dumps(self.record), encoding="utf-8")
            config.write_text(json.dumps({"limits": {"turbidity_critical": 20}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safety limit"):
                preflight(source, record, config)


if __name__ == "__main__":
    unittest.main()
