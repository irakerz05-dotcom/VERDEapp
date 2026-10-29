"""Eight fixed NFT positions and non-destructive planting-date migration."""

import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from deploy import apply_pi_eight_plant_slots as installer
from deploy import pi_plant_slots_eight as records


DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def load_fusion():
    class Result:
        def __init__(self, status, value=None, detail=None):
            self.status, self.value, self.detail = status, value, detail

    class TableFusion:
        def combine(self, water, vision):
            return Result("READY", "High", "Descriptive result")

    app = types.ModuleType("app")
    app.__path__ = []
    components = types.ModuleType("app.components")
    components.Result = Result
    fusion_package = types.ModuleType("app.fusion")
    fusion_package.__path__ = []
    fusion_package.TableFusion = TableFusion
    with patch.dict(sys.modules, {"app": app, "app.components": components,
                                  "app.fusion": fusion_package}):
        spec = importlib.util.spec_from_file_location(
            "test_eight_fusion", DEPLOY / "pi_fusion_eight.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, Result


class EightPlantTests(unittest.TestCase):
    def test_new_slots_work_when_previous_table_allowed_only_six(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verde.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("""CREATE TABLE plant_slots_v2 (
                    slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 6),
                    planted_on TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                connection.execute("INSERT INTO plant_slots_v2 VALUES (1, '2026-10-01', '2026-10-01')")
                connection.commit()
            finally:
                connection.close()
            store = records.PlantSlotStore(path)
            self.assertEqual(store.list()["slots"][0]["planted_on"], "2026-10-01")
            self.assertEqual(store.set_date(7, "2026-10-02")["slots"][6]["planted_on"],
                             "2026-10-02")

    def test_existing_dates_migrate_once_and_original_table_remains(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "verde.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("""CREATE TABLE plant_slots_v2 (
                    slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 10),
                    planted_on TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                connection.executemany("INSERT INTO plant_slots_v2 VALUES (?, ?, ?)", [
                    (1, "2026-10-01", "2026-10-01"),
                    (6, "2026-10-02", "2026-10-02"),
                    (7, "2026-10-03", "2026-10-03"),
                    (8, "2026-10-04", "2026-10-04"),
                    (9, "2026-10-05", "2026-10-05"),
                ])
                connection.commit()
            finally:
                connection.close()
            store = records.PlantSlotStore(path)
            result = store.list(today=date(2026, 10, 29))
            self.assertEqual(result["slot_count"], 8)
            self.assertEqual([item["slot"] for item in result["slots"]], list(range(1, 9)))
            self.assertIsNone(result["slots"][7]["planted_on"])
            store.set_date(8, "2026-10-06")
            self.assertEqual(store.list()["slots"][7]["planted_on"], "2026-10-06")
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute(
                    "SELECT planted_on FROM plant_slots_v2 WHERE slot=8").fetchone()[0],
                    "2026-10-04")
                self.assertEqual(connection.execute(
                    "SELECT planted_on FROM plant_slots_v2 WHERE slot=9").fetchone()[0],
                    "2026-10-05")
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM plant_slots_v3").fetchone()[0], 3)
            finally:
                connection.close()

    def test_eight_camera_positions_keep_missing_slots_fixed(self):
        fusion, Result = load_fusion()
        plants = [{"box_xyxy": [x - 3, y - 3, x + 3, y + 3],
                   "visual_condition": "Healthy", "condition_confidence": 0.9}
                  for y in (20, 80) for x in (12, 37, 62, 87)]
        mapped = fusion.detections_by_slot({"image_size": [100, 100], "plants": plants})
        self.assertEqual(sorted(mapped), list(range(1, 9)))
        without_p2 = plants[:1] + plants[2:]
        mapped = fusion.detections_by_slot({"image_size": [100, 100], "plants": without_p2})
        output = fusion.fuse_plant_slots(Result("READY", "Optimal"), mapped)
        self.assertEqual(output[1]["status"], "NO DETECTION")
        self.assertEqual(output[2]["slot"], 3)
        self.assertEqual(output[7]["slot"], 8)

    def test_installer_accepts_reviewed_six_slot_modules_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/web").mkdir(parents=True)
            (root / "app/fusion").mkdir(parents=True)
            (root / "app/web/__init__.py").write_text(
                "from app.plant_slots import PlantSlotStore\n", encoding="utf-8")
            (root / "app/service.py").write_text(
                "from app.fusion.slots import fuse_vision_artifact\n", encoding="utf-8")
            for source, target in (("pi_plant_slots_six.py", "app/plant_slots.py"),
                                   ("pi_fusion_six.py", "app/fusion/slots.py")):
                (root / target).write_text((DEPLOY / source).read_text(encoding="utf-8"),
                                           encoding="utf-8")
            self.assertEqual(len(installer.plan(root)), 2)
            (root / "app/fusion/slots.py").write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                installer.plan(root)


if __name__ == "__main__":
    unittest.main()
