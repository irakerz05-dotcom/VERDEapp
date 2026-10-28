"""Live service gateway stays idle while disarmed or vision is unavailable."""

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from deploy import pi_pump_decision


def load_runtime():
    app = types.ModuleType("app")
    app.__path__ = []
    automation = types.ModuleType("app.automation")
    automation.__path__ = []
    automation.FULL = pi_pump_decision.FULL
    automation.SEMI = pi_pump_decision.SEMI
    automation.OUTPUTS = ("ph_up", "ph_down", "nutrient_dosing", "circulation_pump")
    components = types.ModuleType("app.components")
    components.Result = lambda status, detail=None: types.SimpleNamespace(
        status=status, detail=detail)
    modules = {"app": app, "app.automation": automation,
               "app.automation.pump_decision": pi_pump_decision,
               "app.components": components}
    with patch.dict(sys.modules, modules):
        path = Path(__file__).resolve().parents[1] / "deploy/pi_pump_runtime.py"
        spec = importlib.util.spec_from_file_location("test_pump_runtime", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def inputs():
    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "sensors": {
        "ph": {"value": 5.2, "status": "OK", "valid": True,
               "classification": "SUBOPTIMAL"},
        "ec": {"value_mScm": 1.4, "status": "OK", "valid": True,
               "classification": "OPTIMAL"},
        "water_temperature": {"value_C": 22, "status": "OK"},
        "turbidity": {"value_ntu": 0.3, "status": "CALIBRATED",
                      "classification": "OPTIMAL"},
    }}
    automation = {"selected_mode": pi_pump_decision.FULL,
                  "active_mode": pi_pump_decision.FULL, "override": False,
                  "override_reason": None, "hold_reason": None,
                  "circulation_stop_required": False,
                  "actuation_enabled": False, "outputs": {}}
    return automation, snapshot, types.SimpleNamespace(value="Suboptimal"), \
        types.SimpleNamespace(status="READY"), {"status": "READY"}


class RuntimeTests(unittest.TestCase):
    def test_disarmed_never_runs_circulation_or_dose(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {"armed": False}
        result = runtime.apply(*inputs())
        self.assertEqual(calls, [("status",)])
        self.assertEqual(result["active_mode"], pi_pump_decision.SEMI)
        self.assertFalse(result["actuation_enabled"])

    def test_armed_full_doses_once_after_circulation_runs(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "STOP", "in_progress": False,
                   "last_dose_elapsed_seconds": None,
                   "ml_in_last_24h": {"pump1": 0, "pump2": 0, "pump3": 0}}
        runtime.command = lambda *args: calls.append(args) or gateway
        result = runtime.apply(*inputs())
        self.assertEqual(calls[0], ("status",))
        self.assertEqual(calls[1], ("circulation", "run"))
        self.assertEqual(calls[2], ("dose", "pump2", "5.00000000"))
        self.assertTrue(result["actuation_enabled"])

    def test_vision_hold_allows_circulation_but_not_dose(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "STOP", "in_progress": False,
                   "last_dose_elapsed_seconds": None,
                   "ml_in_last_24h": {"pump1": 0, "pump2": 0, "pump3": 0}}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        automation["hold_reason"] = "plant classification unavailable"
        runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(calls, [("status",), ("circulation", "run")])

    def test_critical_keeps_circulation_and_holds_automatic_dose(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "STOP", "in_progress": False}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        automation["override"] = True
        automation["active_mode"] = pi_pump_decision.SEMI
        automation["override_reason"] = "ph Critical"
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(calls, [("status",), ("circulation", "run")])
        self.assertFalse(result["actuation_enabled"])
        self.assertEqual(result["outputs"]["circulation_pump"], "RUN (GPIO24 HIGH)")

    def test_fault_stops_circulation(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "RUN", "in_progress": False}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        automation["override"] = True
        automation["circulation_stop_required"] = True
        runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(calls, [("status",), ("safe-off",)])


if __name__ == "__main__":
    unittest.main()
