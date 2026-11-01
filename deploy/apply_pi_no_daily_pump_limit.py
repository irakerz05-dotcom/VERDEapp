#!/usr/bin/env python3
"""Guardedly replace only the installed pump decision after gateway update."""

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


TARGET = Path("/home/verde/VERDE-Sensor-Integration/app/automation/pump_decision.py")
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
OLD_DECISION_SHA256 = "e51350b50b1446a5ff38196386e2ecc87eb847643459b3ae78d3c8671f979558"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check(target, source):
    old = target.read_bytes()
    new = source.read_bytes()
    if digest(old) not in {OLD_DECISION_SHA256, digest(new)}:
        raise ValueError("Installed decision differs from the reviewed 18 L version")
    compile(new, str(target), "exec")
    return old != new


def require_stopped_gateway(source):
    if digest(GATEWAY.read_bytes()) != digest(source.read_bytes()):
        raise ValueError("Install the reviewed updated gateway first")
    result = subprocess.run(
        ("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
        capture_output=True, text=True, timeout=15, check=True,
    )
    state = json.loads(result.stdout)
    if state.get("armed") is not False or state.get("in_progress") is not False:
        raise ValueError("Gateway must be disarmed with no dose in progress")
    if state.get("circulation") != "STOP":
        raise ValueError("Circulation must be stopped during the update")


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
    source = Path(__file__).with_name("pi_pump_decision.py")
    try:
        changed = check(TARGET, source)
        if args.apply:
            require_stopped_gateway(Path(__file__).with_name("pi_auto_pump_driver.py"))
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"Daily-limit update not ready: {exc}\n")
    if not changed:
        print("Already installed; no backend file changed")
        return
    if args.check:
        print("Ready: reviewed 18 L pump decision; no file changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = TARGET.with_name(f"{TARGET.name}.before_no_daily_limit_{stamp}")
    shutil.copy2(TARGET, backup)
    print(f"Backup: {backup}")
    atomic_write(TARGET, source.read_bytes())
    print(f"Updated: {TARGET}")
    print("Service was NOT restarted; no GPIO was switched")


if __name__ == "__main__":
    main()
