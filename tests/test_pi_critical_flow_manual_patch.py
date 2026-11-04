"""Guarded Critical confirmation installer validation without Pi hardware."""

import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_critical_flow_manual as installer


class CriticalFlowPatchTests(unittest.TestCase):
    def test_reviewed_source_is_idempotent_and_rejects_unknown_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pump_runtime.py"
            target.write_bytes(installer.SOURCE.read_bytes())
            self.assertEqual(installer.plan(target=target), [])
            target.write_text("different backend")
            with self.assertRaisesRegex(ValueError, "differs from reviewed"):
                installer.plan(target=target)


if __name__ == "__main__":
    unittest.main()
