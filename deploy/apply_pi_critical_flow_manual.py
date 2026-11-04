#!/usr/bin/env python3
"""Install Critical dashboard confirmation with supervised flow arming."""

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


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
TARGET = ROOT / "app/automation/pump_runtime.py"
SOURCE = Path(__file__).with_name("pi_pump_runtime.py")
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
GATEWAY_SOURCE = Path(__file__).with_name("pi_auto_pump_driver.py")
EXPECTED_OLD = "6d4ad33a9fa108b5d85e0db2f5481539e14a3fb7430b5f536bb27705a4a69776"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plan(target=TARGET, source=SOURCE):
    old, new = target.read_bytes(), source.read_bytes()
    if old != new and digest(old) != EXPECTED_OLD:
        raise ValueError("Installed pump runtime differs from reviewed version")
    compile(new, str(target), "exec")
    if '"CRITICAL — FARMER CONFIRMATION AVAILABLE"'.encode("utf-8") not in new:
        raise ValueError("Critical confirmation anchor is missing")
    if b'gateway.get("circulation") != "STOP"' not in new:
        raise ValueError("Stopped circulation guard is missing")
    return [] if old == new else [(target, new)]


def require_disarmed():
    if digest(GATEWAY.read_bytes()) != digest(GATEWAY_SOURCE.read_bytes()):
        raise ValueError("Install the reviewed protected gateway first")
    result = subprocess.run(("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
                            check=True, capture_output=True, text=True, timeout=15)
    state = json.loads(result.stdout)
    if (state.get("armed") is not False or state.get("in_progress") is not False
            or state.get("circulation") != "STOP"):
        raise ValueError("Disarm the gateway before applying")


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
        changes = plan()
        if args.apply and changes:
            require_disarmed()
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"Critical confirmation update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print("Ready: guarded pump runtime; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = TARGET.with_name(f"{TARGET.name}.before_critical_flow_manual_{stamp}")
    shutil.copy2(TARGET, backup)
    print(f"Backup: {backup}")
    try:
        atomic_write(TARGET, changes[0][1])
    except OSError:
        shutil.copy2(backup, TARGET)
        raise
    print(f"Updated: {TARGET}")
    print("Service was NOT restarted. No GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
