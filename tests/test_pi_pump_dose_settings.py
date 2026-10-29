import json
import tempfile
import unittest
from pathlib import Path

from deploy import pi_pump_dose_settings as settings


class DoseSettingsTests(unittest.TestCase):
    def test_round_trip_and_bounded_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pump_dose_settings.json"
            self.assertEqual(settings.load(path), settings.DEFAULT_ML)
            volumes = {"pump1": 1.0, "pump2": 2.0, "pump3": 3.69}
            self.assertEqual(settings.save(volumes, path), volumes)
            self.assertEqual(settings.load(path), volumes)
            self.assertAlmostEqual(settings.durations(volumes)["pump3"], 4.5)
            self.assertEqual(json.loads(path.read_text())["version"], 1)

    def test_invalid_or_excessive_request_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pump_dose_settings.json"
            settings.save(settings.DEFAULT_ML, path)
            original = path.read_bytes()
            for bad in ({"pump1": 4.0, "pump2": 1, "pump3": 1},
                        {"pump1": 0, "pump2": 1, "pump3": 1},
                        {"pump1": True, "pump2": 1, "pump3": 1},
                        {"pump1": 1, "pump2": 1},
                        {"pump1": float("nan"), "pump2": 1, "pump3": 1}):
                with self.assertRaises(ValueError):
                    settings.save(bad, path)
                self.assertEqual(path.read_bytes(), original)

    def test_corrupt_saved_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pump_dose_settings.json"
            path.write_text('{"version":1,"volumes_ml":{"pump1":9}}')
            with self.assertRaises(ValueError):
                settings.load(path)


if __name__ == "__main__":
    unittest.main()
