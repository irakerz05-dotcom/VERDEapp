"""Six active slots preserve prior dates and map detections to fixed rows."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from deploy import apply_pi_six_plant_slots_v4 as installer
from deploy import pi_plant_slots_six_v4 as records
from tests.test_pi_six_plant_slots import load_fusion


DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


class SixSlotV4Tests(unittest.TestCase):
    def test_migrates_first_six_and_archives_seven_eight(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "verde.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE plant_slots_v3 (slot INTEGER PRIMARY KEY, planted_on TEXT, updated_at TEXT)")
                connection.executemany("INSERT INTO plant_slots_v3 VALUES (?, ?, ?)", [
                    (1, "2026-10-01", "2026-10-01"), (6, "2026-10-02", "2026-10-02"),
                    (7, "2026-10-03", "2026-10-03"), (8, "2026-10-04", "2026-10-04")])
                connection.commit()
            finally:
                connection.close()
            store = records.PlantSlotStore(path)
            result = store.list(today=date(2026, 11, 5))
            self.assertEqual(result["slot_count"], 6)
            self.assertEqual([row["slot"] for row in result["slots"]], list(range(1, 7)))
            self.assertEqual(result["slots"][0]["planted_on"], "2026-10-01")
            with self.assertRaisesRegex(ValueError, "1 to 6"):
                store.set_date(7, "2026-10-05")
            store.swap(1, 6)
            self.assertEqual(store.list()["slots"][0]["planted_on"], "2026-10-02")
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT planted_on FROM plant_slots_v3 WHERE slot=8").fetchone()[0], "2026-10-04")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM plant_slots_v4").fetchone()[0], 2)
            finally:
                connection.close()

    def test_fixed_three_by_two_camera_mapping(self):
        fusion, Result = load_fusion()
        plants = [{"box_xyxy": [x - 3, y - 3, x + 3, y + 3],
                   "visual_condition": "Healthy", "condition_confidence": 0.9}
                  for y in (20, 80) for x in (16, 50, 84)]
        mapped = fusion.detections_by_slot({"image_size": [100, 100], "plants": plants})
        self.assertEqual(sorted(mapped), list(range(1, 7)))
        output = fusion.fuse_plant_slots(Result("READY", "Optimal"), mapped)
        self.assertEqual([row["slot"] for row in output], list(range(1, 7)))

    def test_installer_accepts_only_reviewed_eight_slot_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "app/web").mkdir(parents=True)
            (root / "app/fusion").mkdir(parents=True)
            (root / "app/web/__init__.py").write_text("from app.plant_slots import PlantSlotStore\n")
            (root / "app/service.py").write_text("from app.fusion.slots import fuse_vision_artifact\n")
            for source, target in (("pi_plant_slots_eight.py", "app/plant_slots.py"),
                                   ("pi_fusion_eight.py", "app/fusion/slots.py")):
                (root / target).write_text((DEPLOY / source).read_text(encoding="utf-8"), encoding="utf-8")
            changes = installer.plan(root)
            self.assertEqual(len(changes), 2)
            for target, proposed in changes:
                target.write_text(proposed, encoding="utf-8")
            self.assertEqual(installer.plan(root), [])
            (root / "app/fusion/slots.py").write_text("unknown change", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                installer.plan(root)


if __name__ == "__main__":
    unittest.main()
