import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_pump_dose_settings as installer


SOURCE = Path(__file__).resolve().parents[1] / "deploy"


class DoseSettingsPatchTests(unittest.TestCase):
    def test_guarded_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/automation").mkdir(parents=True)
            (root / "app/web").mkdir(parents=True)
            (root / "app/service.py").write_text(
                "# VERDE-PUMP-RUNTIME-v1\nclass Service:\n" + installer.SERVICE_ANCHOR + "\n", encoding="utf-8")
            (root / "app/web/__init__.py").write_text("class Handler:\n    def do_POST(self):\n        if True:\n            if True:\n" + installer.WEB_ANCHOR + "\n", encoding="utf-8")
            old_runtime = (SOURCE / "pi_pump_runtime.py").read_text(encoding="utf-8")
            (root / "app/automation/pump_runtime.py").write_text(old_runtime, encoding="utf-8")
            changes = installer.plan(root, SOURCE)
            self.assertEqual(len(changes), 3)  # service, web, new settings module
            for path, content in changes:
                path.write_text(content, encoding="utf-8")
            self.assertEqual(installer.plan(root, SOURCE), [])

    def test_rejects_unreviewed_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/automation").mkdir(parents=True)
            (root / "app/web").mkdir(parents=True)
            (root / "app/service.py").write_text("# VERDE-PUMP-RUNTIME-v1\nclass Service:\n" + installer.SERVICE_ANCHOR, encoding="utf-8")
            (root / "app/web/__init__.py").write_text("class Handler:\n    def do_POST(self):\n        if True:\n            if True:\n" + installer.WEB_ANCHOR, encoding="utf-8")
            (root / "app/automation/pump_runtime.py").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewed"):
                installer.plan(root, SOURCE)


if __name__ == "__main__":
    unittest.main()
