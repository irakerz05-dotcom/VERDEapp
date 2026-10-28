"""Guarded Pi installer must not silently alter an unexpected service."""

import unittest

from deploy.apply_pi_live_automation_mode import (
    CALL_NEW, CALL_OLD, IMPORT_NEW, IMPORT_OLD, plan,
)


class InstallerTests(unittest.TestCase):
    def test_exact_anchors_and_idempotence(self):
        service = IMPORT_OLD + "\nclass Service:\n    def sample(self):\n" + CALL_OLD + "\n"
        module = "def evaluate_live():\n    return None\n"
        updated = plan(service, module)
        self.assertIn(IMPORT_NEW, updated)
        self.assertIn(CALL_NEW, updated)
        self.assertNotIn(CALL_OLD, updated)
        self.assertEqual(plan(updated, module), updated)

    def test_changed_service_anchor_is_rejected(self):
        with self.assertRaises(ValueError):
            plan(IMPORT_OLD + "\n# unknown mode flow\n", "pass\n")


if __name__ == "__main__":
    unittest.main()
