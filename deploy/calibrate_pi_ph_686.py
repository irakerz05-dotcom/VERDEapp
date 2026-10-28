#!/usr/bin/env python3
"""Adjust the Pi pH offset using a stable 6.86 pH buffer reading.

The existing slope is retained. Only cached ADS1115 readings are used; this
script never talks to GPIO or I2C. --check is read-only. --apply captures five
new stable samples, backs up the source, and changes only PH_INTERCEPT. Restart
the service separately after reviewing the result.
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


SERVICE_SOURCE = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
API = "http://127.0.0.1:8000/api/sensors/latest"
REFERENCE_PH = 6.86
SAMPLES = 5
MAX_WAIT_SECONDS = 600
SOURCE_NUMBER = r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"


def source_calibration(source):
    if not re.search(r'"ph"\s*,\s*AnalogIn\(self\.ads,\s*ADS\.P1\)', source):
        raise ValueError("pH acquisition is not on the reviewed ADS1115 A1 channel")
    values = {}
    for name in ("PH_SLOPE", "PH_INTERCEPT"):
        pattern = rf"(?m)^{name}\s*=\s*{SOURCE_NUMBER}\s*$"
        matches = list(re.finditer(pattern, source))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one numeric {name} assignment")
        values[name] = (matches[0], float(matches[0].group(1)))
        if not math.isfinite(values[name][1]):
            raise ValueError(f"{name} must be finite")
    slope = values["PH_SLOPE"][1]
    if not -20 < slope < -1:
        raise ValueError("pH slope differs from the reviewed conversion")
    if not re.search(r"ADS1115_GAIN\s*=\s*1\b", source):
        raise ValueError("ADS1115 gain differs from the reviewed configuration")
    return values


def read_snapshot(api=API):
    request = Request(api, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def validate_snapshot(payload, slope, intercept, now=None):
    system = payload.get("system") or {}
    if system.get("ads1115_address") != "0x48" or system.get("ads1115_gain") != 1:
        raise ValueError("ADS1115 address or gain differs from the reviewed configuration")
    sample = system.get("sample")
    if type(sample) is not int or sample < 1:
        raise ValueError("No numbered acquisition sample")
    measured = datetime.fromisoformat(payload["timestamp"])
    if measured.tzinfo is None:
        raise ValueError("Acquisition timestamp has no timezone")
    age = ((now or datetime.now(timezone.utc)) - measured).total_seconds()
    if age < -10 or age > 90:
        raise ValueError(f"Acquisition is stale or the Pi clock is wrong ({age:.0f}s)")
    sensor = (payload.get("sensors") or {}).get("ph") or {}
    if (sensor.get("valid") is not True or sensor.get("retained") is not False
            or sensor.get("stale") is not False or sensor.get("spike") is not False
            or not str(sensor.get("status") or "").startswith("OK")):
        raise ValueError("pH reading is not fresh, valid, and free of spikes")
    values = {}
    for name in ("raw_voltage_V", "filtered_voltage_V"):
        value = sensor.get(name)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0.01 < value < 3.29):
            raise ValueError(f"pH {name} is unavailable or outside the guarded ADC range")
        values[name] = float(value)
    ph = sensor.get("value")
    if isinstance(ph, bool) or not isinstance(ph, (int, float)) or not math.isfinite(ph):
        raise ValueError("Current pH value is unavailable")
    if abs(ph - (slope * values["filtered_voltage_V"] + intercept)) > 0.02:
        raise ValueError("Live pH does not match the source conversion; stop")
    return {"sample": sample, "timestamp": payload["timestamp"], "ph": float(ph), **values}


def summarize(samples, slope):
    if len(samples) != SAMPLES or len({item["sample"] for item in samples}) != SAMPLES:
        raise ValueError("Need five distinct acquisition samples")
    if any(b["sample"] != a["sample"] + 1 for a, b in zip(samples, samples[1:])):
        raise ValueError("Need five consecutive acquisition samples")
    raw = [item["raw_voltage_V"] for item in samples]
    filtered = [item["filtered_voltage_V"] for item in samples]
    raw_range = max(raw) - min(raw)
    filtered_range = max(filtered) - min(filtered)
    if raw_range > 0.025 or filtered_range > 0.015:
        raise ValueError(f"pH buffer reading is still changing (raw {raw_range:.5f} V; filtered {filtered_range:.5f} V)")
    voltage = statistics.median(filtered)
    return {"reference_voltage_V": voltage, "raw_range_V": raw_range,
            "filtered_range_V": filtered_range,
            "new_intercept": REFERENCE_PH - slope * voltage}


def capture(slope, intercept, after_sample, timeout=MAX_WAIT_SECONDS, api=API):
    samples = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            item = validate_snapshot(read_snapshot(api), slope, intercept)
        except (OSError, ValueError, KeyError) as exc:
            samples.clear()
            print(f"Waiting for a valid pH sample: {exc}", flush=True)
            time.sleep(5)
            continue
        if item["sample"] > after_sample and (not samples or item["sample"] > samples[-1]["sample"]):
            if samples and item["sample"] != samples[-1]["sample"] + 1:
                samples.clear()
            samples.append(item)
            samples = samples[-SAMPLES:]
            print(f"Window {len(samples)}/{SAMPLES}: #{item['sample']} pH={item['ph']:.4f} V={item['filtered_voltage_V']:.6f}", flush=True)
            if len(samples) == SAMPLES:
                try:
                    return samples, summarize(samples, slope)
                except ValueError as exc:
                    print(f"Still settling: {exc}; waiting for another sample", flush=True)
        time.sleep(5)
    raise ValueError("Timed out without five consecutive stable pH samples; no file was changed")


def replace_intercept(source, match, new_intercept):
    updated = source[:match.start(1)] + f"{new_intercept:.10f}" + source[match.end(1):]
    compile(updated, str(SERVICE_SOURCE), "exec")
    return updated


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
    parser.add_argument("--timeout-seconds", type=int, default=MAX_WAIT_SECONDS)
    args = parser.parse_args()
    if not 30 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be between 30 and 1800")
    source = SERVICE_SOURCE.read_text(encoding="utf-8")
    values = source_calibration(source)
    slope = values["PH_SLOPE"][1]
    old_intercept = values["PH_INTERCEPT"][1]
    current = validate_snapshot(read_snapshot(), slope, old_intercept)
    print(f"Current pH: {current['ph']:.4f}; A1 filtered: {current['filtered_voltage_V']:.6f} V; sample #{current['sample']}")
    print(f"Reference: {REFERENCE_PH:.2f} pH; existing slope: {slope:.8f}; existing intercept: {old_intercept:.8f}")
    if args.check:
        print("Ready to capture five new stable readings; no files changed.")
        return
    samples, summary = capture(slope, old_intercept, after_sample=current["sample"],
                               timeout=args.timeout_seconds)
    if abs(summary["new_intercept"] - old_intercept) > 2.0:
        raise ValueError("Required pH offset shift exceeds 2.0 pH units; no file was changed")
    # A concurrent source change must not be overwritten by this calibration.
    if SERVICE_SOURCE.read_text(encoding="utf-8") != source:
        raise ValueError("Service source changed during capture; no file was changed")
    updated = replace_intercept(source, values["PH_INTERCEPT"][0], summary["new_intercept"])
    backup = SERVICE_SOURCE.with_name(
        f"{SERVICE_SOURCE.name}.before_ph_686_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
    shutil.copy2(SERVICE_SOURCE, backup)
    atomic_write(SERVICE_SOURCE, updated)
    print(f"Backup: {backup}")
    print(f"Reference voltage: {summary['reference_voltage_V']:.6f} V; raw range: {summary['raw_range_V']:.5f} V; filtered range: {summary['filtered_range_V']:.5f} V")
    print(f"New intercept: {summary['new_intercept']:.10f}; expected buffer pH: {REFERENCE_PH:.2f}")
    print("Existing slope was retained. Service was NOT restarted; no SMS was sent by this script.")


if __name__ == "__main__":
    main()
