"""Safety decisions for the proposed Pi pump integration; no GPIO is imported."""

import unittest

from deploy.pi_pump_decision import FULL, SEMI, decide, manual_correction


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
                     calibrated_dose_seconds={"pump1": 4.5, "pump2": 4.5, "pump3": 4.5},
                     dosed_ml_by_pump={"pump1": 0.0, "pump2": 0.0, "pump3": 0.0},
                     circulation_flow_gpio_level=None)
    arguments.update(overrides)
    return decide(**arguments)


class PumpDecisionTests(unittest.TestCase):
    def test_manual_correction_uses_only_fresh_matching_sensor(self):
        durations = {"pump1": 4.5, "pump2": 4.5, "pump3": 4.5}
        live = sensors(ph=8.5, ec=0.3)
        self.assertEqual(manual_correction(live, "pump3", None, durations),
                         ("ph_down", "pump3", 4.5, 3.69))
        self.assertEqual(manual_correction(live, "pump1", None, durations),
                         ("nutrient_dosing", "pump1", 4.5, 3.69))
        self.assertIsNone(manual_correction(live, "pump2", None, durations))
        self.assertIsNone(manual_correction(live, "pump3", 59, durations))
        live["ph"]["status"] = "ERROR"
        self.assertIsNone(manual_correction(live, "pump3", None, durations))
        self.assertIsNotNone(manual_correction(live, "pump1", None, durations))
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
            stopped = choose(vision_fault=True, circulation_flow_gpio_level=flow_level)
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

    def test_pulse_size_does_not_depend_on_24_hour_totals(self):
        nutrient = choose(sensors=sensors(ec=1.0),
                          dosed_ml_by_pump={"pump1": 0.0})
        self.assertEqual(nutrient.pump, "pump1")
        self.assertAlmostEqual(nutrient.dose_ml, 3.69)
        self.assertEqual(nutrient.dose_seconds, 4.5)
        nutrient_last = choose(sensors=sensors(ec=1.0),
                               dosed_ml_by_pump={"pump1": 7.0})
        self.assertAlmostEqual(nutrient_last.dose_ml, 3.69)
        self.assertEqual(nutrient_last.dose_seconds, 4.5)
        self.assertEqual(choose(sensors=sensors(ec=1.0),
                                dosed_ml_by_pump={"pump1": 9.0}).pump, "pump1")
        self.assertEqual(choose(sensors=sensors(ec=1.0),
                                dosed_ml_by_pump={}).pump, "pump1")
        self.assertAlmostEqual(choose(sensors=sensors(ph=5.2)).dose_ml, 3.69)
        ph_up_last = choose(sensors=sensors(ph=5.2),
                            dosed_ml_by_pump={"pump2": 3.69})
        self.assertAlmostEqual(ph_up_last.dose_ml, 3.69)
        self.assertEqual(ph_up_last.dose_seconds, 4.5)
        self.assertEqual(choose(sensors=sensors(ph=5.2),
                                dosed_ml_by_pump={"pump2": 5.274}).pump, "pump2")
        ph_down_last = choose(sensors=sensors(ph=6.8),
                              dosed_ml_by_pump={"pump3": 0.0})
        self.assertAlmostEqual(ph_down_last.dose_ml, 3.69)
        self.assertAlmostEqual(ph_down_last.dose_seconds, 4.5)
        self.assertEqual(choose(sensors=sensors(ph=6.8),
                                dosed_ml_by_pump={"pump3": 3.69}).pump, "pump3")
        self.assertIsNone(choose(sensors=sensors(ph=8.5)).pump)  # Critical override.

    def test_critical_latches_semi_and_stops_circulation(self):
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

    def test_latched_override_returns_to_requested_full_mode_when_healthy(self):
        held = choose(override_latched=True, circulation_flow_gpio_level="HIGH")
        self.assertEqual((held.active_mode, held.circulation), (FULL, "RUN"))
        self.assertFalse(held.override_latched)
        still_faulty = choose(override_latched=True,
                              vision_fault=True, circulation_flow_gpio_level="HIGH")
        self.assertEqual(still_faulty.active_mode, SEMI)
        recovering = sensors()
        recovering["water_temperature"] = {"value_C": None, "status": "RECOVERING"}
        self.assertEqual(choose(override_latched=True,
                                sensors=recovering).active_mode, SEMI)
        self.assertEqual(choose(selected_mode=SEMI, override_latched=True).active_mode, SEMI)

    def test_stale_snapshot_never_doses(self):
        decision = choose(sensors=sensors(ph=5.2), snapshot_age_seconds=66,
                          circulation_flow_gpio_level="HIGH")
        self.assertEqual((decision.pump, decision.circulation), (None, "STOP"))

    def test_missing_required_sensor_stops_circulation(self):
        live = sensors()
        del live["ph"]
        decision = choose(sensors=live, circulation_flow_gpio_level="HIGH")
        self.assertEqual((decision.pump, decision.circulation), (None, "STOP"))

    def test_semi_requires_confirmation_and_stops_every_critical_condition(self):
        high_ph = sensors(ph=8.5)
        self.assertIsNone(choose(selected_mode=SEMI, sensors=high_ph,
                                 water_class="Critical").pump)
        confirmed = choose(selected_mode=SEMI, sensors=high_ph,
                           water_class="Critical", farmer_confirmed=True,
                           circulation_flow_gpio_level="HIGH")
        self.assertEqual((confirmed.pump, confirmed.circulation), (None, "STOP"))
        high_turbidity = sensors(ph=5.2)
        high_turbidity["turbidity"]["classification"] = "CRITICAL"
        self.assertIsNone(choose(selected_mode=SEMI, sensors=high_turbidity,
                                 water_class="Critical", farmer_confirmed=True).pump)
        faulty = sensors(ph=5.2)
        faulty["ph"]["status"] = "ERROR"
        self.assertIsNone(choose(selected_mode=SEMI, sensors=faulty,
                                 farmer_confirmed=True).pump)

    def test_farmer_selects_one_eligible_pump_when_ph_and_ec_both_need_correction(self):
        readings = sensors(ph=5.2, ec=1.0)
        base = dict(selected_mode=SEMI, sensors=readings, farmer_confirmed=True,
                    circulation_flow_gpio_level="HIGH")
        self.assertEqual(choose(**base, requested_pump="pump2").pump, "pump2")
        self.assertEqual(choose(**base, requested_pump="pump1").pump, "pump1")
        self.assertIsNone(choose(**base, requested_pump="pump3").pump)
        self.assertEqual(choose(**base).pump, "pump2")


if __name__ == "__main__":
    unittest.main()
