"""Guarded water-temperature correction and reader behavior."""

import unittest
from collections import Counter
from types import SimpleNamespace

from deploy.apply_pi_sensor_recovery import REPLACEMENTS
from deploy.apply_pi_water_temperature_offset import OLD, NEW, plan


class WaterTemperatureOffsetTests(unittest.TestCase):
    def test_guarded_patch_and_reapply(self):
        methods = next(new for label, _, new in REPLACEMENTS if label == "retry methods")
        source = "# VERDE-SENSOR-RECOVERY-v3\nclass Reader:\n" + methods + "        pass\n"
        updated, changed = plan(source)
        self.assertTrue(changed)
        self.assertIn('value = raw_value - 0.7', updated)
        self.assertEqual(plan(updated), (updated, False))
        with self.assertRaisesRegex(ValueError, "differs"):
            plan("class Reader:\n    pass\n")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            plan(updated.replace('"raw_value_C": raw_value, ', ""))

    def test_corrected_value_drives_classification_and_raw_is_preserved(self):
        methods = next(new for label, _, new in REPLACEMENTS if label == "retry methods")
        self.assertEqual(methods.count(OLD), 1)
        namespace = {
            "log": SimpleNamespace(info=lambda *args: None),
            "timestamp_now": lambda: "2026-11-12T15:00:00+08:00",
            "discover_ds18b20": lambda: SimpleNamespace(name="28-test"),
            "read_ds18b20": lambda _device, raw: 24.5,
            "classify_water_temperature": lambda value: "OPTIMAL" if value <= 24 else "SUBOPTIMAL",
        }
        exec("class Reader:\n" + methods.replace(OLD, NEW) + "        pass\n", namespace)
        reader = namespace["Reader"]()
        reader.ds18b20_failures = 0
        reader.error_counts = Counter()
        reading = reader._read_water_temperature()
        self.assertAlmostEqual(reading["value_C"], 23.8)
        self.assertEqual(reading["raw_value_C"], 24.5)
        self.assertEqual(reading["classification"], "OPTIMAL")
        self.assertIn("software offset -0.7 C", reading["status"])


if __name__ == "__main__":
    unittest.main()
