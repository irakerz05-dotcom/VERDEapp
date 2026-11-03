#!/usr/bin/env python3
"""Install guarded manual dosing policy; never switch GPIO or restart VERDE."""

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
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
SOURCES = {
    "pump_runtime.py": ("pi_pump_runtime.py", "e2b014bb47456808a414305977616ff7b78d30efc18b80fd369710cff5fd2d9d"),
    "pump_decision.py": ("pi_pump_decision.py", "17bcb66433caa602c8cba2ae72b20e1e22ffd47847c805588db5ef538c018635"),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plan(target=ROOT, source_dir=Path(__file__).parent):
    changes = []
    for name, (source_name, reviewed_hash) in SOURCES.items():
        target_file = target / "app/automation" / name
        old = target_file.read_bytes()
        new = (source_dir / source_name).read_bytes()
        if old != new and digest(old) != reviewed_hash:
            raise ValueError(f"{name}: installed version differs from reviewed source")
        compile(new, str(target_file), "exec")
        if old != new:
            changes.append((target_file, new))
    return changes


def require_disarmed(source_dir):
    if digest(GATEWAY.read_bytes()) != digest((source_dir / "pi_auto_pump_driver.py").read_bytes()):
        raise ValueError("Install the reviewed protected gateway first")
    result = subprocess.run(("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
                            check=True, capture_output=True, text=True, timeout=15)
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
    try:
        changes = plan()
        if args.apply and changes:
            require_disarmed(Path(__file__).parent)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"Manual dosing update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded automation modules; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_critical_manual_{stamp}")
        shutil.copy2(path, backup)
        backups.append((path, backup))
        print(f"Backup: {backup}")
    try:
        for path, data in changes:
            atomic_write(path, data)
            print(f"Updated: {path}")
    except OSError:
        for path, backup in backups:
            shutil.copy2(backup, path)
        raise
    print("Service was NOT restarted. No GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
