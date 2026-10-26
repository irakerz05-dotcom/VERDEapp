"""A3 migration rejects unexpected Pi source and keeps its backup."""

import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_turbidity_a3 import REPLACEMENTS, apply, transform


class A3PatchTests(unittest.TestCase):
    def source(self):
        return "\n".join(("# demo", *(f"# {old}" for old, _ in REPLACEMENTS))) + "\n"

    def test_transform_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verde_sensor_service.py"
            original = self.source()
            path.write_text(original)
            backup = apply(path)
            self.assertEqual(backup.read_text(), original)
            self.assertEqual(path.read_text(), transform(original))
            self.assertNotIn("ADS.P0", path.read_text())

    def test_unexpected_or_already_updated_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "anchor"):
            transform("# unrelated source\n")
        with self.assertRaisesRegex(ValueError, "anchor"):
            transform(transform(self.source()))

    def test_reverse_switch_restores_only_a0_anchors_and_backs_up_a3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verde_sensor_service.py"
            a3_source = transform(self.source())
            path.write_text(a3_source)
            backup = apply(path, channel="A0")
            self.assertEqual(backup.read_text(), a3_source)
            self.assertEqual(path.read_text(), self.source())
            with self.assertRaisesRegex(ValueError, "anchor"):
                transform(path.read_text(), channel="A0")


if __name__ == "__main__":
    unittest.main()
