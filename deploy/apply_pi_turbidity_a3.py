#!/usr/bin/env python3
"""Switch the Pi's turbidity acquisition and calibration guard from A0 to A3.

--check is read-only. --apply backs up and atomically replaces the untracked
service source. It does not restart the service or change calibration data.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
REPLACEMENTS = (
    ('record.get("ads_channel") != "A0"', 'record.get("ads_channel") != "A3"'),
    ('"turbidity", AnalogIn(self.ads, ADS.P0)', '"turbidity", AnalogIn(self.ads, ADS.P3)'),
    ('turbidity calibration is not for ADS1115 A0', 'turbidity calibration is not for ADS1115 A3'),
)


def transform(source):
    for old, new in REPLACEMENTS:
        if source.count(old) != 1 or new in source:
            raise ValueError(f"Expected exactly one current source anchor: {old}")
        source = source.replace(old, new, 1)
    compile(source, str(TARGET), "exec")
    return source


def apply(path=TARGET):
    source = path.read_text(encoding="utf-8")
    updated = transform(source)
    backup = path.with_name(f"{path.name}.before_turbidity_a3_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
    shutil.copy2(path, backup)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(updated)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.check:
        transform(TARGET.read_text(encoding="utf-8"))
        print(f"Ready: {TARGET}; A3 source syntax valid; no files changed")
    else:
        backup = apply()
        print(f"Updated: {TARGET}")
        print(f"Backup: {backup}")
        print("Service was NOT restarted. The old A0 calibration will be rejected after restart.")


if __name__ == "__main__":
    main()
