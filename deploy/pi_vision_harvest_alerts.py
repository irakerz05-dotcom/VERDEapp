"""Camera-only harvest notices for the six fixed NFT zones."""

import math


ZONE_SLOTS = {f"{row}{column}": start + column - 1
              for row, start in (("T", 1), ("B", 4)) for column in (1, 2, 3)}


def harvest_ready_slots(report):
    """Return P numbers only when the fresh worker report is internally consistent."""
    if not isinstance(report, dict):
        return []
    aggregate = report.get("plant_condition")
    plants = report.get("plants")
    if (not isinstance(aggregate, dict) or aggregate.get("status") != "READY"
            or not isinstance(plants, list)):
        return []
    classes = aggregate.get("classifications")
    harvest = classes.get("Harvest-Ready") if isinstance(classes, dict) else None
    expected = harvest.get("count") if isinstance(harvest, dict) else None
    if type(expected) is not int or not 0 <= expected <= 6:
        return []
    seen = set()
    ready = []
    for plant in plants:
        if not isinstance(plant, dict):
            return []
        zone = plant.get("zone_id")
        if zone not in ZONE_SLOTS or zone in seen:
            return []
        seen.add(zone)
        if plant.get("harvest_ready") is not True:
            continue
        confidence = plant.get("harvest_confidence")
        threshold = plant.get("harvest_threshold_provisional")
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1
                for value in (confidence, threshold)) or confidence < threshold):
            return []
        ready.append(ZONE_SLOTS[zone])
    return sorted(ready) if len(ready) == expected else []
