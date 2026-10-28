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
    def test_disarmed_gateway_never_doses(self):
        controller = FakeController()
        with patch.object(driver, "armed", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "disarmed"):
                driver.dose(controller, {"events": [], "in_progress": False},
                            1000.0, "pump1", 5.0)
        self.assertEqual(controller.dose_calls, [])

    def test_persistent_budget_and_cooldown(self):
        controller = FakeController()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (patch.object(driver, "STATE_PATH", state_path),
                  patch.object(driver, "armed", return_value=True),
                  patch.object(driver.time, "time", return_value=1070.0)):
                state = {"version": 1, "events": [], "in_progress": False}
                result = driver.dose(controller, state, 1000.0, "pump1", 5.0)
                self.assertEqual(result["estimated_ml"], 4.1)
                self.assertEqual(controller.dose_calls, [("pump1", 5.0)])
                saved = json.loads(state_path.read_text())
                self.assertFalse(saved["in_progress"])
                self.assertEqual(driver.totals(saved)["pump1"], 4.1)
                with self.assertRaisesRegex(RuntimeError, "mixing wait"):
                    driver.dose(controller, saved, 1100.0, "pump1", 5.0)
                saved["events"][0]["ml"] = 9.0
                with self.assertRaisesRegex(RuntimeError, "volume limit"):
                    driver.dose(controller, saved, 1200.0, "pump1", 5.0)
                self.assertEqual(controller.dose_calls, [("pump1", 5.0)])

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
