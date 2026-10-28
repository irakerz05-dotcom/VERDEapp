import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sms_spacing_installer", ROOT / "deploy/apply_pi_sms_spacing.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)
BACKEND = ROOT.parent / "verde-software-plant-slots"


class SMSSpacingInstallerTests(unittest.TestCase):
    def test_guarded_edits_match_reviewed_backend_and_are_idempotent(self):
        for relative, edits in (
            ("app/notifications/__init__.py", INSTALLER.NOTIFIER_EDITS),
            ("app/service.py", INSTALLER.SERVICE_EDITS),
        ):
            current = (BACKEND / relative).read_text(encoding="utf-8")
            old = current
            for original, replacement in reversed(edits):
                self.assertEqual(old.count(replacement), 1)
                old = old.replace(replacement, original, 1)
            restored = INSTALLER.plan(old, edits, relative)
            self.assertEqual(restored, current)
            self.assertEqual(INSTALLER.plan(restored, edits, relative), current)

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "reviewed anchor"):
            INSTALLER.plan("other code", INSTALLER.SERVICE_EDITS, "service.py")


if __name__ == "__main__":
    unittest.main()
