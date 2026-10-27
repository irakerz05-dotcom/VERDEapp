"""Guard and behavior checks for the Pi's water-only last-good metadata."""

import unittest

from deploy.apply_pi_water_recovery_last_good import (
    SENSOR_MARKER, patch_sensor,
)


class WaterLastGoodPatchTests(unittest.TestCase):
    def test_water_only_metadata_follows_success_and_transient_failure(self):
        source = '''# VERDE-SENSOR-RECOVERY-v3
class Reader:
    def __init__(self):
        self.water = []
        self.humidity = []
    def _read_water_temperature(self):
        return self.water.pop(0)
    def _read_humidity(self):
        return self.humidity.pop(0)
    def _safe_analog(self, channel):
        pass
'''
        updated = patch_sensor(source)
        namespace = {}
        exec(updated, namespace)
        reader = namespace["Reader"]()
        reader.water = [
            {"value_C": 23.5, "status": "OK", "read_error": None,
             "read_timestamp": "2026-10-27T14:00:00+08:00"},
            {"value_C": None, "status": "RECOVERING: CRC failure",
             "read_error": "CRC failure"},
            {"value_C": None, "status": "ERROR: disconnected",
             "read_error": "disconnected"},
        ]
        self.assertEqual(reader._read_water_temperature()["value_C"], 23.5)
        retry = reader._read_water_temperature()
        self.assertIsNone(retry["value_C"])
        self.assertEqual(retry["last_valid_value_C"], 23.5)
        self.assertEqual(retry["last_valid_measured_at"], "2026-10-27T14:00:00+08:00")
        self.assertNotIn("last_valid_value_C", reader._read_water_temperature())
        self.assertEqual(patch_sensor(updated), updated)

    def test_guard_rejects_unrecognized_sensor_owner(self):
        with self.assertRaisesRegex(ValueError, "Expected installed Pi water retry methods"):
            patch_sensor("class Reader: pass\n")


if __name__ == "__main__":
    unittest.main()
