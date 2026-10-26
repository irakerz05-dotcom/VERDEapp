#!/usr/bin/env python3
"""Set a project-relative A0 turbidity reference from cached Pi sensor samples.

The farmer designates the current drinking water as 1.0 NTU. This is a single
point estimate, not a certified NTU calibration. No GPIO/I2C access occurs here.
Run --check first; --apply waits for five distinct backend samples, backs up the
old record, and saves a new A0 reference. Restart the service separately.
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
RECORD_PATH = Path("/home/verde/turbidity_calibration_ntu.json")
CONFIG_PATH = Path("/home/verde/VERDE-Sensor-Integration/config.local.json")
API = "http://127.0.0.1:8000/api/sensors/latest"
SAMPLES = 5
MAX_WAIT_SECONDS = 210


def verify_service_source(path=SERVICE_SOURCE):
    source = path.read_text(encoding="utf-8")
    checks = (
        (r'ADS1115_GAIN\s*=\s*1\b', "ADS1115 gain 1"),
        (r'TURBIDITY_REFERENCE_NTU\s*=\s*1\.0\b', "1.0 reference"),
        (r'"turbidity"\s*,\s*AnalogIn\(self\.ads,\s*ADS\.P0\)', "A0 input"),
        (r'record\.get\("ads_channel"\)\s*!=\s*"A0"', "A0 record guard"),
        (r'record\.get\("calibration_status"\)\s*!=\s*"CALIBRATED"', "record status guard"),
        (r'TURBIDITY_REFERENCE_NTU\s*\*\s*abs\(reference_voltage\)\s*/\s*abs\(measured_voltage\)',
         "project-relative NTU equation"),
    )
    for expression, description in checks:
        if re.search(expression, source) is None:
            raise ValueError(f"Running service source does not confirm {description}; stop")


def read_snapshot(api=API):
    request = Request(api, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def validate_snapshot(payload, now=None):
    system = payload.get("system") or {}
    if system.get("ads1115_address") != "0x48" or system.get("ads1115_gain") != 1:
        raise ValueError("ADS1115 address/gain differs from verified configuration")
    sample = system.get("sample")
    if type(sample) is not int or sample < 1:
        raise ValueError("No numbered sensor sample")
    measured = datetime.fromisoformat(payload["timestamp"])
    if measured.tzinfo is None:
        raise ValueError("Sensor timestamp has no timezone")
    age = ((now or datetime.now(timezone.utc)) - measured).total_seconds()
    if age < -10 or age > 90:
        raise ValueError(f"Sensor snapshot is stale or clock is wrong ({age:.0f}s)")
    sensor = (payload.get("sensors") or {}).get("turbidity") or {}
    if sensor.get("spike") is True:
        raise ValueError("A0 spike was flagged; hold the probe still")
    values = {}
    for name in ("raw_voltage_V", "filtered_voltage_V"):
        value = sensor.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"A0 {name} is unavailable")
        if not 0.01 < value < 3.0:
            raise ValueError(f"A0 {name}={value} V is outside the guarded capture range")
        values[name] = float(value)
    return {"sample": sample, "timestamp": payload["timestamp"], **values}


def summarize(samples):
    if len(samples) != SAMPLES or len({item["sample"] for item in samples}) != SAMPLES:
        raise ValueError(f"Need {SAMPLES} distinct sensor samples")
    raw = [item["raw_voltage_V"] for item in samples]
    filtered = [item["filtered_voltage_V"] for item in samples]
    raw_range = max(raw) - min(raw)
    filtered_range = max(filtered) - min(filtered)
    if raw_range > 0.010 or filtered_range > 0.010:
        raise ValueError(f"Reference is unstable (raw range {raw_range:.5f} V, filtered range {filtered_range:.5f} V)")
    return {"reference_voltage_V": statistics.median(filtered),
            "raw_voltage_range_V": raw_range,
            "filtered_voltage_range_V": filtered_range,
            "filtered_voltage_sd_V": statistics.pstdev(filtered)}


def capture(api=API, timeout=MAX_WAIT_SECONDS):
    seen = set()
    samples = []
    deadline = time.monotonic() + timeout
    while len(samples) < SAMPLES and time.monotonic() < deadline:
        try:
            item = validate_snapshot(read_snapshot(api))
        except (OSError, ValueError, KeyError) as exc:
            print(f"Waiting for a valid A0 sample: {exc}", flush=True)
            time.sleep(5)
            continue
        if item["sample"] not in seen:
            seen.add(item["sample"])
            samples.append(item)
            print(f"Sample {len(samples)}/{SAMPLES}: #{item['sample']} A0={item['filtered_voltage_V']:.6f} V", flush=True)
        if len(samples) < SAMPLES:
            time.sleep(5)
    if len(samples) != SAMPLES:
        raise ValueError("Timed out before five fresh A0 samples; no record was changed")
    return samples, summarize(samples)


def local_critical_limit(path=CONFIG_PATH):
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as handle:
        return (json.load(handle).get("limits") or {}).get("turbidity_critical")


def record_for(samples, summary):
    return {
        "sensor_type": "SEN0189-compatible analog turbidity sensor",
        "ads_channel": "A0", "ads_gain": 1,
        "calibration_datetime": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reference_sample": "Drinking water designated 1.0 NTU by project operator; not certified",
        "reference_ntu": 1.0,
        "reference_voltage_V": summary["reference_voltage_V"],
        "voltage_statistics": {"sample_count": len(samples), **summary,
                               "samples": samples},
        "calibration_method": "Median of five distinct cached ADS1115 A0 samples; no direct hardware reads",
        "calibration_equation": "Estimated NTU = 1.0 * abs(V_reference) / abs(V_measured)",
        "sensor_direction": "Lower voltage gives a larger project NTU estimate",
        "reference_provenance": "USER_ASSIGNED_UNCERTIFIED",
        "calibration_status": "CALIBRATED",
        "interpretation": "Single-point project estimate, not a validated physical NTU measurement",
    }


def save_record(record, path=RECORD_PATH):
    backup = None
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            prior = json.load(handle)
        if prior.get("ads_channel") == "A0":
            raise ValueError("An A0 reference already exists; refusing to replace it automatically")
        backup = path.with_name(f"{path.name}.before_a0_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(path, backup)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                 prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(record, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    verify_service_source()
    current = validate_snapshot(read_snapshot())
    threshold = local_critical_limit()
    print(f"Current A0: {current['filtered_voltage_V']:.6f} V; sample #{current['sample']}")
    print(f"Configured critical turbidity threshold: {threshold!r}")
    if threshold is not None:
        print("Note: estimated NTU can influence the configured critical alert and safety override.")
    if args.check:
        print("Ready to capture five new readings; no files changed.")
        return
    if threshold is not None:
        raise SystemExit("A critical turbidity limit is configured. Review its impact on safety/SMS before assigning this uncertified NTU estimate; no record was changed.")
    samples, summary = capture()
    record = record_for(samples, summary)
    backup = save_record(record)
    print(f"Saved A0 reference: {summary['reference_voltage_V']:.6f} V = project-assigned 1.0 NTU")
    print(f"Prior record backup: {backup}")
    print("The service was NOT restarted. Restart at a safe time to load the reference.")


if __name__ == "__main__":
    main()
