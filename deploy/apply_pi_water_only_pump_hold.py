#!/usr/bin/env python3
"""Guardedly remove the plant-classification hold on water dosing.

The gateway must be disarmed before --apply. This installer changes no GPIO
and does not restart the service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/app/automation/live_mode.py")
SOURCE = Path(__file__).with_name("pi_live_automation_mode.py")
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
EXPECTED_OLD = "e5ef8e9be688709eb82deb120799e3730f5c76ed6c781a0dfd8a7bc616e9ba4f"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plan(target=TARGET, source=SOURCE):
    old = target.read_bytes()
    new = source.read_bytes()
    if digest(old) not in (EXPECTED_OLD, digest(new)):
        raise ValueError("Installed live-mode module differs from reviewed version")
    compile(new, str(target), "exec")
    if b'circulation_stop_reasons.append("Faulty Vision")' not in new:
        raise ValueError("Vision fault stop is missing")
    if b'circulation_stop_reasons.append(name + " Critical")' not in new:
        raise ValueError("Critical sensor stop is missing")
    return old != new, new


def require_disarmed(gateway=GATEWAY):
    result = subprocess.run(("/usr/bin/sudo", "-n", str(gateway), "status"),
                            check=True, capture_output=True, text=True, timeout=15)
    state = json.loads(result.stdout)
    if (state.get("armed") is not False or state.get("in_progress") is not False
            or state.get("circulation") != "STOP"):
        raise ValueError("Disarm the pump gateway and stop circulation before applying")


def atomic_write(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
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
    args = parser.parse_args()
    try:
        changed, new = plan()
        if args.apply and changed:
            require_disarmed()
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"Water-only pump hold update not ready: {exc}\n")
    if not changed:
        print("Already installed; no files changed")
        return
    if args.check:
        print("Ready: reviewed live-mode module; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = TARGET.with_name(f"{TARGET.name}.before_water_only_hold_{stamp}")
    shutil.copy2(TARGET, backup)
    print(f"Backup: {backup}")
    try:
        atomic_write(TARGET, new)
    except OSError:
        shutil.copy2(backup, TARGET)
        raise
    print(f"Updated: {TARGET}")
    print("Service was NOT restarted. No GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
