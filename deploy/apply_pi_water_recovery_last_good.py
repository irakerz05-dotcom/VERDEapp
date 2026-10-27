#!/usr/bin/env python3
"""Guardedly expose the last valid water temperature during short recovery.

The current reading stays null. The prototype RF alone may use a last-good
value for 90 seconds; automation, safety, and fusion reliability stay unchanged.
--check is read-only. --apply backs up files and never restarts the service.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
SENSOR_MARKER = "# VERDE-LAST-GOOD-WATER-v1"
RF_MARKER = "# VERDE-RECOVERING-WATER-RF-v1"
SERVICE_MARKER = "# VERDE-RECOVERING-WATER-SERVICE-v1"

SENSOR_WRAPPER = '''    # VERDE-LAST-GOOD-WATER-v1
    _read_water_temperature_without_last_good = _read_water_temperature

    def _read_water_temperature(self):
        reading = self._read_water_temperature_without_last_good()
        status = str(reading.get("status") or "")
        if status.startswith("OK") and reading.get("read_error") is None:
            value = reading.get("value_C")
            measured_at = reading.get("read_timestamp")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and measured_at:
                self._last_good_water_temperature = (value, measured_at)
        elif status.startswith("RECOVERING"):
            prior = getattr(self, "_last_good_water_temperature", None)
            if prior is not None:
                reading["last_valid_value_C"] = prior[0]
                reading["last_valid_measured_at"] = prior[1]
        return reading

'''

RF_HELPERS = '''# VERDE-RECOVERING-WATER-RF-v1
MAX_RECOVERY_AGE_SECONDS = 90


def recovering_water_value(sensor, clock=None):
    """Accept a recent last-good temperature only during transient recovery."""
    if not isinstance(sensor, dict) or not str(sensor.get("status") or "").startswith("RECOVERING"):
        return None
    if (sensor.get("value_C") is not None or not sensor.get("read_error")
            or sensor.get("stale") is True or sensor.get("retained") is True):
        return None
    value = sensor.get("last_valid_value_C")
    timestamp = sensor.get("last_valid_measured_at")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if not DOMAINS["water_temperature"][0] <= value <= DOMAINS["water_temperature"][1]:
        return None
    try:
        measured = datetime.fromisoformat(timestamp)
        if measured.tzinfo is None:
            return None
        age = ((clock or datetime.now(timezone.utc)) - measured.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None
    return float(value) if 0 <= age <= MAX_RECOVERY_AGE_SECONDS else None


def recovering_inputs(snapshot, clock=None):
    sensors = snapshot.get("sensors") if isinstance(snapshot, dict) else None
    sensor = sensors.get("water_temperature") if isinstance(sensors, dict) else None
    return ("water_temperature",) if recovering_water_value(sensor, clock) is not None else ()


'''


def replace_once(source, old, new, label):
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected exactly one reviewed source anchor")
    return source.replace(old, new, 1)


def patch_sensor(source):
    if SENSOR_MARKER in source:
        if source.count(SENSOR_MARKER) != 1 or source.count('"last_valid_value_C"') != 1:
            raise ValueError("Water last-good patch is incomplete")
        compile(source, "verde_sensor_service.py", "exec")
        return source
    if (source.count("    def _read_water_temperature(self):\n") != 1
            or source.count("    def _safe_analog(self, channel):\n") != 1
            or "# VERDE-SENSOR-RECOVERY-v3" not in source):
        raise ValueError("Expected installed Pi water retry methods are missing")
    source = replace_once(source, "    def _safe_analog(self, channel):\n",
                          SENSOR_WRAPPER + "    def _safe_analog(self, channel):\n", "water wrapper")
    compile(source, "verde_sensor_service.py", "exec")
    return source


def patch_rf(source):
    if RF_MARKER in source:
        if source.count(RF_MARKER) != 1 or "EXPERIMENTAL_RECOVERING" not in source:
            raise ValueError("Recovering RF patch is incomplete")
        compile(source, "app/ml/water_quality/prototype_rf.py", "exec")
        return source
    source = replace_once(source,
        'DOMAINS = {"ph": (0, 14), "ec": (0, 10), "water_temperature": (0, 50),\n'
        '           "turbidity": (0, 100)}\n\n\n',
        'DOMAINS = {"ph": (0, 14), "ec": (0, 10), "water_temperature": (0, 50),\n'
        '           "turbidity": (0, 100)}\n\n\n' + RF_HELPERS, "RF recovery helpers")
    source = replace_once(source,
        '        if (not valid_status or sensor.get("valid") is False or sensor.get("retained") is True\n'
        '                or sensor.get("stale") is True or sensor.get("read_error") is not None):\n'
        '            return None\n'
        '        value = sensor.get(FIELDS[name])\n',
        '        if name == "water_temperature" and status.startswith("RECOVERING"):\n'
        '            value = recovering_water_value(sensor, clock)\n'
        '        else:\n'
        '            if (not valid_status or sensor.get("valid") is False or sensor.get("retained") is True\n'
        '                    or sensor.get("stale") is True or sensor.get("read_error") is not None):\n'
        '                return None\n'
        '            value = sensor.get(FIELDS[name])\n', "RF feature validation")
    source = replace_once(source, '    def classify(self, features, fluctuating=()):\n',
                          '    def classify(self, features, fluctuating=(), recovering=()):\n', "RF classifier signature")
    source = replace_once(source, '        return Result("EXPERIMENTAL", predicted, detail=detail)\n',
        '        if recovering:\n'
        '            detail += (" Provisional: using the last valid " + ", ".join(recovering)\n'
        '                       + " reading during sensor recovery, not a live measurement."\n'
        '                       " Safety and fusion reliability still treat the sensor as faulty.")\n'
        '        return Result("EXPERIMENTAL_RECOVERING" if recovering else "EXPERIMENTAL", predicted,\n'
        '                      detail=detail)\n', "RF provisional result")
    compile(source, "app/ml/water_quality/prototype_rf.py", "exec")
    return source


def patch_service(source):
    if SERVICE_MARKER in source:
        if source.count(SERVICE_MARKER) != 1 or "recovering=recovering_inputs(live_snapshot)" not in source:
            raise ValueError("Recovering service patch is incomplete")
        compile(source, "app/service.py", "exec")
        return source
    source = replace_once(source,
        'from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs\n',
        'from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs, recovering_inputs\n',
        "RF service import")
    source = replace_once(source,
        '            experimental_water = guarded(lambda: self.prototype_classifier.classify(\n'
        '                features_from_live(live_snapshot), fluctuating=fluctuating_inputs(live_snapshot)),\n',
        '            ' + SERVICE_MARKER + '\n'
        '            experimental_water = guarded(lambda: self.prototype_classifier.classify(\n'
        '                features_from_live(live_snapshot), fluctuating=fluctuating_inputs(live_snapshot),\n'
        '                recovering=recovering_inputs(live_snapshot)),\n', "RF service call")
    compile(source, "app/service.py", "exec")
    return source


FILES = {
    "verde_sensor_service.py": patch_sensor,
    "app/ml/water_quality/prototype_rf.py": patch_rf,
    "app/service.py": patch_service,
}


def prepare(root=BACKEND):
    planned = {}
    for relative, patch in FILES.items():
        path = root / relative
        planned[path] = patch(path.read_text(encoding="utf-8"))
    return planned


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    root = args.target.resolve()
    planned = prepare(root)
    changes = [(path, content) for path, content in planned.items()
               if path.read_text(encoding="utf-8") != content]
    if args.check:
        print(f"Ready: {len(changes)} guarded backend updates; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_water_last_good_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, content in changes:
        atomic_write(path, content)
        print(f"Updated: {path}")
    print("Service was NOT restarted. GPIO, calibration, SMS and safety code were not changed.")


if __name__ == "__main__":
    main()
