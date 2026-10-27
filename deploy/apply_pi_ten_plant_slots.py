#!/usr/bin/env python3
"""Install ten blank NFT planting slots while retaining the earlier date table.

--check makes no changes. --apply backs up only the Python module and leaves
the service running; its next start creates plant_slots_v2 on first request.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
SOURCE = Path(__file__).with_name("pi_plant_slots_ten.py")
OLD_COMMIT = "a69d0d8"


def prepare(root=BACKEND):
    target = root / "app/plant_slots.py"
    web = root / "app/web/__init__.py"
    current = target.read_text(encoding="utf-8")
    if "from app.plant_slots import PlantSlotStore" not in web.read_text(encoding="utf-8"):
        raise ValueError("Existing planting-date routes are missing")
    expected_old = subprocess.run(
        ["git", "-C", str(root), "show", f"{OLD_COMMIT}:app/plant_slots.py"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    desired = SOURCE.read_text(encoding="utf-8")
    if current not in (expected_old, desired):
        raise ValueError("Pi planting module differs from reviewed version; no files changed")
    if ("SLOT_COUNT = 10" not in desired or "plant_slots_v2" not in desired
            or "slot_count" not in desired):
        raise ValueError("Reviewed ten-slot source is incomplete")
    compile(desired, str(target), "exec")
    return target, desired, current != desired


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
    try:
        target, contents, changed = prepare(args.target.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError, SyntaxError) as exc:
        parser.exit(1, f"Ten-slot patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {target}; {'one module update' if changed else 'already applied'}; no files changed")
        return
    if not changed:
        print("Already applied; no files changed")
        return
    backup = target.with_name(f"{target.name}.before_ten_slots_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(target, backup)
    atomic_write(target, contents)
    print(f"Updated: {target}")
    print(f"Backup: {backup}")
    print("Service was NOT restarted. Old 12-slot dates remain in SQLite plant_slots; new dates start blank.")


if __name__ == "__main__":
    main()
