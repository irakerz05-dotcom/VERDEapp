#!/usr/bin/env python3
"""Reject flagged pH/EC/turbidity spikes in the Pi's descriptive RF and fusion.

--check changes nothing. --apply backs up both Python modules, validates their
syntax, and does not restart the service or modify automation, GPIO, or SMS.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
PATCHES = (
    ("app/ml/water_quality/prototype_rf.py",
     'or sensor.get("stale") is True or sensor.get("read_error") is not None):',
     'or sensor.get("stale") is True or sensor.get("spike") is True\n'
     '                or sensor.get("read_error") is not None):'),
    ("app/fusion/__init__.py",
     'or sensor.get("retained") is True or sensor.get("stale") is True\n'
     '                or not status.startswith(("OK", "CONNECTED", "CALIBRATED"))):',
     'or sensor.get("retained") is True or sensor.get("stale") is True\n'
     '                or sensor.get("spike") is True\n'
     '                or not status.startswith(("OK", "CONNECTED", "CALIBRATED"))):'),
)


def transform(source, old, new, name):
    if source.count(old) != 1 or new in source:
        raise ValueError(f"{name}: expected one unmodified source anchor")
    updated = source.replace(old, new, 1)
    compile(updated, name, "exec")
    return updated


def prepare(root=BACKEND):
    prepared = []
    for name, old, new in PATCHES:
        path = root / name
        updated = transform(path.read_text(encoding="utf-8"), old, new, name)
        prepared.append((path, updated))
    return prepared


def apply(root=BACKEND):
    prepared = prepare(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path, _ in prepared:
        backup = path.with_name(f"{path.name}.before_rf_spike_guard_{stamp}")
        shutil.copy2(path, backup)
        backups.append(backup)
    for path, updated in prepared:
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
    return backups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.check:
        prepared = prepare()
        print(f"Ready: {len(prepared)} guarded Python edits; syntax valid; no files changed")
    else:
        backups = apply()
        for backup in backups:
            print(f"Backup: {backup}")
        print("RF and fusion guard updated. Service was NOT restarted.")


if __name__ == "__main__":
    main()
