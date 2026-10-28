"""Live-source mode decisions without enabling actuators."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from deploy.pi_live_automation_mode import FULL, SEMI, evaluate_live


NOW = datetime(2026, 10, 29, 3, 41, 40, tzinfo=timezone.utc)


def snapshot():
    return {
        "timestamp": "2026-10-29T03:41:20+00:00",
        "sensors": {
            "ph": {"value": 6.3, "classification": "OPTIMAL", "status": "OK",
                   "valid": True, "retained": False, "stale": False},
            "ec": {"value_mScm": 1.38, "classification": "OPTIMAL",
                   "status": "OK: PROVISIONAL THREE-POINT EC", "valid": True,
                   "retained": False, "stale": False},
            "turbidity": {"value_ntu": 0.3, "classification": "OPTIMAL",
                          "status": "CALIBRATED"},
            "water_temperature": {"value_C": 22.0, "classification": "OPTIMAL",
                                  "status": "OK: DS18B20"},
            "ambient_humidity": {"value": None, "status": "ERROR"},
        },
    }


def decide(**changes):
    args = dict(selected_mode=FULL, snapshot=snapshot(),
                water=SimpleNamespace(status="EXPERIMENTAL", value="Optimal"),
                plant=SimpleNamespace(status="READY", value="Healthy"),
                camera={"status": "READY"},
                limits={"ph_optimal": (5.5, 6.5), "ec_optimal": (1.2, 1.8)},
                now=NOW)
    args.update(changes)
    return evaluate_live(**args)


class LiveModeTests(unittest.TestCase):
    def test_healthy_live_cache_clears_legacy_override_but_not_actuation(self):
        result = decide()
        self.assertEqual(result["active_mode"], FULL)
        self.assertFalse(result["override"])
        self.assertFalse(result["circulation_stop_required"])
        self.assertFalse(result["actuation_enabled"])
        self.assertEqual(result["recommendations"], [])

    def test_critical_and_camera_fault_override(self):
        live = snapshot()
        live["sensors"]["ph"]["classification"] = "CRITICAL"
        self.assertEqual(decide(snapshot=live)["active_mode"], SEMI)
        self.assertFalse(decide(snapshot=live)["circulation_stop_required"])
        self.assertTrue(decide(camera={"status": "FAULT / ERROR"})["override"])
        self.assertTrue(decide(camera={"status": "FAULT / ERROR"})["circulation_stop_required"])
        self.assertTrue(decide(water=SimpleNamespace(value="Critical", status="EXPERIMENTAL"))["override"])

    def test_recovering_temperature_holds_without_fault_override(self):
        live = snapshot()
        live["sensors"]["water_temperature"] = {
            "value_C": None, "status": "RECOVERING: CRC", "consecutive_failures": 1}
        result = decide(snapshot=live)
        self.assertFalse(result["override"])
        self.assertIn("water_temperature", result["hold_reason"])
        live["sensors"]["water_temperature"]["consecutive_failures"] = 2
        live["sensors"]["water_temperature"]["valid"] = False
        self.assertTrue(decide(snapshot=live)["override"])
        self.assertTrue(decide(snapshot=live)["circulation_stop_required"])

    def test_missing_plant_classification_is_hold_not_fault(self):
        result = decide(plant=SimpleNamespace(value=None, status="NO DETECTION"))
        self.assertFalse(result["override"])
        self.assertIn("plant classification unavailable", result["hold_reason"])

    def test_missing_required_sensor_stops_circulation(self):
        live = snapshot()
        del live["sensors"]["ph"]
        result = decide(snapshot=live)
        self.assertTrue(result["override"])
        self.assertTrue(result["circulation_stop_required"])

    def test_numeric_critical_overrides_even_if_classification_is_stale(self):
        live = snapshot()
        live["sensors"]["ph"]["value"] = 8.5
        result = decide(snapshot=live)
        self.assertTrue(result["override"])
        self.assertFalse(result["circulation_stop_required"])

    def test_stale_snapshot_and_legacy_placeholder_never_enable_pumps(self):
        live = snapshot()
        live["timestamp"] = "2026-10-29T03:40:00+00:00"
        result = decide(snapshot=live)
        self.assertTrue(result["override"])
        self.assertTrue(result["circulation_stop_required"])
        self.assertFalse(result["actuation_enabled"])
        self.assertTrue(all("OFF" in value for value in result["outputs"].values()))


if __name__ == "__main__":
    unittest.main()
