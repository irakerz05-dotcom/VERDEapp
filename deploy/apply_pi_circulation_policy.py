#!/usr/bin/env python3
"""Guardedly separate Critical-mode override from circulation fault-stop."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
EXPECTED_OLD = {
    "live_mode.py": "5110114902d908e872af74fb14d91da0e8c712329c593b09f0f7049467380181",
    "pump_runtime.py": "045b19f8f3b46e085d685c7febb17b02859f47bae6ab6c990a4f242175871642",
    "pump_decision.py": "dc2fb835af3d1b7369905cd2d14872e8d1c4676f48000940cfdb4d79f8c251de",
}
SOURCE = {
    "live_mode.py": "pi_live_automation_mode.py",
    "pump_runtime.py": "pi_pump_runtime.py",
    "pump_decision.py": "pi_pump_decision.py",
}


def digest(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def atomic_write(path, source):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
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
    parser.add_argument("--target", type=Path, default=ROOT)
    args = parser.parse_args()
    service = args.target / "app/service.py"
    try:
        if "VERDE-PUMP-RUNTIME-v1" not in service.read_text(encoding="utf-8"):
            raise ValueError("Installed service does not have the pump runtime")
        changes = []
        for name, source_name in SOURCE.items():
            path = args.target / "app/automation" / name
            old = path.read_text(encoding="utf-8")
            new = Path(__file__).with_name(source_name).read_text(encoding="utf-8")
            compile(new, str(path), "exec")
            if digest(old) not in (EXPECTED_OLD[name], digest(new)):
                raise ValueError(f"{path}: installed source differs from reviewed version")
            if old != new:
                changes.append((path, new))
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Circulation policy patch not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded modules; source syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_circulation_policy_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, new in changes:
        atomic_write(path, new)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Pump gateway remains disarmed.")


if __name__ == "__main__":
    main()
