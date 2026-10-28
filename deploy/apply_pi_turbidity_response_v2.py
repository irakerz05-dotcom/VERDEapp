#!/usr/bin/env python3
"""Increase the unvalidated A0 turbidity project response without recapturing water.

--check changes nothing. --apply backs up the service and calibration record,
then updates both; it never restarts the Pi service or sends a test SMS.
"""

import argparse
import json
import math
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


SOURCE = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
RECORD = Path("/home/verde/turbidity_calibration_ntu.json")
CONFIG = Path("/home/verde/VERDE-Sensor-Integration/config.local.json")
OLD_EQUATION = "return TURBIDITY_REFERENCE_NTU * (abs(reference_voltage) / abs(measured_voltage)) ** 2"
NEW_EQUATION = "return TURBIDITY_REFERENCE_NTU * (abs(reference_voltage) / abs(measured_voltage)) ** 2.4"
REFERENCE_ESTIMATE = 0.3
VERSION = "PROJECT_RELATIVE_POWER_2_4_V2"


def transform_source(source):
    if source.count(OLD_EQUATION) != 1 or NEW_EQUATION in source:
        raise ValueError("Expected exactly one installed squared-ratio conversion")
    if (source.count("TURBIDITY_REFERENCE_NTU = 0.3") != 1
            or 'record.get("ads_channel") != "A0"' not in source
            or "if value_ntu < 20.0:" not in source):
        raise ValueError("Expected the installed A0 reference and 20+ boundary")
    updated = source.replace(OLD_EQUATION, NEW_EQUATION, 1)
    compile(updated, str(SOURCE), "exec")
    return updated


def transform_record(record):
    if (record.get("ads_channel") != "A0"
            or record.get("calibration_status") != "CALIBRATED"
            or type(record.get("reference_ntu")) not in (int, float)
            or record["reference_ntu"] != REFERENCE_ESTIMATE
            or record.get("conversion_version") != "PROJECT_RELATIVE_SQUARED_V1"
            or record.get("reference_provenance") != "USER_ASSIGNED_UNCERTIFIED"):
        raise ValueError("Expected the installed unverified A0 project response")
    voltage = record.get("reference_voltage_V")
    if type(voltage) not in (int, float) or not math.isfinite(voltage) or not 0 < voltage < 3.29:
        raise ValueError("Expected a finite, in-range A0 reference voltage")
    updated = dict(record)
    updated["calibration_equation"] = (
        "Project-estimated NTU = 0.3 * (abs(V_reference) / abs(V_measured))^2.4"
    )
    updated["interpretation"] = (
        "Unvalidated project-relative display estimate; not measured standard NTU. "
        "The 2.4-power response is chosen to place this milk sample above 20 on "
        "the project scale; milk was not a certified 20 NTU standard."
    )
    updated["conversion_version"] = VERSION
    updated["conversion_applied_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return updated


def preflight(source_path=SOURCE, record_path=RECORD, config_path=CONFIG):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (config.get("limits") or {}).get("turbidity_critical") is not None:
        raise ValueError("Configured critical turbidity safety limit requires separate review")
    source = transform_source(source_path.read_text(encoding="utf-8"))
    record = transform_record(json.loads(record_path.read_text(encoding="utf-8")))
    return source, record


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source, record = preflight()
    reference = record["reference_voltage_V"]
    for voltage in (reference, 0.279):
        print(f"A0 {voltage:.6f} V -> {REFERENCE_ESTIMATE * (reference / voltage) ** 2.4:.4f} project-estimated NTU")
    if args.check:
        print("Ready: A0 response and record verified; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path in (SOURCE, RECORD):
        backup = path.with_name(f"{path.name}.before_relative_response_v2_{stamp}")
        shutil.copy2(path, backup)
        backups.append(backup)
    atomic_write(SOURCE, source)
    try:
        atomic_write(RECORD, json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    except Exception:
        atomic_write(SOURCE, backups[0].read_text(encoding="utf-8"))
        raise
    for backup in backups:
        print(f"Backup: {backup}")
    print("Updated project response. Service was NOT restarted; no test SMS was sent.")


if __name__ == "__main__":
    main()
