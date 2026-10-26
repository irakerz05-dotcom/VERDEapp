import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from deploy.compare_pi_water_pilot import compare, load_pilot
from deploy.train_pi_water_pilot import COLUMNS, audit_pilot, fit_pilot


def make_row(number, batch, ph, ec, temperature, turbidity):
    return dict(zip(COLUMNS, (f"session.csv#{number}", "2026-10-27T01:00:00+08:00",
                              ph, ec, temperature, turbidity, batch, "", "", "", "")))


class WaterPilotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.csv_path = Path(self.directory.name) / "samples.csv"
        self.rows = [
            make_row(2, "grow", 6.503615914990622, 1.4356718644067799, 18.75, 0.9827800829875518),
            make_row(5, "grow", 6.363153149087502, 1.432797966101695, 19.687, 0.9830520199225236),
            make_row(67, "suboptimal", 7.3844906304762485, 2.638877288135593, 30.062, 6.202968136185072),
            make_row(28, "critical", 10.505457839995, 0.21618101694915257, 40.562, 7.847045831032579),
        ]
        self.write_rows()

    def write_rows(self):
        with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(self.rows)

    def test_mixed_batch_requires_explicit_exclusion(self):
        with self.assertRaisesRegex(ValueError, "conflicting threshold labels"):
            audit_pilot(self.csv_path)

    def test_explicit_boundary_exclusion_and_offline_artifact(self):
        samples, summary = audit_pilot(self.csv_path, ["session.csv#2"])
        self.assertEqual(summary["usable_rows"], 3)
        self.assertEqual(summary["batches_by_class"],
                         {"Optimal": 1, "Suboptimal": 1, "Critical": 1})
        self.assertTrue(summary["ready_for_exploratory_fit"])
        output = Path(self.directory.name) / "pilot.json.gz"
        fit_pilot(samples, summary, output)
        with gzip.open(output, "rt", encoding="utf-8") as handle:
            artifact = json.load(handle)
        self.assertEqual(artifact["training_source"],
                         "real_pi_readings_labeled_by_paper_thresholds")
        self.assertIn("no independent labels", artifact["validation"])
        self.assertEqual(set(artifact["classes"]), {"Optimal", "Suboptimal", "Critical"})
        self.assertNotIn("balanced_accuracy", artifact)
        with self.assertRaisesRegex(ValueError, "new output"):
            fit_pilot(samples, summary, output)

    def test_incomplete_classes_cannot_fit(self):
        self.rows = self.rows[:2]
        self.write_rows()
        samples, summary = audit_pilot(self.csv_path, ["session.csv#2"])
        self.assertFalse(summary["ready_for_exploratory_fit"])
        with self.assertRaisesRegex(ValueError, "one training batch"):
            fit_pilot(samples, summary, Path(self.directory.name) / "pilot.json.gz")

    def test_rejects_claimed_independent_label_in_pilot(self):
        self.rows[1]["independent_reference_label"] = "Optimal"
        self.write_rows()
        with self.assertRaisesRegex(ValueError, "unlabeled capture"):
            audit_pilot(self.csv_path, ["session.csv#2"])

    def test_new_optimal_batch_is_held_out_and_compared_offline(self):
        self.rows.append(make_row(159, "optimal-02", 6.1, 1.5, 21, 1.1))
        self.write_rows()
        samples, summary = audit_pilot(self.csv_path, ["session.csv#2"])
        output = Path(self.directory.name) / "held-out.json.gz"
        fit_pilot(samples, summary, output, ["optimal-02"])
        model = load_pilot(output)
        self.assertEqual(model["training_batch_ids"], ["critical", "grow", "suboptimal"])
        self.assertEqual(model["held_out_batch_ids"], ["optimal-02"])
        result = compare(model, samples, "optimal-02")
        self.assertEqual(result["readings"][0]["threshold_class"], "Optimal")
        self.assertIn(result["readings"][0]["pilot_prediction"],
                      ("Optimal", "Suboptimal", "Critical"))
        self.assertIsNone(result["accuracy"])
        with self.assertRaisesRegex(ValueError, "not explicitly held out"):
            compare(model, samples, "grow")

    def test_holdout_cannot_remove_only_training_class(self):
        samples, summary = audit_pilot(self.csv_path, ["session.csv#2"])
        with self.assertRaisesRegex(ValueError, "after holdout"):
            fit_pilot(samples, summary, Path(self.directory.name) / "bad.json.gz", ["grow"])


if __name__ == "__main__":
    unittest.main()
