"""Check the guarded Pi spike edits without loading hardware modules."""

import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_rf_spike_guard import PATCHES, apply, prepare, transform


class RFSpikeGuardPatchTests(unittest.TestCase):
    def test_both_edits_are_syntax_valid_and_guarded(self):
        for name, old, new in PATCHES:
            with self.subTest(name=name):
                source = "def check(sensor, status):\n    if (False\n                " + old + "\n        return True\n"
                updated = transform(source, old, new, name)
                self.assertIn('sensor.get("spike") is True', updated)
                with self.assertRaises(ValueError):
                    transform(updated, old, new, name)

    def test_apply_backs_up_both_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = {}
            for name, old, _ in PATCHES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                source = "def check(sensor, status):\n    if (False\n                " + old + "\n        return True\n"
                path.write_text(source, encoding="utf-8")
                originals[name] = source
            self.assertEqual(len(prepare(root)), 2)
            backups = apply(root)
            self.assertEqual(len(backups), 2)
            for (name, _, new), backup in zip(PATCHES, backups):
                self.assertEqual(backup.read_text(encoding="utf-8"), originals[name])
                self.assertIn(new, (root / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
