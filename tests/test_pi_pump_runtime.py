"""Live service gateway stays idle while disarmed or vision is unavailable."""

import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from deploy import pi_pump_decision, pi_pump_dose_settings


def load_runtime():
    app = types.ModuleType("app")
    app.__path__ = []
    automation = types.ModuleType("app.automation")
    automation.__path__ = []
    automation.FULL = pi_pump_decision.FULL
    automation.SEMI = pi_pump_decision.SEMI
    automation.OUTPUTS = ("ph_up", "ph_down", "nutrient_dosing", "circulation_pump")
    components = types.ModuleType("app.components")
    components.Result = lambda status, value=None, detail=None: types.SimpleNamespace(
        status=status, value=value, detail=detail)
    modules = {"app": app, "app.automation": automation,
               "app.automation.pump_decision": pi_pump_decision,
               "app.automation.pump_dose_settings": pi_pump_dose_settings,
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
        self.assertEqual(result["selected_mode"], pi_pump_decision.FULL)
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
        self.assertEqual(calls[2], ("dose", "pump2", "4.50000000"))
        self.assertTrue(result["actuation_enabled"])
        self.assertEqual(result["dose_event"]["pump"], "pump2")
        self.assertEqual(result["dose_event"]["requested_seconds"], 4.5)

    def test_saved_volume_shortens_the_requested_dose(self):
        module = load_runtime()
        module.load_dose_settings = lambda: {"pump1": 3.69, "pump2": 0.82, "pump3": 3.69}
        runtime = module.PumpRuntime()
        calls = []
        gateway = {"armed": True, "arm_mode": "flow", "circulation": "RUN", "in_progress": False,
                   "last_dose_elapsed_seconds": None,
                   "ml_in_last_24h": {"pump1": 0, "pump2": 0, "pump3": 0}}
        runtime.command = lambda *args: calls.append(args) or gateway
        result = runtime.apply(*inputs())
        self.assertEqual(calls, [("status",), ("dose", "pump2", "1.00000000")])
        self.assertEqual(result["dose_settings"]["volumes_ml"]["pump2"], 0.82)

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

    def test_critical_stops_circulation_and_holds_automatic_dose(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "STOP", "in_progress": False}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        automation["override"] = True
        automation["active_mode"] = pi_pump_decision.SEMI
        automation["override_reason"] = "ph Critical"
        automation["circulation_stop_required"] = True
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(calls, [("status",), ("safe-off",)])
        self.assertFalse(result["actuation_enabled"])
        self.assertEqual(result["outputs"]["circulation_pump"], "OFF")

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

    def test_farmer_can_select_the_specific_recommended_pump(self):
        module = load_runtime()
        runtime = module.PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "RUN", "in_progress": False,
                   "last_dose_elapsed_seconds": None,
                   "ml_in_last_24h": {"pump1": 0, "pump2": 0, "pump3": 0}}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        automation["active_mode"] = pi_pump_decision.SEMI
        automation["selected_mode"] = pi_pump_decision.SEMI
        automation["confirmation_available"] = True
        state = {"automation": automation, "database": {"status": "AVAILABLE"},
                 "water_quality_experimental": {"value": "Optimal"},
                 "plant_condition": {"status": "READY", "value": "Healthy"},
                 "camera": camera}
        result = runtime.confirm(state, snapshot, "pump3")
        self.assertIn("BLOCKED", result.status)
        self.assertEqual(calls, [("status",)])

    def test_farmer_can_select_nutrients_when_ph_also_needs_correction(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "arm_mode": "flow", "circulation": "RUN", "in_progress": False,
                   "last_dose_elapsed_seconds": None, "ml_in_last_24h": {}}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        snapshot["sensors"]["ec"]["value_mScm"] = 1.0
        automation.update(active_mode=pi_pump_decision.SEMI,
                          selected_mode=pi_pump_decision.SEMI,
                          confirmation_available=True)
        state = {"automation": automation, "database": {"status": "AVAILABLE"},
                 "water_quality_experimental": {"value": "Suboptimal"},
                 "plant_condition": {"status": "READY", "value": "Healthy"},
                 "camera": camera}
        result = runtime.confirm(state, snapshot, "pump1")
        self.assertEqual(result.status, "DOSED")
        self.assertEqual(result.value["pump"], "pump1")
        self.assertEqual(calls, [("status",), ("dose", "pump1", "4.50000000")])

    def test_farmer_must_select_a_specific_pump(self):
        runtime = load_runtime().PumpRuntime()
        runtime.command = lambda *args: self.fail("A missing selection must not reach the gateway")
        result = runtime.confirm({}, {}, None)
        self.assertEqual(result.status, "BLOCKED — SELECT ONE PUMP")

    def test_critical_ph_blocks_farmer_dose_while_circulation_stops(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "circulation": "RUN", "in_progress": False,
                   "last_dose_elapsed_seconds": None,
                   "ml_in_last_24h": {"pump1": 0, "pump2": 0, "pump3": 0}}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        snapshot["sensors"]["ph"]["value"] = 8.5
        automation["active_mode"] = pi_pump_decision.SEMI
        automation["selected_mode"] = pi_pump_decision.SEMI
        automation["override"] = True
        automation["confirmation_available"] = False
        automation["circulation_stop_required"] = True
        state = {"automation": automation,
                 "water_quality_experimental": {"value": "Critical"},
                 "plant_condition": {"status": "READY", "value": "Healthy"},
                 "camera": camera}
        result = runtime.confirm(state, snapshot)
        self.assertIn("BLOCKED", result.status)
        self.assertEqual(calls, [])

    def test_critical_manual_arm_allows_selected_pump_with_circulation_stopped(self):
        module = load_runtime()
        module.load_dose_settings = lambda: {"pump1": 0.82, "pump2": 0.82, "pump3": 0.82}
        runtime = module.PumpRuntime()
        calls = []
        gateway = {"armed": True, "arm_mode": "manual", "circulation": "STOP",
                   "in_progress": False, "last_dose_elapsed_seconds": None}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        snapshot["sensors"]["ph"]["value"] = 8.5
        automation.update(active_mode=pi_pump_decision.SEMI,
                          selected_mode=pi_pump_decision.SEMI,
                          override=True, override_reason="ec Critical",
                          circulation_stop_required=True,
                          recommendations=["pH-Down dosing"], confirmation_available=True)
        state = {"automation": automation, "database": {"status": "AVAILABLE"},
                 "water_quality_experimental": {"value": "Critical"}}
        displayed = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertTrue(displayed["confirmation_available"])
        self.assertTrue(displayed["critical_manual_dose"])
        self.assertFalse(displayed["actuation_enabled"])
        self.assertEqual(displayed["outputs"]["circulation_pump"], "OFF")
        self.assertEqual(calls, [("status",), ("safe-off",)])
        calls.clear()
        result = runtime.confirm(state, snapshot, "pump3")
        self.assertEqual(result.status, "DOSED")
        self.assertAlmostEqual(result.value["estimated_ml"], 3.69)
        self.assertEqual(calls, [("status",), ("manual-dose", "pump3", "4.50000000")])

    def test_full_request_remains_selected_during_critical_manual_correction(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "arm_mode": "manual", "circulation": "STOP",
                   "auto_resume_available": True, "in_progress": False,
                   "last_dose_elapsed_seconds": None}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, water, plant, camera = inputs()
        snapshot["sensors"]["ph"].update(value=4.0, classification="CRITICAL")
        automation.update(active_mode=pi_pump_decision.SEMI, override=True,
                          override_reason="ph Critical", circulation_stop_required=True,
                          recommendations=["pH-Up dosing"])
        water.value = "Critical"
        displayed = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertTrue(displayed["confirmation_available"])
        self.assertEqual(displayed["selected_mode"], pi_pump_decision.FULL)
        calls.clear()
        state = {"automation": displayed, "database": {"status": "AVAILABLE"},
                 "water_quality_experimental": {"value": "Critical"}}
        result = runtime.confirm(state, snapshot, "pump2")
        self.assertEqual(result.status, "DOSED")
        self.assertEqual(calls, [("status",), ("manual-dose", "pump2", "4.50000000")])

    def test_repeat_requires_mixing_wait_and_post_dose_sample(self):
        module = load_runtime()
        self.assertEqual(module.manual_wait_reason({"last_dose_elapsed_seconds": 59}, 1),
                         "Wait at least 60 seconds after the previous dose")
        self.assertEqual(module.manual_wait_reason({"last_dose_elapsed_seconds": 60}, 63),
                         "Wait for a new sensor reading after the previous dose")
        self.assertIsNone(module.manual_wait_reason({"last_dose_elapsed_seconds": 61}, 1))

    def test_repeat_requires_an_actual_post_dose_snapshot(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        gateway = {"armed": True, "arm_mode": "manual", "circulation": "STOP",
                   "in_progress": False, "last_dose_elapsed_seconds": 61}
        runtime.command = lambda *args: calls.append(args) or gateway
        automation, snapshot, *_ = inputs()
        snapshot["sensors"]["ec"]["value_mScm"] = 0.3
        automation.update(active_mode=pi_pump_decision.SEMI,
                          selected_mode=pi_pump_decision.SEMI,
                          override_reason="ec Critical", circulation_stop_required=True,
                          confirmation_available=True)
        state = {"automation": automation, "database": {"status": "AVAILABLE"},
                 "water_quality_experimental": {"value": "Critical"}}
        snapshot["timestamp"] = (datetime.now(timezone.utc) - timedelta(seconds=63)).isoformat()
        blocked = runtime.confirm(state, snapshot, "pump1")
        self.assertEqual(blocked.status, "BLOCKED — WAIT FOR NEXT CHECK")
        self.assertEqual(calls, [("status",)])
        snapshot["timestamp"] = datetime.now(timezone.utc).isoformat()
        result = runtime.confirm(state, snapshot, "pump1")
        self.assertEqual(result.status, "DOSED")
        self.assertEqual(calls[-1], ("manual-dose", "pump1", "4.50000000"))

    def test_manual_arm_never_runs_full_auto_or_circulation(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {
            "armed": True, "arm_mode": "manual", "circulation": "STOP",
            "in_progress": False}
        automation, snapshot, water, plant, camera = inputs()
        automation["recommendations"] = ["pH-Up dosing"]
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(calls, [("status",), ("safe-off",)])
        self.assertEqual(result["active_mode"], pi_pump_decision.SEMI)
        self.assertFalse(result["confirmation_available"])
        self.assertFalse(result["actuation_enabled"])

    def test_full_mode_resumes_after_supervised_flow_manual_session(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        manual = {"armed": True, "arm_mode": "manual", "circulation": "STOP",
                  "auto_resume_available": True, "in_progress": False,
                  "last_dose_elapsed_seconds": 90}
        flow = {"armed": True, "arm_mode": "flow", "circulation": "RUN",
                "in_progress": False, "last_dose_elapsed_seconds": 90}

        def command(*args):
            calls.append(args)
            return flow if args == ("status",) and ("resume-flow",) in calls else manual

        runtime.command = command
        automation, snapshot, water, plant, camera = inputs()
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(result["active_mode"], pi_pump_decision.FULL)
        self.assertEqual(result["hardware_status"], "CONNECTED — GUARDED PUMP GATEWAY")
        self.assertEqual(calls[:4], [("status",), ("safe-off",), ("resume-flow",), ("status",)])
        self.assertEqual(calls[4][0:2], ("dose", "pump2"))

    def test_manual_session_waits_for_new_sample_before_flow_resume(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {
            "armed": True, "arm_mode": "manual", "circulation": "STOP",
            "auto_resume_available": True, "in_progress": False,
            "last_dose_elapsed_seconds": 90}
        automation, snapshot, water, plant, camera = inputs()
        snapshot["timestamp"] = (datetime.now(timezone.utc) - timedelta(seconds=91)).isoformat()
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(result["active_mode"], pi_pump_decision.SEMI)
        self.assertEqual(calls, [("status",), ("safe-off",)])

    def test_critical_manual_session_cannot_resume_flow(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {
            "armed": True, "arm_mode": "manual", "circulation": "STOP",
            "auto_resume_available": True, "in_progress": False,
            "last_dose_elapsed_seconds": 90}
        automation, snapshot, water, plant, camera = inputs()
        automation.update(active_mode=pi_pump_decision.SEMI, override=True,
                          circulation_stop_required=True)
        result = runtime.apply(automation, snapshot, water, plant, camera)
        self.assertEqual(result["active_mode"], pi_pump_decision.SEMI)
        self.assertEqual(calls, [("status",), ("safe-off",)])

    def test_manual_arm_rejects_faulty_matching_sensor(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {
            "armed": True, "arm_mode": "manual", "circulation": "STOP",
            "in_progress": False, "last_dose_elapsed_seconds": None}
        automation, snapshot, *_ = inputs()
        snapshot["sensors"]["ph"].update(value=8.5, status="ERROR")
        automation.update(active_mode=pi_pump_decision.SEMI,
                          selected_mode=pi_pump_decision.SEMI,
                          circulation_stop_required=True, confirmation_available=True)
        result = runtime.confirm({"automation": automation,
                                  "database": {"status": "AVAILABLE"}}, snapshot, "pump3")
        self.assertIn("BLOCKED", result.status)
        self.assertEqual(calls, [("status",)])

    def test_fault_blocks_farmer_confirmation_before_gateway_call(self):
        runtime = load_runtime().PumpRuntime()
        calls = []
        runtime.command = lambda *args: calls.append(args) or {}
        automation, snapshot, water, plant, camera = inputs()
        automation["active_mode"] = pi_pump_decision.SEMI
        automation["circulation_stop_required"] = True
        state = {"automation": automation}
        result = runtime.confirm(state, snapshot)
        self.assertIn("BLOCKED", result.status)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
