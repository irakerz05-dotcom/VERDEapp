"""The reservoir correction only replaces reviewed pump policy modules."""

import tempfile
import unittest
from pathlib import Path

from deploy.apply_pi_reservoir_125 import plan


SOURCE = Path(__file__).resolve().parents[1] / "deploy"


class ReservoirPatchTests(unittest.TestCase):
    def test_plan_is_idempotent_for_installed_new_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app/automation"
            target.mkdir(parents=True)
            for name in ("pump_runtime.py", "pump_decision.py"):
                (target / name).write_text((SOURCE / ("pi_" + name)).read_text(encoding="utf-8"),
                                           encoding="utf-8")
            self.assertEqual(plan(Path(directory), SOURCE), [])

    def test_unreviewed_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app/automation"
            target.mkdir(parents=True)
            for name in ("pump_runtime.py", "pump_decision.py"):
                (target / name).write_text("unreviewed source", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                plan(Path(directory), SOURCE)


if __name__ == "__main__":
    unittest.main()
