"""Guarded service update for automatic recovery after Critical manual dosing."""

import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_auto_flow_resume as installer


class FlowResumePatchTests(unittest.TestCase):
    def test_service_confirmation_patch_is_guarded_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Path(directory) / "service.py"
            runtime = Path(directory) / "pump_runtime.py"
            runtime.write_bytes(installer.SOURCE.read_bytes())
            service.write_text("class Service:\n" + installer.OLD_CONFIRM + "\n")
            changes = installer.plan(target=runtime, service=service)
            self.assertEqual([path for path, _ in changes], [service])
            service.write_bytes(changes[0][1])
            self.assertIn(installer.SERVICE_MARKER,
                          service.read_text(encoding="utf-8"))
            self.assertEqual(installer.plan(target=runtime, service=service), [])
            service.write_text("class Service:\n    def confirm(self): pass\n")
            with self.assertRaisesRegex(ValueError, "anchor differs"):
                installer.plan(target=runtime, service=service)


if __name__ == "__main__":
    unittest.main()
