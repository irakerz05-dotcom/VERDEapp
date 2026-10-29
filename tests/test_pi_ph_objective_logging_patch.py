import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_ph_objective_logging as installer


SOURCE = Path(__file__).resolve().parents[1] / "deploy"


class PhObjectiveLoggingPatchTests(unittest.TestCase):
    def test_patch_adds_database_event_after_successful_dose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/automation").mkdir(parents=True)
            service_path = root / "app/service.py"
            service_path.write_text(
                "# VERDE-PUMP-RUNTIME-v1\nclass Service:\n    def sample(self):\n"
                "        if True:\n            if True:\n" + installer.SERVICE_OLD + "\n",
                encoding="utf-8")
            for name, source_name in (("live_mode.py", "pi_live_automation_mode.py"),
                                      ("pump_runtime.py", "pi_pump_runtime.py")):
                (root / "app/automation" / name).write_text(
                    (SOURCE / source_name).read_text(encoding="utf-8"), encoding="utf-8")
            changes = installer.plan(root, SOURCE)
            self.assertEqual([path.name for path, _ in changes], ["service.py"])
            self.assertIn('self.event("actuator", "Automatic dose completed"', changes[0][1])
            for path, content in changes:
                path.write_text(content, encoding="utf-8")
            self.assertEqual(installer.plan(root, SOURCE), [])

    def test_rejects_unreviewed_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/automation").mkdir(parents=True)
            (root / "app/service.py").write_text(
                "# VERDE-PUMP-RUNTIME-v1\nclass Service:\n    def sample(self):\n"
                "        if True:\n            if True:\n" + installer.SERVICE_OLD,
                encoding="utf-8")
            (root / "app/automation/live_mode.py").write_text(
                (SOURCE / "pi_live_automation_mode.py").read_text(encoding="utf-8"), encoding="utf-8")
            (root / "app/automation/pump_runtime.py").write_text("unreviewed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed"):
                installer.plan(root, SOURCE)


if __name__ == "__main__":
    unittest.main()
