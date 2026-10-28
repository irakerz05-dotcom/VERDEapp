#!/usr/bin/env python3
"""Fit a provisional A2 EC line to the saved standard and live tap-water meter.

The external meter read 0.138 mS/cm in the current tap-water sample. --check
changes nothing. --apply captures five distinct stable Pi acquisitions, saves
the new fit outside Git, backs up the sensor service, and never restarts it.
"""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
SOURCE = BACKEND / "verde_sensor_service.py"
OLD_RECORD = Path("/home/verde/ec_calibration_1467_27C_v2.json")
NEW_RECORD = Path("/home/verde/ec_calibration_two_point_20261028.json")
API = "http://127.0.0.1:8000/api/sensors/latest"
TAP_USCM = 138.0
HIGH_USCM = 1413.0
SAMPLES = 5
MAX_WAIT_SECONDS = 600


LOADER = '''def load_ec_two_point(path=EC_TWO_POINT_RECORD_PATH):
    with Path(path).open(encoding="utf-8") as handle:
        record = json.load(handle)
    if (record.get("calibration_status") != "PROVISIONAL TWO-POINT DIRECT EC"
            or record.get("formula") != "EC_uScm = max(0, slope * voltage_V + intercept)"):
        raise ValueError(f"{path}: invalid two-point EC calibration")
    coefficients = []
    for field in ("slope_uScm_per_V", "intercept_uScm"):
        value = record.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{path}: {field} must be a coefficient string")
        coefficient = float(value)
        if not math.isfinite(coefficient):
            raise ValueError(f"{path}: {field} is not finite")
        coefficients.append(coefficient)
    slope, intercept = coefficients
    if not 100 < slope < 10000 or not -5000 < intercept < 5000:
        raise ValueError(f"{path}: two-point EC coefficients outside guarded range")
    points = record.get("reference_points")
    if not isinstance(points, list) or len(points) != 2:
        raise ValueError(f"{path}: two reference points required")
    for point in points:
        voltage = point.get("filtered_voltage_V")
        target = point.get("ec_uScm")
        if (isinstance(voltage, bool) or not isinstance(voltage, (int, float))
                or isinstance(target, bool) or not isinstance(target, (int, float))
                or not math.isfinite(voltage) or not math.isfinite(target)
                or abs(slope * voltage + intercept - target) > 0.01):
            raise ValueError(f"{path}: reference points do not match coefficients")
    return slope, intercept


'''


def replace_once(source, old, new, label):
    if source.count(old) != 1 or new in source:
        raise ValueError(f"{label}: expected exactly one reviewed source anchor")
    return source.replace(old, new, 1)


def transform_source(source):
    if not re.search(r'"ec_tds"\s*,\s*AnalogIn\(self\.ads,\s*ADS\.P2\)', source):
        raise ValueError("EC acquisition is not on ADS1115 A2")
    if not re.search(r'(?m)^ADS1115_GAIN\s*=\s*1\s*$', source):
        raise ValueError("ADS1115 gain differs from the reviewed source")
    if (source.count("EC V2 post-hardware-fix") < 2
            or source.count("OK: ACCEPTED SINGLE-POINT DIRECT EC — POST-HARDWARE-FIX") != 1):
        raise ValueError("Expected installed V2 EC status fields")
    source = replace_once(
        source,
        'EC_RECORD_PATH = Path("/home/verde/ec_calibration_1467_27C_v2.json")',
        'EC_RECORD_PATH = Path("/home/verde/ec_calibration_1467_27C_v2.json")\n'
        'EC_TWO_POINT_RECORD_PATH = Path("/home/verde/ec_calibration_two_point_20261028.json")',
        "EC record path",
    )
    source = replace_once(source, "    return coefficient\n\n\ndef load_turbidity_reference",
                          "    return coefficient\n\n\n" + LOADER + "def load_turbidity_reference",
                          "EC loader insertion")
    source = replace_once(
        source,
        '        self.ec_scale = load_scale(\n'
        '            EC_RECORD_PATH, "ec_scale_uScm_per_V",\n'
        '            "EC_uScm = EC_SCALE * voltage_V",\n'
        '            {"ACCEPTED SINGLE-POINT DIRECT EC CALIBRATION — POST-HARDWARE-FIX"},\n'
        '        )',
        '        self.ec_slope_uScm_per_V, self.ec_intercept_uScm = load_ec_two_point()',
        "EC loader call",
    )
    source = replace_once(
        source,
        'ec_uScm = self.ec_scale * a2_reading["filtered_voltage_V"]',
        'ec_uScm = max(0.0, self.ec_slope_uScm_per_V * a2_reading["filtered_voltage_V"]'
        ' + self.ec_intercept_uScm)',
        "EC conversion",
    )
    source = source.replace("EC V2 post-hardware-fix", "EC V3 two-point (tap water)")
    source = source.replace("OK: ACCEPTED SINGLE-POINT DIRECT EC — POST-HARDWARE-FIX",
                            "OK: PROVISIONAL TWO-POINT DIRECT EC")
    compile(source, str(SOURCE), "exec")
    return source


