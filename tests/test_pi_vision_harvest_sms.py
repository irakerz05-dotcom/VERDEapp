"""Camera harvest SMS selects fixed zones, never planting age or fusion condition."""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from deploy import apply_pi_vision_harvest_sms as installer


ROOT = Path(__file__).resolve().parents[1]
BACKEND_FIXTURE = ROOT.parent / "verde-software-plant-slots"


def load_helper():
    spec = importlib.util.spec_from_file_location("vision_harvest_alerts", installer.HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VisionHarvestSMSTests(unittest.TestCase):
    def test_camera_flags_assign_p4_p5_p6_even_when_condition_is_healthy(self):
        helper = load_helper()
        report = {
            "plant_condition": {"status": "READY", "value": "Wilting",
                "classifications": {"Harvest-Ready": {"count": 3}}},
            "plants": [
                {"zone_id": zone, "visual_condition": "Healthy",
                 "harvest_ready": zone in {"B1", "B2", "B3"},
                 "harvest_confidence": .9, "harvest_threshold_provisional": .5}
                for zone in ("T1", "T2", "T3", "B1", "B2", "B3")],
        }
        self.assertEqual(helper.harvest_ready_slots(report), [4, 5, 6])
        report["plants"][3]["harvest_confidence"] = .1
        self.assertEqual(helper.harvest_ready_slots(report), [])
        report["plants"][3]["harvest_confidence"] = .9
        report["plants"][4]["zone_id"] = "B1"
        self.assertEqual(helper.harvest_ready_slots(report), [])

    def test_alerts_use_camera_flags_and_ignore_planting_age(self):
        helper = load_helper()
        source = installer.patch_policy(
            (BACKEND_FIXTURE / "app/notifications/alert_policy.py").read_text(encoding="utf-8"))
        source = source.replace(
            "from app.notifications.vision_harvest_alerts import harvest_ready_slots\n", "")
        namespace = {"harvest_ready_slots": helper.harvest_ready_slots}
        exec(source, namespace)
        report = {"plant_condition": {"status": "READY", "classifications": {
            "Harvest-Ready": {"count": 1}}}, "plants": [
            {"zone_id": "T2", "visual_condition": "Healthy", "harvest_ready": True,
             "harvest_confidence": .85, "harvest_threshold_provisional": .5}]}
        fusion = [{"slot": 2, "plant_condition": "Healthy", "status": "READY"}]
        issues = namespace["enrich_issues"](
            {"vision:harvest_ready": {"severity": "warning"}}, None, fusion, report)
        self.assertEqual(list(issues), ["vision:slot:2:harvest_ready"])
        self.assertEqual(namespace["enrich_issues"]({}, None, fusion), {})
        self.assertEqual(namespace["enrich_issues"](
            {}, None, [{"slot": 2, "plant_condition": "Harvest-Ready", "status": "READY",
                         "days_growing": 40}]), {})

    def test_installer_is_guarded_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in ("app/service.py", "app/notifications/alert_policy.py",
                             "app/notifications/sms_text.py"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(BACKEND_FIXTURE / relative, target)
            changes = installer.plan(root)
            self.assertEqual(len(changes), 4)
            for target, contents in changes:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
            self.assertEqual(installer.plan(root), [])
            policy = (root / "app/notifications/alert_policy.py").read_text()
            self.assertIn("harvest_ready_slots(vision_report)", policy)
            self.assertNotIn("planting date", policy)
            self.assertNotIn("days_growing", policy)
            sms = (root / "app/notifications/sms_text.py").read_text()
            self.assertIn("Harvest-Ready plant P{number}", sms)
            (root / "app/service.py").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                installer.plan(root)


if __name__ == "__main__":
    unittest.main()
