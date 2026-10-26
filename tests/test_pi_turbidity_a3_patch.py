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


if __name__ == "__main__":
    unittest.main()
