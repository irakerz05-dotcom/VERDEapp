"""The farmer-confirmation installer changes only reviewed service routes."""

import unittest

from deploy.apply_pi_pump_confirmation import (
    SERVICE_OLD, SERVICE_NEW, WEB_OLD, WEB_NEW, plan,
)
from pathlib import Path


DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


class ConfirmationPatchTests(unittest.TestCase):
    def test_route_and_service_patch_are_idempotent(self):
        service = "# VERDE-PUMP-RUNTIME-v1\nclass Service:\n" + SERVICE_OLD + "\n"
        web = "class Handler:\n    def do_POST(self):\n        path = '/api/confirm'\n        service = None\n        if False:\n" + WEB_OLD + "\n"
        runtime = (DEPLOY / "pi_pump_runtime.py").read_text(encoding="utf-8")
        decision = (DEPLOY / "pi_pump_decision.py").read_text(encoding="utf-8")
        changed = plan(service, web, runtime, decision)
        self.assertIn(SERVICE_NEW, changed[0])
        self.assertIn(WEB_NEW, changed[1])
        self.assertEqual(plan(*changed, runtime, decision), changed)

    def test_missing_anchor_stops_patch(self):
        runtime = (DEPLOY / "pi_pump_runtime.py").read_text(encoding="utf-8")
        decision = (DEPLOY / "pi_pump_decision.py").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            plan("# VERDE-PUMP-RUNTIME-v1", WEB_OLD, runtime, decision)


if __name__ == "__main__":
    unittest.main()
