"""Guard the Pi-only digital threshold patch without accessing hardware."""

import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_turbidity_gpio5 import apply, transform


SOURCE = '''from gpiozero import OutputDevice
class Service:
    def __init__(self):
        try:
            self.turbidity_channel = RollingAnalogChannel(
                "turbidity", AnalogIn(self.ads, ADS.P0)
            )
        except Exception as exc:
            self.ads_setup_error = f"{type(exc).__name__}: {exc}"
    def _acquire(self):
        turb_reading, turb_read_status = self._safe_analog(self.turbidity_channel)
        available = [
            turbidity.get("value_ntu") is not None,
        ]
    def close(self):
        try:
            pass
        finally:
            if self.dht11_device is not None:
                self.dht11_device.close()
'''


class GPIO5PatchTests(unittest.TestCase):
    def test_gpio5_patch_keeps_numeric_ntu_unavailable(self):
        updated = transform(SOURCE)
        self.assertNotIn("ADS.P0", updated)
        self.assertIn("InputDevice(5, pull_up=None, active_state=True)", updated)
        self.assertIn('"value_ntu": None', updated)
        self.assertIn('"measurement_type": "DIGITAL_THRESHOLD_ONLY"', updated)
        self.assertNotIn("threshold_triggered", updated)
        with self.assertRaisesRegex(ValueError, "already present"):
            transform(updated)

    def test_apply_preserves_original_source_as_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verde_sensor_service.py"
            path.write_text(SOURCE, encoding="utf-8")
            backup = apply(path)
            self.assertEqual(backup.read_text(encoding="utf-8"), SOURCE)
            self.assertEqual(path.read_text(encoding="utf-8"), transform(SOURCE))


if __name__ == "__main__":
    unittest.main()
