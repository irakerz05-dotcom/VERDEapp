"""Persistent, bounded per-pump dose targets. No GPIO access."""

import json
import math
import os
import tempfile
from pathlib import Path


SETTINGS_PATH = Path("/home/verde/VERDE-Sensor-Integration/pump_dose_settings.json")
PUMPS = ("pump1", "pump2", "pump3")
FLOW_ML_PER_SECOND = 0.82
MAX_SECONDS = 4.5
MAX_ML = FLOW_ML_PER_SECOND * MAX_SECONDS
DEFAULT_ML = {pump: MAX_ML for pump in PUMPS}


def validate(volumes):
    if not isinstance(volumes, dict) or set(volumes) != set(PUMPS):
        raise ValueError("Provide a volume for each of Pumps 1, 2, and 3")
    result = {}
    for pump in PUMPS:
        value = volumes[pump]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 < value <= MAX_ML):
            raise ValueError(f"{pump} must be greater than 0 and at most {MAX_ML:.2f} mL")
        result[pump] = float(value)
    return result


def load(path=SETTINGS_PATH):
    try:
        with path.open(encoding="utf-8") as handle:
            record = json.load(handle)
    except FileNotFoundError:
        return dict(DEFAULT_ML)
    if not isinstance(record, dict) or set(record) != {"version", "volumes_ml"} or record["version"] != 1:
        raise ValueError("Pump dose settings record is invalid")
    return validate(record["volumes_ml"])


def save(volumes, path=SETTINGS_PATH):
    validated = validate(volumes)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "volumes_ml": validated}, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return validated


def durations(volumes):
    return {pump: ml / FLOW_ML_PER_SECOND for pump, ml in validate(volumes).items()}
