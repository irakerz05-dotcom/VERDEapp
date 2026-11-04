"""Safety checks for the protected pump gateway without touching GPIO."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deploy import pi_auto_pump_driver as driver


class FakeController:
    DOSING_PINS = {"pump1": 27, "pump2": 22, "pump3": 23}

    def __init__(self):
        self.dose_calls = []
        self.circulation = "RUN"

    def require_dosing_off(self):
        pass

    def dose(self, pump, seconds):
        self.dose_calls.append((pump, seconds))

    def dosing_off(self):
        pass

    def pin_state(self, pin):
        return ("24: op dh pd | hi // GPIO24 = output" if self.circulation == "RUN"
                else "24: op dl pd | lo // GPIO24 = output")

    def set_level(self, pin, level):
        assert pin == 24
        self.circulation = "RUN" if level == "dh" else "STOP"


class GatewayTests(unittest.TestCase):
    def test_auto_resume_requires_a_protected_prior_flow_record(self):
        record = Mock()
        record.stat.return_value = SimpleNamespace(st_uid=0, st_mode=0o600)
        with patch.object(driver, "ARM_PATH", record):
            record.read_text.return_value = driver.manual_flow_record()
            self.assertEqual(driver.arm_mode(), "manual")
            self.assertTrue(driver.auto_resume_available())
            record.read_text.return_value = driver.MANUAL_ARM_RECORD
            self.assertFalse(driver.auto_resume_available())
            record.read_text.return_value = driver.manual_flow_record()
            record.stat.return_value = SimpleNamespace(st_uid=1000, st_mode=0o600)
            self.assertFalse(driver.auto_resume_available())

    def test_flow_resume_requires_prior_proof_and_no_interrupted_dose(self):
        controller = FakeController()
        controller.circulation = "STOP"
        record = Mock()
        with (patch.object(driver, "auto_resume_available", return_value=False),
              patch.object(driver, "ARM_PATH", record)):
            with self.assertRaisesRegex(RuntimeError, "prior supervised flow"):
                driver.resume_flow(controller, {"in_progress": False})
        self.assertEqual(controller.circulation, "STOP")
        with (patch.object(driver, "auto_resume_available", return_value=True),
              patch.object(driver, "ARM_PATH", record),
              patch.object(driver.os, "chmod"),
              patch.object(driver, "status", return_value={"circulation": "RUN"})):
            with self.assertRaisesRegex(RuntimeError, "Interrupted dose"):
                driver.resume_flow(controller, {"in_progress": True})
            self.assertEqual(controller.circulation, "STOP")
            result = driver.resume_flow(controller, {"in_progress": False})
            self.assertEqual(result["circulation"], "RUN")
            self.assertEqual(controller.circulation, "RUN")
            record.write_text.assert_called_once_with(driver.ARM_RECORD, encoding="utf-8")

    def test_prior_flow_proof_must_be_from_current_boot(self):
        record = Mock()
        with (patch.object(driver, "ARM_PATH", record),
              patch.object(driver, "arm_mode", return_value="flow"),
              patch.object(driver.time, "time", return_value=1000),
              patch.object(driver.time, "monotonic", return_value=200)):
            record.stat.return_value = SimpleNamespace(st_mtime=900)
            self.assertTrue(driver.flow_arm_current_boot())
            record.stat.return_value = SimpleNamespace(st_mtime=700)
            self.assertFalse(driver.flow_arm_current_boot())

    def test_corrected_reservoir_caps_the_pulse_and_requires_new_arm_record(self):
        self.assertEqual(driver.ARM_RECORD, "GPIO24 HIGH=FLOW LOW=STOP; 18L\n")
        self.assertEqual(driver.PUMPS, ("pump1", "pump2", "pump3"))
        controller = FakeController()
        with patch.object(driver, "arm_mode", return_value="flow"):
            with self.assertRaisesRegex(RuntimeError, "4.5 seconds"):
                driver.dose(controller, {"events": [], "in_progress": False},
                            1000.0, "pump2", 5.0)
        self.assertEqual(controller.dose_calls, [])

    def test_disarmed_gateway_never_doses(self):
        controller = FakeController()
        with patch.object(driver, "arm_mode", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "not armed"):
                driver.dose(controller, {"events": [], "in_progress": False},
                            1000.0, "pump1", 3.125)
        self.assertEqual(controller.dose_calls, [])

    def test_ledger_and_cooldown_without_daily_limit(self):
        controller = FakeController()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with (patch.object(driver, "STATE_PATH", state_path),
                  patch.object(driver, "arm_mode", return_value="flow"),
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
                driver.dose(controller, saved, 1200.0, "pump1", 4.5)
                self.assertEqual(controller.dose_calls, [("pump1", 4.5), ("pump1", 4.5)])
                self.assertIsNone(driver.status(controller, saved, 1200.0)["limits_ml_in_24h"])

    def test_interrupted_ledger_blocks_redose(self):
        controller = FakeController()
        state = {"version": 1, "events": [{"pump": "pump2", "at": 1000.0,
                                             "ml": 4.1}], "in_progress": True}
        with patch.object(driver, "arm_mode", return_value="flow"):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                driver.dose(controller, state, 1200.0, "pump2", 2.0)
        self.assertEqual(controller.dose_calls, [])

    def test_manual_dose_requires_manual_arm_and_stopped_circulation(self):
        controller = FakeController()
        controller.circulation = "STOP"
        state = {"version": 1, "events": [], "in_progress": False}
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(driver, "STATE_PATH", Path(directory) / "state.json"),
                  patch.object(driver, "arm_mode", return_value="manual"),
                  patch.object(driver.time, "time", return_value=1070.0)):
                result = driver.dose(controller, state, 1000.0, "pump3", 4.5, manual=True)
                self.assertAlmostEqual(result["estimated_ml"], 3.69)
                self.assertEqual(controller.dose_calls, [("pump3", 4.5)])
                with self.assertRaisesRegex(RuntimeError, "not armed"):
                    driver.dose(controller, state, 1100.0, "pump3", 4.5)
                controller.circulation = "RUN"
                with self.assertRaisesRegex(RuntimeError, "must be STOP"):
                    driver.dose(controller, state, 1100.0, "pump3", 4.5, manual=True)


if __name__ == "__main__":
    unittest.main()
