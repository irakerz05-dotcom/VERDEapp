import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ph_two_point", ROOT / "deploy/apply_pi_ph_two_point.py")
PH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PH)


class PHTwoPointTests(unittest.TestCase):
    SOURCE = ('ADS1115_GAIN = 1\nPH_SLOPE = -6.15727193\n'
              'PH_INTERCEPT = 24.1211421968\n'
              'self.ph_channel = RollingAnalogChannel("ph", AnalogIn(self.ads, ADS.P1))\n')

    def test_fit_matches_both_commercial_references(self):
        slope, intercept = PH.coefficients()
        self.assertAlmostEqual(slope * PH.NEUTRAL_V + intercept, 6.81)
        self.assertAlmostEqual(slope * PH.ALKALINE_V + intercept, 9.45)
        updated = PH.transform(self.SOURCE)
        self.assertIn(f"PH_SLOPE = {slope:.10f}", updated)
        self.assertIn(f"PH_INTERCEPT = {intercept:.10f}", updated)
        self.assertEqual(PH.transform(updated), updated)
        self.assertIn("4.41 acidic point is excluded", " ".join(PH.record_for("backup")["limitations"]))

    def test_source_changes_are_guarded(self):
        with self.assertRaisesRegex(ValueError, "reviewed 6.86-point"):
            PH.transform(self.SOURCE.replace("PH_SLOPE = -6.15727193", "PH_SLOPE = -8"))
        with self.assertRaisesRegex(ValueError, "A1 channel"):
            PH.transform(self.SOURCE.replace("ADS.P1", "ADS.P0"))

    def test_check_is_read_only_and_apply_keeps_a_backup_and_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "verde_sensor_service.py"
            record = Path(temporary) / "ph_calibration.json"
            target.write_text(self.SOURCE, encoding="utf-8")
            command = [sys.executable, str(ROOT / "deploy/apply_pi_ph_two_point.py"),
                       "--target", str(target), "--record", str(record)]
            checked = subprocess.run(command + ["--check"], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), self.SOURCE)
            self.assertFalse(record.exists())
            applied = subprocess.run(command + ["--apply"], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), PH.transform(self.SOURCE))
            self.assertEqual(json.loads(record.read_text(encoding="utf-8"))["slope"],
                             PH.coefficients()[0])
            self.assertEqual(len(list(Path(temporary).glob("*.before_ph_two_point_*"))), 1)


if __name__ == "__main__":
    unittest.main()
