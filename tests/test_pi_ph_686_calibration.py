import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ph_686", ROOT / "deploy/calibrate_pi_ph_686.py")
PH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PH)


class PHCalibrationTests(unittest.TestCase):
    SOURCE = ('ADS1115_GAIN = 1\nPH_SLOPE = -6.15727193\n'
              'PH_INTERCEPT = 22.99548395\n'
              'self.ph_channel = RollingAnalogChannel("ph", AnalogIn(self.ads, ADS.P1))\n')

    def sample(self, number, voltage=2.8, **overrides):
        sensor = {"status": "OK", "valid": True, "retained": False,
                  "stale": False, "spike": False,
                  "raw_voltage_V": voltage,
                  "filtered_voltage_V": voltage,
                  "value": -6.15727193 * voltage + 22.99548395}
        sensor.update(overrides)
        return {"timestamp": "2026-10-28T14:20:00+08:00",
                "system": {"sample": number, "ads1115_address": "0x48", "ads1115_gain": 1},
                "sensors": {"ph": sensor}}

    def test_single_point_shifts_only_intercept(self):
        values = PH.source_calibration(self.SOURCE)
        slope = values["PH_SLOPE"][1]
        now = datetime(2026, 10, 28, 6, 20, 10, tzinfo=timezone.utc)
        samples = [PH.validate_snapshot(self.sample(n, 2.8 + n * 0.001),
                                        slope, values["PH_INTERCEPT"][1], now)
                   for n in range(1, 6)]
        summary = PH.summarize(samples, slope)
        updated = PH.replace_intercept(self.SOURCE, values["PH_INTERCEPT"][0],
                                       summary["new_intercept"])
        self.assertIn('PH_SLOPE = -6.15727193', updated)
        self.assertAlmostEqual(slope * summary["reference_voltage_V"] +
                               PH.source_calibration(updated)["PH_INTERCEPT"][1], 6.86, places=8)
        self.assertEqual(
            self.SOURCE.replace('PH_INTERCEPT = 22.99548395',
                                f'PH_INTERCEPT = {summary["new_intercept"]:.10f}'), updated)

    def test_invalid_and_unstable_readings_are_rejected(self):
        now = datetime(2026, 10, 28, 6, 20, 10, tzinfo=timezone.utc)
        slope, intercept = -6.15727193, 22.99548395
        for altered in ({"spike": True}, {"retained": True}, {"valid": False},
                        {"filtered_voltage_V": 3.5}, {"value": 6.86}):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                PH.validate_snapshot(self.sample(1, **altered), slope, intercept, now)
        samples = [PH.validate_snapshot(self.sample(n, 2.8 + n * 0.01),
                                        slope, intercept, now) for n in range(1, 6)]
        with self.assertRaisesRegex(ValueError, "still changing"):
            PH.summarize(samples, slope)


if __name__ == "__main__":
    unittest.main()
