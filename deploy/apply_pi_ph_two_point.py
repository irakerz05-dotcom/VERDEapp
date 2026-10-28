#!/usr/bin/env python3
"""Apply a provisional two-point pH fit to the Pi's cached A1 sensor service.

The 6.81 and 9.45 targets were reported from a commercial pH meter. The
6.81-point voltage came from a stable five-sample 6.86-buffer capture. The
9.45-point voltage is a repeated filtered reading in the alkaline buffer;
raw readings there fluctuated. The acidic point is excluded because its A1
voltage reached the ADC supply. No GPIO or I2C operations occur here.
"""

import argparse
import json
import math
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
RECORD = Path("/home/verde/ph_calibration_two_point_20261028.json")
OLD_SLOPE = -6.15727193
OLD_INTERCEPT = 24.1211421968
NEUTRAL_V = 2.803375
NEUTRAL_PH = 6.81
ALKALINE_V = 2.37775
ALKALINE_PH = 9.45


def coefficients():
    slope = (ALKALINE_PH - NEUTRAL_PH) / (ALKALINE_V - NEUTRAL_V)
    intercept = NEUTRAL_PH - slope * NEUTRAL_V
    if not (math.isfinite(slope) and math.isfinite(intercept) and -20 < slope < -1):
        raise ValueError("Invalid two-point pH coefficients")
    return slope, intercept


def transform(source):
    if not re.search(r'"ph"\s*,\s*AnalogIn\(self\.ads,\s*ADS\.P1\)', source):
        raise ValueError("pH acquisition is not on the reviewed ADS1115 A1 channel")
    if not re.search(r'(?m)^ADS1115_GAIN\s*=\s*1\s*$', source):
        raise ValueError("ADS1115 gain differs from the reviewed configuration")
    slope, intercept = coefficients()
    assignments = (
        ("PH_SLOPE", OLD_SLOPE, slope),
        ("PH_INTERCEPT", OLD_INTERCEPT, intercept),
    )
    updated = source
    already = []
    for name, old, new in assignments:
        pattern = rf"(?m)^{name}\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
        matches = list(re.finditer(pattern, updated))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one numeric {name} assignment")
        match = matches[0]
        actual = float(match.group(1))
        if math.isclose(actual, new, abs_tol=1e-9):
            already.append(True)
            continue
        if not math.isclose(actual, old, abs_tol=1e-9):
            raise ValueError(f"{name} differs from the reviewed 6.86-point calibration")
        already.append(False)
        updated = updated[:match.start(1)] + f"{new:.10f}" + updated[match.end(1):]
    if any(already) and not all(already):
        raise ValueError("Only one pH coefficient has been updated; refusing a mixed calibration")
    compile(updated, str(TARGET), "exec")
    return updated


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record_for(backup):
    slope, intercept = coefficients()
    return {
        "calibrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "method": "Provisional straight-line fit to two commercial-meter readings",
        "equation": "pH = slope * ADS1115_A1_filtered_voltage_V + intercept",
        "points": [
            {"reference_ph": NEUTRAL_PH, "filtered_voltage_V": NEUTRAL_V,
             "source": "Stable five-sample capture in 6.86-labeled buffer; commercial meter read 6.81"},
            {"reference_ph": ALKALINE_PH, "filtered_voltage_V": ALKALINE_V,
             "source": "Repeated filtered reading in 9.4 buffer; commercial meter read 9.45 (roughly 9.3–9.6)"},
        ],
        "slope": slope, "intercept": intercept,
        "previous_slope": OLD_SLOPE, "previous_intercept": OLD_INTERCEPT,
        "source_backup": str(backup),
        "limitations": [
            "Alkaline raw voltage fluctuated substantially; this fit is provisional.",
            "The commercial-meter reading and A1 voltage were not confirmed simultaneous.",
            "The 4.41 acidic point is excluded because A1 reached or exceeded the ADC supply.",
            "Readings below 6.81 pH are extrapolated and not validated by these two points.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--record", type=Path, default=RECORD)
    args = parser.parse_args()
    try:
        source = args.target.read_text(encoding="utf-8")
        updated = transform(source)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"pH two-point patch not ready: {exc}\n")
    slope, intercept = coefficients()
    print(f"Reference points: {NEUTRAL_V:.6f} V = {NEUTRAL_PH:.2f} pH; "
          f"{ALKALINE_V:.6f} V = {ALKALINE_PH:.2f} pH")
    print(f"New slope: {slope:.10f}; new intercept: {intercept:.10f}")
    if source == updated:
        print("Already installed; no files changed")
        return
    if args.check:
        print("Ready: A1 and both prior coefficients match; syntax valid; no files changed")
        return
    if args.record.exists():
        parser.exit(1, f"Calibration record already exists: {args.record}; no file changed\n")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = args.target.with_name(f"{args.target.name}.before_ph_two_point_{stamp}")
    record = json.dumps(record_for(backup), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.target.read_text(encoding="utf-8") != source:
        parser.exit(1, "Service source changed during the check; no file changed\n")
    shutil.copy2(args.target, backup)
    print(f"Backup: {backup}")
    try:
        atomic_write(args.target, updated)
        atomic_write(args.record, record)
    except OSError:
        atomic_write(args.target, source)
        raise
    print(f"Calibration record: {args.record}")
    print("Updated pH slope and intercept. Service was NOT restarted; no SMS was sent.")


if __name__ == "__main__":
    main()
