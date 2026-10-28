#!/usr/bin/env python3
"""Install a project-relative turbidity response, preserving the A0 reference.

This is an unvalidated display estimate, not a standard NTU calibration.
--check is read-only. --apply backs up both changed Pi files and does not restart.
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
OLD_EQUATION = "return TURBIDITY_REFERENCE_NTU * abs(reference_voltage) / abs(measured_voltage)"
NEW_EQUATION = "return TURBIDITY_REFERENCE_NTU * (abs(reference_voltage) / abs(measured_voltage)) ** 2"
REFERENCE_ESTIMATE = 0.3


def replace_once(source, old, new, label):
    if source.count(old) != 1 or new in source:
        raise ValueError(f"{label}: expected exactly one original source anchor")
    return source.replace(old, new, 1)


def transform_source(source):
    source = replace_once(source, "TURBIDITY_REFERENCE_NTU = 1.0",
                          "TURBIDITY_REFERENCE_NTU = 0.3", "reference value")
    source = replace_once(source, OLD_EQUATION, NEW_EQUATION, "conversion")
    source = replace_once(source, "if value_ntu <= 20.0:",
                          "if value_ntu < 20.0:", "20 NTU critical boundary")
    source = replace_once(source, "reference NTU must be exactly 1.00",
                          "project reference estimate must be exactly 0.30", "record guard")
    if 'record.get("ads_channel") != "A0"' not in source:
        raise ValueError("Current sensor input is not verified as ADS1115 A0")
    compile(source, str(SOURCE), "exec")
    return source


def transform_record(record):
    if record.get("ads_channel") != "A0" or record.get("calibration_status") != "CALIBRATED":
        raise ValueError("Expected calibrated ADS1115 A0 reference")
    if type(record.get("reference_ntu")) not in (int, float) or record["reference_ntu"] != 1.0:
        raise ValueError("Expected the existing project-assigned 1.0 reference")
    voltage = record.get("reference_voltage_V")
    if type(voltage) not in (int, float) or not math.isfinite(voltage) or not 0 < voltage < 3.29:
        raise ValueError("Expected a finite, in-range A0 reference voltage")
    if record.get("reference_provenance") != "USER_ASSIGNED_UNCERTIFIED":
        raise ValueError("Expected unverified project reference provenance")
    updated = dict(record)
    updated["reference_ntu"] = REFERENCE_ESTIMATE
    updated["reference_sample"] = (
        "Drinking water designated 0.3 project-estimated NTU by operator; not certified"
    )
    updated["calibration_equation"] = (
        "Project-estimated NTU = 0.3 * (abs(V_reference) / abs(V_measured))^2"
    )
    updated["interpretation"] = (
        "Unvalidated project-relative display estimate; not measured standard NTU. "
        "The squared response is an assumed sensitivity, not a DFRobot calibration curve."
    )
    updated["conversion_version"] = "PROJECT_RELATIVE_SQUARED_V1"
    updated["conversion_applied_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return updated


def preflight(source_path=SOURCE, record_path=RECORD, config_path=CONFIG):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if (config.get("limits") or {}).get("turbidity_critical") is not None:
        raise ValueError("Configured critical turbidity safety/SMS limit requires separate review")
    original_source = source_path.read_text(encoding="utf-8")
    original_record = json.loads(record_path.read_text(encoding="utf-8"))
    return transform_source(original_source), transform_record(original_record)


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
    current = record["reference_voltage_V"]
    projected_milk = REFERENCE_ESTIMATE * (current / (current / 8.3)) ** 2
    print(f"A0 reference: {current:.6f} V; project display reference: 0.3 estimated NTU")
    print(f"An old 8.3-ratio sample would display about {projected_milk:.1f} estimated NTU; not a measured milk standard")
    if args.check:
        print("Ready: two guarded Pi files; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path in (SOURCE, RECORD):
        backup = path.with_name(f"{path.name}.before_relative_response_{stamp}")
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
    print("Updated source and reference record. Service was NOT restarted; no test SMS was sent.")


if __name__ == "__main__":
    main()