def old_standard(path=OLD_RECORD):
    record = json.loads(path.read_text(encoding="utf-8"))
    voltage = record.get("reference_filtered_voltage_V")
    scale = record.get("ec_scale_uScm_per_V")
    if (record.get("hardware", {}).get("channel") != "A2"
            or record.get("hardware", {}).get("gain") != 1
            or record.get("reference_uScm") != HIGH_USCM
            or record.get("reference_temperature_C") != 25.0
            or record.get("calibration_status") !=
            "ACCEPTED SINGLE-POINT DIRECT EC CALIBRATION — POST-HARDWARE-FIX"
            or type(voltage) not in (int, float)
            or not math.isfinite(voltage)
            or not 0.4 < voltage < 1.0
            or not isinstance(scale, str)
            or not math.isclose(float(scale) * voltage, HIGH_USCM, abs_tol=0.01)):
        raise ValueError("Saved 1.413 mS/cm A2 standard is missing or incompatible")
    return float(voltage)


def read_snapshot(api=API):
    request = Request(api, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def validate_snapshot(payload, now=None):
    system = payload.get("system") or {}
    if (system.get("ads1115_address") != "0x48" or system.get("ads1115_gain") != 1
            or system.get("ec_relay_state") != "OFF"
            or system.get("ec_relay_polarity") != "ACTIVE_LOW"):
        raise ValueError("Unexpected A2/relay configuration")
    sample = system.get("sample")
    if type(sample) is not int or sample < 1:
        raise ValueError("No numbered sensor sample")
    measured = datetime.fromisoformat(payload["timestamp"])
    if measured.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    age = ((now or datetime.now(timezone.utc)) - measured).total_seconds()
    if age < -10 or age > 90:
        raise ValueError(f"Sensor snapshot is stale ({age:.0f}s)")
    ec = (payload.get("sensors") or {}).get("ec") or {}
    if (ec.get("spike") is True or ec.get("valid") is not True
            or ec.get("retained") is True or ec.get("stale") is True
            or not str(ec.get("status") or "").startswith("OK")):
        raise ValueError("EC is spiking, stale, retained, or unavailable")
    values = {}
    for field in ("raw_voltage_V", "filtered_voltage_V"):
        value = ec.get(field)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0.01 < value < 3.29:
            raise ValueError(f"EC {field} is unavailable or out of range")
        values[field] = float(value)
    return {"sample": sample, "timestamp": payload["timestamp"],
            "csv_path": system.get("csv_path"), **values}


def summarize(samples):
    if len(samples) != SAMPLES or len({item["sample"] for item in samples}) != SAMPLES:
        raise ValueError("Five distinct samples required")
    raw = [item["raw_voltage_V"] for item in samples]
    filtered = [item["filtered_voltage_V"] for item in samples]
    raw_range = max(raw) - min(raw)
    filtered_range = max(filtered) - min(filtered)
    if raw_range > 0.01 or filtered_range > 0.005:
        raise ValueError(f"A2 reference is drifting (raw {raw_range:.6f} V, filtered {filtered_range:.6f} V)")
    return {"median_voltage_V": statistics.median(filtered),
            "raw_range_V": raw_range, "filtered_range_V": filtered_range,
            "filtered_sd_V": statistics.pstdev(filtered)}


def capture(after_sample, session, timeout=MAX_WAIT_SECONDS):
    samples = []
    seen = set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            item = validate_snapshot(read_snapshot())
        except (OSError, ValueError, KeyError) as exc:
            samples.clear()
            print(f"Waiting for valid A2 sample: {exc}", flush=True)
            time.sleep(5)
            continue
        if item["csv_path"] != session:
            raise ValueError("Sensor service session changed during calibration; no files changed")
        if item["sample"] > after_sample and item["sample"] not in seen:
            seen.add(item["sample"])
            if samples and item["sample"] != samples[-1]["sample"] + 1:
                samples.clear()
            samples.append(item)
            samples = samples[-SAMPLES:]
            print(f"Window {len(samples)}/{SAMPLES}: #{item['sample']} A2={item['filtered_voltage_V']:.6f} V", flush=True)
            if len(samples) == SAMPLES:
                try:
                    return samples, summarize(samples)
                except ValueError as exc:
                    print(f"Still settling: {exc}", flush=True)
        time.sleep(5)
    raise ValueError("Timed out without five stable A2 samples; no files changed")


def coefficients(high_voltage, low_voltage):
    if not 0 < low_voltage < high_voltage - 0.1:
        raise ValueError("EC reference voltages are too close or reversed")
    slope = (HIGH_USCM - TAP_USCM) / (high_voltage - low_voltage)
    intercept = TAP_USCM - slope * low_voltage
    if not 100 < slope < 10000 or not -5000 < intercept < 5000:
        raise ValueError("EC two-point fit is outside guarded range")
    return slope, intercept


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, path.stat().st_mode if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = SOURCE.read_text(encoding="utf-8")
    updated = transform_source(original)
    high_voltage = old_standard()
    current = validate_snapshot(read_snapshot())
    slope, intercept = coefficients(high_voltage, current["filtered_voltage_V"])
    print(f"Saved high standard: {high_voltage:.6f} V = {HIGH_USCM / 1000:.3f} mS/cm")
    print(f"Current tap water: {current['filtered_voltage_V']:.6f} V; external meter {TAP_USCM / 1000:.3f} mS/cm")
    print(f"Provisional fit at current voltage: slope {slope:.6f} uS/cm/V, intercept {intercept:.6f} uS/cm")
    if NEW_RECORD.exists():
        raise ValueError(f"{NEW_RECORD} already exists; refusing to overwrite calibration")
    if args.check:
        print("Ready to capture five fresh A2 readings; no files changed")
        return
    samples, summary = capture(current["sample"], current["csv_path"])
    low_voltage = summary["median_voltage_V"]
    slope, intercept = coefficients(high_voltage, low_voltage)
    if SOURCE.read_text(encoding="utf-8") != original or NEW_RECORD.exists():
        raise ValueError("Service or calibration changed during capture; no files changed")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = SOURCE.with_name(f"{SOURCE.name}.before_ec_two_point_{stamp}")
    record = {
        "calibration_status": "PROVISIONAL TWO-POINT DIRECT EC",
        "calibrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "formula": "EC_uScm = max(0, slope * voltage_V + intercept)",
        "slope_uScm_per_V": format(slope, ".15g"),
        "intercept_uScm": format(intercept, ".15g"),
        "reference_points": [
            {"ec_uScm": HIGH_USCM, "filtered_voltage_V": high_voltage,
             "source": str(OLD_RECORD), "reference_temperature_C": 25.0},
            {"ec_uScm": TAP_USCM, "filtered_voltage_V": low_voltage,
             "source": "separate EC meter reading in current tap-water sample",
             "meter_temperature_C": None},
        ],
        "tap_voltage_statistics": {"sample_count": len(samples), **summary, "samples": samples},
        "limitations": [
            "Provisional two-point fit; no independent validation outside the two anchors.",
            "Tap-water meter temperature is unrecorded; no temperature compensation was derived.",
            "Below the low anchor, negative linear estimates are clamped to zero; above the high anchor is extrapolation.",
            "Older EC history and trained pilot inputs used the prior conversion.",
        ],
    }
    shutil.copy2(SOURCE, backup)
    try:
        atomic_write(NEW_RECORD, json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        atomic_write(SOURCE, updated)
    except Exception:
        atomic_write(SOURCE, original)
        NEW_RECORD.unlink(missing_ok=True)
        raise
    print(f"Tap-water A2 median: {low_voltage:.6f} V")
    print(f"New slope: {slope:.8f} uS/cm/V; intercept: {intercept:.8f} uS/cm")
    print(f"Backup: {backup}\nCalibration record: {NEW_RECORD}")
    print("Service was NOT restarted; no test SMS was sent.")


if __name__ == "__main__":
    main()
