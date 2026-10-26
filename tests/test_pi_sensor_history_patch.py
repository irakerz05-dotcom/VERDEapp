"""The Pi installer must stop when reviewed backend anchors differ."""

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/apply_pi_sensor_history.py"
SPEC = importlib.util.spec_from_file_location("apply_pi_sensor_history", SCRIPT)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)

SERVICE = (
    "from app.database import Database\n"
    "class Service:\n"
    "    def sample(self):\n"
    "        with self.lock:\n"
    "            self.db_call(lambda: self.database.snapshot(self.state))\n"
    "            if self.database_error:\n"
    "                pass\n"
)
WEB = (
    "class Handler:\n"
    "    def do_GET(self):\n"
    "        with self.lock:\n"
    '            if path in ("/api/events", "/api/history"):\n'
    "                pass\n"
)


class InstallerTests(unittest.TestCase):
    def test_reviewed_anchors_are_guarded_and_repeatable(self):
        service = INSTALLER.patch_service(SERVICE)
        web = INSTALLER.patch_web(WEB)
        self.assertIn(INSTALLER.SERVICE_CALL, service)
        self.assertIn(INSTALLER.WEB_ROUTE, web)
        self.assertEqual(INSTALLER.patch_service(service), service)
        self.assertEqual(INSTALLER.patch_web(web), web)

    def test_unknown_service_or_web_shape_stops(self):
        with self.assertRaises(ValueError):
            INSTALLER.patch_service(SERVICE.replace("self.database.snapshot(self.state)", "self.database.other()"))
        with self.assertRaises(ValueError):
            INSTALLER.patch_web(WEB.replace('("/api/events", "/api/history")', '("/api/events",)'))


if __name__ == "__main__":
    unittest.main()
