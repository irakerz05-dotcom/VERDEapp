"""Safety checks for the protected pump gateway without touching GPIO."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import pi_auto_pump_driver as driver


class FakeController:
    def __init__(self):
        self.dose_calls = []

    def require_dosing_off(self):
        pass

    def dose(self, pump, seconds):
        self.dose_calls.append((pump, seconds))

    def dosing_off(self):
        pass

    def pin_state(self, pin):
        return "24: op dh pd | hi // GPIO24 = output"


class GatewayTests(unittest.TestCase):
    def test_corrected_reservoir_caps_the_pulse_and_requires_new_arm_record(self):
        self.assertEqual(driver.ARM_RECORD, "GPIO24 HIGH=FLOW LOW=STOP; 18L\n")
        self.assertEqual(driver.LIMITS_ML,
                         {"pump1": 9.0, "pump2": 5.274, "pump3": 3.69})
        controller = FakeController()
        with patch.object(driver, "armed", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "4.5 seconds"):
                driver.dose(controller, {"events": [], "in_progress": False},
                            1000.0, "pump2", 5.0)
        self.assertEqual(controller.dose_calls, [])

    def test_disarmed_gateway_never_doses(self):
        controller = FakeController()
        with patch.object(driver, "armed", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "disarmed"):
                driver.dose(controller, {"events": [], "in_progress": False},
                            1000.0, "pump1", 3.125)
        self.assertEqual(controller.dose_calls, [])

    def test_persistent_budget_and_cooldown(self):
        controller = FakeController()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (patch.object(driver, "STATE_PATH", state_path),
                  patch.object(driver, "armed", return_value=True),
                  patch.object(driver.time, "time", return_value=1070.0)):
                state = {"version": 1, "events": [], "in_progress": False}
                result = driver.dose(controller, state, 1000.0, "pump1", 4.5)
                self.assertAlmostEqual(result["estimated_ml"], 3.69)
                self.assertEqual(controller.dose_calls, [("pump1", 4.5)])
                saved = json.loads(state_path.read_text())
                self.assertFalse(saved["in_progress"])
                self.assertAlmostEqual(driver.totals(saved)["pump1"], 3.69)
                with self.assertRaisesRegex(RuntimeError, "mixing wait"):
                    driver.dose(controller, saved, 1100.0, "pump1", 4.5)
                saved["events"][0]["ml"] = 7.0
                with self.assertRaisesRegex(RuntimeError, "volume limit"):
                    driver.dose(controller, saved, 1200.0, "pump1", 4.5)
                self.assertEqual(controller.dose_calls, [("pump1", 4.5)])

    def test_interrupted_ledger_blocks_redose(self):
        controller = FakeController()
        state = {"version": 1, "events": [{"pump": "pump2", "at": 1000.0,
                                             "ml": 4.1}], "in_progress": True}
        with patch.object(driver, "armed", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                driver.dose(controller, state, 1200.0, "pump2", 2.0)
        self.assertEqual(controller.dose_calls, [])


if __name__ == "__main__":
    unittest.main()
