"""Safety decisions for the proposed Pi pump integration; no GPIO is imported."""

import unittest

from deploy.pi_pump_decision import FULL, SEMI, decide


def sensors(ph=6.0, ec=1.4):
    return {
        "ph": {"value": ph, "status": "OK", "valid": True, "classification": "OPTIMAL"},
        "ec": {"value_mScm": ec, "status": "OK", "valid": True,
               "classification": "OPTIMAL"},
        "water_temperature": {"value_C": 22.0, "status": "OK"},
        "turbidity": {"value_ntu": 0.3, "status": "CALIBRATED",
                      "classification": "OPTIMAL"},
        "ambient_humidity": {"value": None, "status": "ERROR"},
    }


def choose(**overrides):
    arguments = dict(selected_mode=FULL, override_latched=False, request_full=False,
                     sensors=sensors(), snapshot_age_seconds=5, water_class="Suboptimal",
                     camera_fault=False, vision_fault=False,
                     last_dose_elapsed_seconds=None,
                     calibrated_dose_seconds={"pump1": 1, "pump2": 1, "pump3": 1},
                     circulation_polarity_verified=False)
    arguments.update(overrides)
    return decide(**arguments)


class PumpDecisionTests(unittest.TestCase):
    def test_pump_mapping_and_unverified_circulation(self):
        self.assertEqual(choose(sensors=sensors(ph=5.2)).pump, "pump2")
        self.assertEqual(choose(sensors=sensors(ph=6.8)).pump, "pump3")
        self.assertEqual(choose(sensors=sensors(ec=1.0)).pump, "pump1")
        self.assertEqual(choose(sensors=sensors(ec=2.1)).pump, None)
        self.assertEqual(choose(sensors=sensors(ph=5.2)).circulation,
                         "BLOCKED: polarity unverified")

    def test_one_minute_mixing_and_measured_duration_gate(self):
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 last_dose_elapsed_seconds=59.9).pump)
        self.assertEqual(choose(sensors=sensors(ph=5.2),
                                last_dose_elapsed_seconds=60).pump, "pump2")
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 calibrated_dose_seconds={}).pump)
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 calibrated_dose_seconds={"pump2": 5.1}).pump)

    def test_critical_and_faults_latch_semi_and_stop_circulation(self):
        critical = choose(water_class="Critical", circulation_polarity_verified=True)
        self.assertEqual((critical.active_mode, critical.circulation, critical.pump),
                         (SEMI, "STOP", None))
        self.assertTrue(critical.override_latched)
        fault = sensors(ph=5.2)
        fault["water_temperature"] = {"value_C": 22, "status": "ERROR: CRC"}
        self.assertEqual(choose(sensors=fault, circulation_polarity_verified=True).circulation,
                         "STOP")
        self.assertEqual(choose(vision_fault=True, circulation_polarity_verified=True).circulation,
                         "STOP")

    def test_recovery_holds_dosing_without_treating_humidity_as_fault(self):
        recovering = sensors(ph=5.2)
        recovering["water_temperature"] = {"value_C": None, "status": "RECOVERING"}
        decision = choose(sensors=recovering, circulation_polarity_verified=True)
        self.assertIsNone(decision.pump)
        self.assertEqual(decision.circulation, "RUN")
        self.assertFalse(decision.override_latched)
        self.assertEqual(choose(sensors=sensors(ph=5.2)).pump, "pump2")

    def test_latched_override_needs_new_farmer_full_request(self):
        held = choose(override_latched=True, circulation_polarity_verified=True)
        self.assertEqual((held.active_mode, held.circulation), (SEMI, "STOP"))
        restored = choose(override_latched=True, request_full=True,
                          circulation_polarity_verified=True)
        self.assertEqual((restored.active_mode, restored.circulation), (FULL, "RUN"))
        still_faulty = choose(override_latched=True, request_full=True,
                              vision_fault=True, circulation_polarity_verified=True)
        self.assertEqual(still_faulty.active_mode, SEMI)
        recovering = sensors()
        recovering["water_temperature"] = {"value_C": None, "status": "RECOVERING"}
        self.assertEqual(choose(override_latched=True, request_full=True,
                                sensors=recovering).active_mode, SEMI)

    def test_stale_snapshot_never_doses(self):
        decision = choose(sensors=sensors(ph=5.2), snapshot_age_seconds=66,
                          circulation_polarity_verified=True)
        self.assertEqual((decision.pump, decision.circulation), (None, "STOP"))


if __name__ == "__main__":
    unittest.main()
