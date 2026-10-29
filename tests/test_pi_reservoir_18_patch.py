"""Guarded 18 L policy update; no GPIO access."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy import apply_pi_reservoir_18 as installer


SOURCE = Path(__file__).resolve().parents[1] / "deploy"


class Reservoir18PatchTests(unittest.TestCase):
    def test_current_policy_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app/automation"
            target.mkdir(parents=True)
            for name in ("pump_runtime.py", "pump_decision.py"):
                (target / name).write_text((SOURCE / ("pi_" + name)).read_text(encoding="utf-8"),
                                           encoding="utf-8")
            self.assertEqual(installer.plan(Path(directory), SOURCE), [])

    def test_unreviewed_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app/automation"
            target.mkdir(parents=True)
            for name in ("pump_runtime.py", "pump_decision.py"):
                (target / name).write_text("unreviewed source", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                installer.plan(Path(directory), SOURCE)

    def test_backend_update_requires_disarmed_stopped_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / "gateway.py"
            gateway.write_text((SOURCE / "pi_auto_pump_driver.py").read_text(encoding="utf-8"),
                               encoding="utf-8")
            with patch.object(installer, "GATEWAY", gateway):
                for state in ({"armed": True, "in_progress": False, "circulation": "RUN"},
                              {"armed": False, "in_progress": False, "circulation": "RUN"},
                              {"armed": False, "in_progress": True, "circulation": "STOP"}):
                    with patch.object(installer.subprocess, "run", return_value=type("Result", (), {
                        "stdout": json.dumps(state)
                    })()):
                        with self.assertRaisesRegex(ValueError, "disarmed|STOP"):
                            installer.require_disarmed_gateway(SOURCE)
                with patch.object(installer.subprocess, "run", return_value=type("Result", (), {
                    "stdout": json.dumps({"armed": False, "in_progress": False,
                                          "circulation": "STOP"})
                })()):
                    installer.require_disarmed_gateway(SOURCE)


if __name__ == "__main__":
    unittest.main()
