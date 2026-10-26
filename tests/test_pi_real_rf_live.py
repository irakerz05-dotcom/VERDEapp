import csv
import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_real_rf_live import patch_service, prepare
from deploy.pi_real_rf_live import RealDataPilotClassifier
from deploy.train_pi_water_pilot import COLUMNS, audit_pilot, fit_pilot


class LivePilotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        csv_path = root / "batch.csv"
        rows = [
            ("one", "grow", 6.2, 1.5, 21, 1),
            ("two", "suboptimal", 7.3, 2.6, 30, 6),
            ("three", "critical", 10.5, 0.2, 40, 8),
            ("four", "optimal-solution-02", 6.4, 1.4, 22, 1.1),
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(COLUMNS)
            for sample_id, batch, *values in rows:
                writer.writerow((sample_id, "2026-10-27T01:00:00+08:00", *values,
                                 batch, "", "", "", ""))
        samples, summary = audit_pilot(csv_path)
        self.artifact = root / "pilot.json.gz"
        fit_pilot(samples, summary, self.artifact, ["optimal-solution-02"])
        self.service_source = '''from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs
class Example:
    def __init__(self):
        self.prototype_classifier = PrototypeRFClassifier()
    def sample(self):
        experimental_water = None
        live_snapshot = integrated.snapshot()
        if True:
            sensor_fault = required_water_sensor_fault(live_snapshot)
            fusion_water = experimental_water
            automation = evaluate()
            state = {
                "water_quality_experimental": experimental_water.as_dict(),
            }
            failed = {
                              "water_quality_experimental": unavailable, "plant_condition": unavailable,
            }
'''

    def test_live_result_has_provenance_and_never_invents_missing_values(self):
        pilot = RealDataPilotClassifier(self.artifact)
        ready = pilot.classify({"ph": 6.2, "ec": 1.5,
                                "water_temperature": 21, "turbidity": 1})
        self.assertEqual(ready["status"], "EXPERIMENTAL")
        self.assertIn(ready["value"], {"Optimal", "Suboptimal", "Critical"})
        self.assertIn("no independent validation", ready["detail"])
        self.assertIn("Paper thresholds: Optimal", ready["detail"])
        missing = pilot.classify(None)
        self.assertEqual(missing["status"], "SENSOR INPUT UNAVAILABLE")
        self.assertIsNone(missing["value"])
        self.assertIn("provisional", pilot.classify({"ph": 6.2, "ec": 1.5,
            "water_temperature": 21, "turbidity": 1}, fluctuating=("ph",))["detail"])

    def test_service_patch_is_idempotent_and_keeps_safety_paths(self):
        updated = patch_service(self.service_source)
        self.assertEqual(patch_service(updated), updated)
        self.assertIn("fusion_water = experimental_water", updated)
        self.assertIn("automation = evaluate()", updated)
        self.assertIn('"water_quality_real_pilot": real_pilot_water.as_dict()', updated)

    def test_guarded_installer_stages_only_service_and_pilot_module(self):
        root = Path(self.directory.name) / "backend"
        service = root / "app/service.py"
        service.parent.mkdir(parents=True)
        # A missing live service must never be patched.
        with self.assertRaises(OSError):
            prepare(root, self.artifact)
        service.write_text(self.service_source, encoding="utf-8")
        planned, edits = prepare(root, self.artifact)
        self.assertEqual(edits, 2)
        self.assertEqual({str(path.relative_to(root)) for path in planned},
                         {str(Path("app/service.py")), str(Path("app/ml/water_quality/real_rf_pilot.py"))})
        self.assertIn(b"fusion_water = experimental_water", planned[service])


if __name__ == "__main__":
    unittest.main()
