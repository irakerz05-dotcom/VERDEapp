"""Apply the thesis fusion table independently to fixed NFT positions.

Camera-to-slot association happens upstream. Missing plants stay unclassified;
a true camera/vision fault is explicitly represented as Faulty Vision.
"""

import math

from app.components import Result
from app.fusion import TableFusion


SLOT_COUNT = 6
VISION_LABELS = frozenset(("Healthy", "Yellowing", "Wilting", "Harvest-Ready"))


def detections_by_slot(report, row_split=0.66):
    """Locate worker detections on a fixed two-row, three-column camera grid.

    The camera is fixed above the NFT. Slot numbers run left to right: P1–P3
    on top and P4–P6 below. A missing plant never shifts another slot.
    The split must be checked against a real annotated frame before deployment.
    """
    if not isinstance(report, dict):
        raise ValueError("Vision report must be an object")
    size, detections = report.get("image_size"), report.get("plants")
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)
            or not isinstance(detections, list)):
        raise ValueError("Vision report needs image_size and plants")
    width, height = size
    if not 0.5 <= row_split <= 0.8:
        raise ValueError("Invalid NFT row split")
    by_slot = {}
    for detection in detections:
        box = detection.get("box_xyxy") if isinstance(detection, dict) else None
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in box)):
            raise ValueError("Invalid lettuce bounding box")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError("Lettuce bounding box outside camera frame")
        x, y = (x1 + x2) / (2 * width), (y1 + y2) / (2 * height)
        column = min(2, int(3 * x))
        slot = (1 if y < row_split else 4) + column
        label = detection.get("visual_condition")
        confidence = detection.get("condition_confidence")
        valid = (label in VISION_LABELS and not isinstance(confidence, bool)
                 and isinstance(confidence, (int, float))
                 and math.isfinite(confidence) and 0 <= confidence <= 1)
        result = (Result("READY", label) if valid
                  else Result("FAULT / ERROR", "Faulty Vision",
                              detail="Detected plant has no valid condition classification"))
        if slot in by_slot:
            by_slot[slot] = Result("FAULT / ERROR", "Faulty Vision",
                                   detail="Multiple detections overlap one NFT slot")
        else:
            by_slot[slot] = result
    return by_slot


def fuse_vision_artifact(water, plant, camera, store):
    """Use one fresh worker report; reject a report from a different cycle.

    A camera/model fault follows Table 3. A report changed between the
    aggregate read and this read is withheld until the next service cycle.
    """
    if store is None:
        return None
    if plant.status == "FAULT / ERROR" or camera.get("status") == "FAULT / ERROR":
        return fuse_plant_slots(water, {},
                                vision_fault=plant.detail or camera.get("detail") or "Vision analysis failed")
    try:
        report = store.read()
        aggregate = report.get("plant_condition")
        if (not isinstance(aggregate, dict)
                or aggregate.get("status") != plant.status
                or aggregate.get("value") != plant.value
                or (camera.get("ai_capture_version") is not None
                    and report.get("generated_at") != camera["ai_capture_version"])):
            return None
        return fuse_plant_slots(water, detections_by_slot(report))
    except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
        return fuse_plant_slots(water, {}, vision_fault=f"{type(exc).__name__}: {exc}")


def fuse_plant_slots(water, plants_by_slot, vision_fault=None):
    """Return six descriptive results without changing water or actuator state.

    ``plants_by_slot`` maps fixed slot numbers to current Result classifications.
    Absent slots mean no detected plant; they do not imply a faulty camera.
    """
    if not isinstance(water, Result) or not isinstance(plants_by_slot, dict):
        raise TypeError("Water result and slot mapping are required")
    if any(type(slot) is not int or not 1 <= slot <= SLOT_COUNT
           for slot in plants_by_slot):
        raise ValueError("Plant slot must be an integer from 1 to 6")
    if vision_fault is not None and not isinstance(vision_fault, str):
        raise TypeError("Vision fault must be a string")

    fusion = TableFusion()
    output = []
    for slot in range(1, SLOT_COUNT + 1):
        vision = plants_by_slot.get(slot)
        if vision_fault:
            vision = Result("FAULT / ERROR", "Faulty Vision", detail=vision_fault)
        elif vision is None:
            output.append({"slot": slot, "sensor_status": water.value,
                           "plant_condition": None, "confidence": None,
                           "status": "NO DETECTION", "reason": "No plant classified in this slot."})
            continue
        elif (not isinstance(vision, Result) or vision.status != "READY"
              or vision.value not in VISION_LABELS):
            vision = Result("FAULT / ERROR", "Faulty Vision",
                            detail="No valid plant classification for this slot")

        result = fusion.combine(water, vision)
        output.append({"slot": slot, "sensor_status": water.value,
                       "plant_condition": vision.value,
                       "confidence": result.value, "status": result.status,
                       "reason": result.detail})
    return output
