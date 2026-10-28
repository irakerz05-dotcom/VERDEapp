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
                     calibrated_dose_seconds={"pump1": 1 / 0.82, "pump2": 1 / 0.82,
                                              "pump3": 1 / 0.82},
                     dosed_ml_by_pump={"pump1": 0.0, "pump2": 0.0, "pump3": 0.0},
                     circulation_flow_gpio_level=None)
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
        self.assertIsNone(choose().circulation_gpio_level)

    def test_circulation_gpio_level_uses_observed_flow_polarity(self):
        for flow_level, stop_level in (("LOW", "HIGH"), ("HIGH", "LOW")):
            self.assertEqual(choose(circulation_flow_gpio_level=flow_level).circulation_gpio_level,
                             flow_level)
            stopped = choose(water_class="Critical", circulation_flow_gpio_level=flow_level)
            self.assertEqual(stopped.circulation_gpio_level, stop_level)
        with self.assertRaises(ValueError):
            choose(circulation_flow_gpio_level="probably HIGH")

    def test_one_minute_mixing_and_measured_duration_gate(self):
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 last_dose_elapsed_seconds=59.9).pump)
        self.assertEqual(choose(sensors=sensors(ph=5.2),
                                last_dose_elapsed_seconds=60).pump, "pump2")
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 calibrated_dose_seconds={}).pump)
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 calibrated_dose_seconds={"pump2": 5.1}).pump)

    def test_one_ml_steps_and_ten_ml_nutrient_course_limit(self):
        nutrient = choose(sensors=sensors(ec=1.0),
                          dosed_ml_by_pump={"pump1": 9.0})
        self.assertEqual(nutrient.pump, "pump1")
        self.assertEqual(nutrient.dose_ml, 1.0)
        self.assertAlmostEqual(nutrient.dose_seconds, 1.219512195, places=7)
        self.assertIsNone(choose(sensors=sensors(ec=1.0),
                                 dosed_ml_by_pump={"pump1": 10.0}).pump)
        self.assertIsNone(choose(sensors=sensors(ec=1.0),
                                 dosed_ml_by_pump={}).pump)
        self.assertEqual(choose(sensors=sensors(ph=5.2)).dose_ml, 1.0)
        ph_up_last = choose(sensors=sensors(ph=5.2),
                            dosed_ml_by_pump={"pump2": 5.0})
        self.assertAlmostEqual(ph_up_last.dose_ml, 0.86)
        self.assertAlmostEqual(ph_up_last.dose_seconds, 0.86 / 0.82)
        self.assertIsNone(choose(sensors=sensors(ph=5.2),
                                 dosed_ml_by_pump={"pump2": 5.86}).pump)
        ph_down_last = choose(sensors=sensors(ph=6.8),
                              dosed_ml_by_pump={"pump3": 3.0})
        self.assertAlmostEqual(ph_down_last.dose_ml, 0.98)
        self.assertAlmostEqual(ph_down_last.dose_seconds, 0.98 / 0.82)
        self.assertIsNone(choose(sensors=sensors(ph=8.5)).pump)  # Critical override.

    def test_critical_and_faults_latch_semi_and_stop_circulation(self):
        critical = choose(water_class="Critical", circulation_flow_gpio_level="HIGH")
        self.assertEqual((critical.active_mode, critical.circulation, critical.pump),
                         (SEMI, "STOP", None))
        self.assertTrue(critical.override_latched)
        fault = sensors(ph=5.2)
        fault["water_temperature"] = {"value_C": 22, "status": "ERROR: CRC"}
        self.assertEqual(choose(sensors=fault, circulation_flow_gpio_level="HIGH").circulation,
                         "STOP")
        self.assertEqual(choose(vision_fault=True, circulation_flow_gpio_level="HIGH").circulation,
                         "STOP")

    def test_recovery_holds_dosing_without_treating_humidity_as_fault(self):
        recovering = sensors(ph=5.2)
        recovering["water_temperature"] = {"value_C": None, "status": "RECOVERING"}
        decision = choose(sensors=recovering, circulation_flow_gpio_level="HIGH")
        self.assertIsNone(decision.pump)
        self.assertEqual(decision.circulation, "RUN")
        self.assertFalse(decision.override_latched)
        self.assertEqual(choose(sensors=sensors(ph=5.2)).pump, "pump2")

    def test_latched_override_needs_new_farmer_full_request(self):
        held = choose(override_latched=True, circulation_flow_gpio_level="HIGH")
        self.assertEqual((held.active_mode, held.circulation), (SEMI, "STOP"))
        restored = choose(override_latched=True, request_full=True,
                          circulation_flow_gpio_level="HIGH")
        self.assertEqual((restored.active_mode, restored.circulation), (FULL, "RUN"))
        still_faulty = choose(override_latched=True, request_full=True,
                              vision_fault=True, circulation_flow_gpio_level="HIGH")
        self.assertEqual(still_faulty.active_mode, SEMI)
        recovering = sensors()
        recovering["water_temperature"] = {"value_C": None, "status": "RECOVERING"}
        self.assertEqual(choose(override_latched=True, request_full=True,
                                sensors=recovering).active_mode, SEMI)

    def test_stale_snapshot_never_doses(self):
        decision = choose(sensors=sensors(ph=5.2), snapshot_age_seconds=66,
                          circulation_flow_gpio_level="HIGH")
        self.assertEqual((decision.pump, decision.circulation), (None, "STOP"))


if __name__ == "__main__":
    unittest.main()
