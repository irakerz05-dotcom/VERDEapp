"""Exercise the guarded service change without touching GPIO."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from deploy.apply_pi_auto_mode_recovery import EARLY_NEW, MARKER, plan


class AutoModeRecoveryPatchTests(unittest.TestCase):
    def test_recovery_from_critical_uses_current_fresh_water(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Path(folder) / "service.py"
            service.write_text("class Service:\n    def sample(self):\n" + EARLY_NEW + "\n")
            updated = plan(service).decode("utf-8")
            self.assertIn(MARKER, updated)
            service.write_text(updated)
            self.assertIsNone(plan(service))

            namespace = {
                "FULL": "Full Automation Mode",
                "SEMI": "Semi-Automation Mode",
            }
            exec(updated, namespace)

            def evaluate(mode, snapshot, water, plant, camera, limits, error, *, pest):
                return {"active_mode": mode, "override": water.value == "Critical",
                        "hold_reason": "stale" if snapshot.get("stale") else None}

            namespace["evaluate_live"] = evaluate
            instance = namespace["Service"]()
            instance.selected_mode = namespace["SEMI"]
            instance.config = {"limits": {}}
            instance.database_error = None
            events = []
            instance.event = lambda *args: events.append(args)
            namespace.update(live_snapshot={}, experimental_water=SimpleNamespace(value="Critical"),
                             plant=None, camera=None, pest=None)
            instance.sample()
            self.assertEqual(instance.selected_mode, namespace["SEMI"])
            namespace["experimental_water"] = SimpleNamespace(value="Suboptimal")
            namespace["live_snapshot"] = {"stale": True}
            instance.sample()
            self.assertEqual(instance.selected_mode, namespace["SEMI"])
            namespace["live_snapshot"] = {}
            instance.sample()
            self.assertEqual(instance.selected_mode, namespace["FULL"])
            self.assertEqual(len(events), 1)
            instance.sample()
            self.assertEqual(len(events), 1)

    def test_unknown_installed_service_refuses_partial_patch(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Path(folder) / "service.py"
            service.write_text("class Service:\n    def sample(self):\n" + EARLY_NEW + "\n")
            updated = plan(service).decode("utf-8")
            with self.assertRaisesRegex(ValueError, "mode anchor"):
                service.write_text("class Service:\n    def sample(self):\n        pass\n")
                plan(service)


if __name__ == "__main__":
    unittest.main()
