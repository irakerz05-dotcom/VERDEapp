"""Validate the guarded Pi-only RF update without hardware or a service restart."""

import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_rf_filtered_spikes import MODEL, SERVICE, apply, prepare


MODEL_SOURCE = '''FEATURES = ("ph", "ec", "water_temperature", "turbidity")
def features_from_live(snapshot):
    sensors = snapshot["sensors"]
    for name in FEATURES:
        sensor = sensors[name]
        if (False
                or sensor.get("stale") is True or sensor.get("spike") is True
                or sensor.get("read_error") is not None):
            return None
    values = {}
    return values


def _load_artifact(path):
    pass

class PrototypeRFClassifier:
    def classify(self, features):
        predicted = "Optimal"
        return Result("EXPERIMENTAL", predicted,
                      detail="Prototype Random Forest trained on paper-rule examples; not validated with labeled measurements. Turbidity uses a project-assigned NTU reference.")
'''
SERVICE_SOURCE = '''from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live
def tick(self, live_snapshot):
            experimental_water = guarded(lambda: self.prototype_classifier.classify(
                features_from_live(live_snapshot)), error_status="MODEL UNAVAILABLE")
'''


class FilteredSpikePatchTests(unittest.TestCase):
    def test_patch_preserves_fresh_filter_and_reports_fluctuation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in ((MODEL, MODEL_SOURCE), (SERVICE, SERVICE_SOURCE)):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source, encoding="utf-8")
            self.assertEqual(len(prepare(root)), 2)
            backups = apply(root)
            self.assertEqual(len(backups), 2)
            self.assertIn('def fluctuating_inputs(snapshot):', (root / MODEL).read_text())
            self.assertIn('fluctuating=fluctuating_inputs(live_snapshot)', (root / SERVICE).read_text())
            with self.assertRaises(ValueError):
                prepare(root)
            for backup in backups:
                self.assertTrue(backup.is_file())


if __name__ == "__main__":
    unittest.main()
