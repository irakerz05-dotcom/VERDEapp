"""Six fixed planting records and camera-to-slot mapping; no Pi hardware."""

import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from deploy import apply_pi_six_plant_slots as installer
from deploy import pi_plant_slots_six as records


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
            "test_six_fusion", DEPLOY / "pi_fusion_six.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, Result


class SixPlantTests(unittest.TestCase):
    def test_existing_dates_one_through_six_survive_and_old_rows_are_hidden(self):
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
                ])
                connection.commit()
            finally:
                connection.close()
            store = records.PlantSlotStore(path)
            result = store.list(today=date(2026, 10, 29))
            self.assertEqual(result["slot_count"], 6)
            self.assertEqual([item["slot"] for item in result["slots"]], list(range(1, 7)))
            self.assertEqual(result["slots"][0]["planted_on"], "2026-10-01")
            self.assertEqual(result["slots"][5]["planted_on"], "2026-10-02")
            with self.assertRaises(ValueError):
                store.clear(7)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute(
                    "SELECT planted_on FROM plant_slots_v2 WHERE slot=7").fetchone()[0],
                    "2026-10-03")
            finally:
                connection.close()

    def test_six_camera_positions_map_left_to_right_without_shifting(self):
        fusion, Result = load_fusion()
        plants = []
        for y in (20, 80):
            for x in (10, 50, 90):
                plants.append({"box_xyxy": [x - 5, y - 5, x + 5, y + 5],
                               "visual_condition": "Healthy", "condition_confidence": 0.9})
        mapped = fusion.detections_by_slot({"image_size": [100, 100], "plants": plants})
        self.assertEqual(sorted(mapped), [1, 2, 3, 4, 5, 6])
        without_p2 = plants[:1] + plants[2:]
        mapped = fusion.detections_by_slot({"image_size": [100, 100], "plants": without_p2})
        output = fusion.fuse_plant_slots(Result("READY", "Optimal"), mapped)
        self.assertEqual(output[1]["status"], "NO DETECTION")
        self.assertEqual(output[2]["slot"], 3)
        self.assertEqual(output[5]["slot"], 6)

    def test_guarded_installer_accepts_only_reviewed_ten_slot_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app/web").mkdir(parents=True)
            (root / "app/fusion").mkdir(parents=True)
            (root / "app/web/__init__.py").write_text(
                "from app.plant_slots import PlantSlotStore\n")
            (root / "app/service.py").write_text(
                "from app.fusion.slots import fuse_vision_artifact\n")
            for source, target in (("pi_plant_slots_ten.py", "app/plant_slots.py"),
                                   ("pi_fusion_ten.py", "app/fusion/slots.py")):
                (root / target).write_text((DEPLOY / source).read_text(encoding="utf-8"),
                                           encoding="utf-8")
            self.assertEqual(len(installer.plan(root)), 2)
            (root / "app/fusion/slots.py").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "differs"):
                installer.plan(root)


if __name__ == "__main__":
    unittest.main()
