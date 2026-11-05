import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from deploy.apply_pi_pest_only_overlay import patch_web, plan
from deploy.pi_pest_only_overlay import pest_overlay


class Store:
    def __init__(self, report):
        self.report = report

    def read(self):
        return self.report


class Camera:
    def __init__(self, timestamp):
        self.timestamp = timestamp

    def history(self):
        return [{"id": "capture-3.jpg", "capture_timestamp": self.timestamp,
                 "url": "/api/camera/history/capture-3.jpg"}]

    def history_frame(self, identifier):
        return b"\xff\xd8photo\xff\xd9" if identifier == "capture-3.jpg" else None


class PestOverlayTests(unittest.TestCase):
    def setUp(self):
        self.source_time = datetime(2026, 11, 5, 10, 13, 57, tzinfo=timezone.utc).timestamp()
        self.report = {"generated_at": "2026-11-05T10:14:02+00:00",
                       "source_mtime_ns": int(self.source_time * 1e9),
                       "image_size": [4608, 2592],
                       "plants": [{"possible_pests": [
                           {"class_name": "Pest Detected", "box_xyxy": [100, 200, 180, 280],
                            "confidence": 0.8},
                           {"class_name": "Pest Detected", "box_xyxy": [-1, 200, 180, 280],
                            "confidence": 0.9}]}]}

    def test_matches_source_photo_and_returns_only_pest_boxes(self):
        camera = Camera("2026-11-05T10:13:57.054+00:00")
        result = pest_overlay(Store(self.report), camera)
        self.assertEqual(result["capture_id"], "capture-3.jpg")
        self.assertEqual(result["boxes"], [{"box_xyxy": [100, 200, 180, 280], "confidence": 0.8}])
        self.assertEqual(result["image_size"], [4608, 2592])

    def test_rejects_different_capture_and_stale_source(self):
        with self.assertRaises(LookupError):
            pest_overlay(Store(self.report), Camera("2026-11-05T10:14:09+00:00"))
        changed = {**self.report, "source_mtime_ns": None}
        with self.assertRaises(ValueError):
            pest_overlay(Store(changed), Camera("2026-11-05T10:13:57.054+00:00"))

    def test_guarded_web_route_keeps_main_annotated_route(self):
        source = ('from app.plant_slots import PlantSlotStore\n'
                  'def route(path, service):\n'
                  '            if path == "/api/camera/annotated":\n'
                  '                frame = service.annotated_camera_frame()\n')
        patched = patch_web(source)
        self.assertEqual(patch_web(patched), patched)
        self.assertIn('if path == "/api/camera/pest-overlay":', patched)
        self.assertIn('frame = service.annotated_camera_frame()', patched)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "app/web/__init__.py"
            target.parent.mkdir(parents=True)
            target.write_text(source, encoding="utf-8")
            self.assertEqual(len(plan(root)), 2)


if __name__ == "__main__":
    unittest.main()
