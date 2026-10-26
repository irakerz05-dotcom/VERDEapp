#!/usr/bin/env python3
"""Switch the Pi's turbidity acquisition and calibration guard between A0 and A3.

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


def transform(source, channel="A3"):
    if channel not in ("A0", "A3"):
        raise ValueError("Unsupported turbidity channel")
    replacements = REPLACEMENTS if channel == "A3" else tuple(
        (new, old) for old, new in REPLACEMENTS
    )
    for old, new in replacements:
        if source.count(old) != 1 or new in source:
            raise ValueError(f"Expected exactly one current source anchor: {old}")
        source = source.replace(old, new, 1)
    compile(source, str(TARGET), "exec")
    return source


def apply(path=TARGET, channel="A3"):
    source = path.read_text(encoding="utf-8")
    updated = transform(source, channel)
    backup = path.with_name(f"{path.name}.before_turbidity_{channel.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}")
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
    parser.add_argument("--channel", choices=("A0", "A3"), default="A3")
    args = parser.parse_args()
    if args.check:
        transform(TARGET.read_text(encoding="utf-8"), args.channel)
        print(f"Ready: {TARGET}; {args.channel} source syntax valid; no files changed")
    else:
        backup = apply(channel=args.channel)
        print(f"Updated: {TARGET}")
        print(f"Backup: {backup}")
        print(f"Service was NOT restarted. The old calibration will be rejected if it is not for {args.channel}.")


if __name__ == "__main__":
    main()
