"""Guarded installer validation without changing the Pi backend."""

import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_ec_turn_taking as installer


class TurnTakingPatchTests(unittest.TestCase):
    def test_reviewed_sources_are_idempotent_and_reject_unknown_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name, (source_name, _) in installer.SOURCES.items():
                (target / name).write_bytes(
                    (Path(installer.__file__).parent / source_name).read_bytes())
            self.assertEqual(installer.plan(target=target), [])
            (target / "pump_decision.py").write_text("different backend")
            with self.assertRaisesRegex(ValueError, "differs from reviewed"):
                installer.plan(target=target)


if __name__ == "__main__":
    unittest.main()
