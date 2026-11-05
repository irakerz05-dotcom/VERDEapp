"""Expose V8 pest boxes for the exact raw camera capture they came from."""

from datetime import datetime
import math
import re


CAPTURE_ID = re.compile(r"capture-(?:[0-9]|1[01])\.jpg\Z")


def pest_overlay(vision_store, camera_capture):
    report = vision_store.read()
    size = report.get("image_size")
    source_ns = report.get("source_mtime_ns")
    if (not isinstance(size, list) or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)
            or type(source_ns) is not int or source_ns <= 0):
        raise ValueError("Invalid V8 camera source")
    source_seconds = source_ns / 1_000_000_000
    matches = []
    for capture in camera_capture.history():
        identifier = capture.get("id")
        if not isinstance(identifier, str) or not CAPTURE_ID.fullmatch(identifier):
            continue
        try:
            seconds = datetime.fromisoformat(capture["capture_timestamp"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        if abs(seconds - source_seconds) <= 1:
            matches.append(identifier)
    if len(matches) != 1 or camera_capture.history_frame(matches[0]) is None:
        raise LookupError("V8 source photo is no longer in camera history")

    boxes = []
    plants = report.get("plants")
    if not isinstance(plants, list):
        raise ValueError("Invalid V8 plant results")
    for plant in plants:
        if not isinstance(plant, dict) or not isinstance(plant.get("possible_pests"), list):
            raise ValueError("Invalid V8 pest results")
        for pest in plant["possible_pests"]:
            if not isinstance(pest, dict) or pest.get("class_name") != "Pest Detected":
                continue
            bounds = pest.get("box_xyxy")
            confidence = pest.get("confidence")
            if (not isinstance(bounds, list) or len(bounds) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
                    or type(confidence) not in (int, float) or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1):
                continue
            x1, y1, x2, y2 = bounds
            if not (0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1]):
                continue
            boxes.append({"box_xyxy": bounds, "confidence": confidence})
    return {"generated_at": report["generated_at"], "capture_id": matches[0],
            "image_size": size, "boxes": boxes}
