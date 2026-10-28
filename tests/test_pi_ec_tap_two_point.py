"""Check the A2 EC two-point fit and guarded Pi source update."""

import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from deploy.calibrate_pi_ec_tap_two_point import (
    LOADER, coefficients, old_standard, summarize, transform_source,
    validate_snapshot,
)


SOURCE = '''import json
import math
from pathlib import Path
ADS1115_GAIN = 1
EC_RECORD_PATH = Path("/home/verde/ec_calibration_1467_27C_v2.json")
def load_scale(path, coefficient_field, expected_formula, allowed_statuses):
    coefficient = 1.0
    return coefficient


def load_turbidity_reference(path=None):
    return None
class Sensor:
    def __init__(self):
        self.ec_tds_channel = RollingAnalogChannel("ec_tds", AnalogIn(self.ads, ADS.P2))
        self.ec_scale = load_scale(
            EC_RECORD_PATH, "ec_scale_uScm_per_V",
            "EC_uScm = EC_SCALE * voltage_V",
            {"ACCEPTED SINGLE-POINT DIRECT EC CALIBRATION — POST-HARDWARE-FIX"},
        )
    def sample(self, a2_reading):
        label = "EC V2 post-hardware-fix"
        ec_uScm = self.ec_scale * a2_reading["filtered_voltage_V"]
        return label, ec_uScm, "OK: ACCEPTED SINGLE-POINT DIRECT EC — POST-HARDWARE-FIX"
    def initial(self):
        return "EC V2 post-hardware-fix"
'''


class ECTapTwoPointTests(unittest.TestCase):
    def test_fit_matches_both_references(self):
        slope, intercept = coefficients(0.553125, 0.160625)
        self.assertAlmostEqual((slope * 0.553125 + intercept) / 1000, 1.413)
        self.assertAlmostEqual((slope * 0.160625 + intercept) / 1000, 0.138)
        self.assertGreater(slope, 0)
        with self.assertRaises(ValueError):
            coefficients(0.16, 0.16)

    def test_source_uses_new_record_and_preserves_a2(self):
        updated = transform_source(SOURCE)
        self.assertIn('self.ec_slope_uScm_per_V, self.ec_intercept_uScm = load_ec_two_point()', updated)
        self.assertIn('EC_TWO_POINT_RECORD_PATH', updated)
        self.assertIn('"ec_tds", AnalogIn(self.ads, ADS.P2)', updated)
        with self.assertRaises(ValueError):
            transform_source(updated)
        with self.assertRaisesRegex(ValueError, "A2"):
            transform_source(SOURCE.replace("ADS.P2", "ADS.P0"))

    def test_loader_rejects_record_that_does_not_fit_points(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ec_v3.json"
            slope, intercept = coefficients(0.553125, 0.160625)
            record = {
                "calibration_status": "PROVISIONAL TWO-POINT DIRECT EC",
                "formula": "EC_uScm = max(0, slope * voltage_V + intercept)",
                "slope_uScm_per_V": format(slope, ".15g"),
                "intercept_uScm": format(intercept, ".15g"),
                "reference_points": [
                    {"filtered_voltage_V": 0.553125, "ec_uScm": 1413.0},
                    {"filtered_voltage_V": 0.160625, "ec_uScm": 138.0},
                ],
            }
            path.write_text(json.dumps(record), encoding="utf-8")
            scope = {"Path": Path, "json": json, "math": math,
                     "EC_TWO_POINT_RECORD_PATH": path}
            exec(LOADER, scope)
            self.assertAlmostEqual(scope["load_ec_two_point"]()[0], slope)
            record["reference_points"][0]["ec_uScm"] = 1000.0
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "do not match"):
                scope["load_ec_two_point"]()

    def test_old_high_point_and_fresh_voltage_window(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ec_v2.json"
            path.write_text(json.dumps({
                "hardware": {"channel": "A2", "gain": 1},
                "reference_uScm": 1413.0, "reference_temperature_C": 25.0,
                "calibration_status": "ACCEPTED SINGLE-POINT DIRECT EC CALIBRATION — POST-HARDWARE-FIX",
                "reference_filtered_voltage_V": 0.553125,
                "ec_scale_uScm_per_V": "2554.576271186440863",
            }), encoding="utf-8")
            self.assertAlmostEqual(old_standard(path), 0.553125)
        now = datetime.now(timezone.utc)
        samples = []
        for index, voltage in enumerate((0.1600, 0.160125, 0.16025, 0.160375, 0.1605), 1):
            payload = {
                "timestamp": now.isoformat(),
                "system": {"sample": index, "ads1115_address": "0x48", "ads1115_gain": 1,
                           "ec_relay_state": "OFF", "ec_relay_polarity": "ACTIVE_LOW"},
                "sensors": {"ec": {"status": "OK", "valid": True, "retained": False,
                                   "stale": False, "spike": False,
                                   "raw_voltage_V": voltage,
                                   "filtered_voltage_V": voltage}},
            }
            samples.append(validate_snapshot(payload, now=now))
        self.assertAlmostEqual(summarize(samples)["median_voltage_V"], 0.16025)


if __name__ == "__main__":
    unittest.main()
