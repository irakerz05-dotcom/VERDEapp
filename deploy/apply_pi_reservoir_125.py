#!/usr/bin/env python3
"""Guardedly install the 12.5 L pump pulse and volume caps on the Pi."""

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
OLD_HASHES = {
    "pump_runtime.py": "585aabe5421bc75abcdb7702f23711b7480207ac7aa867f0f21645d6c283fac6",
    "pump_decision.py": "6a9bd18765f7ad1c9c57defd62c29f48f2d8103f4dc1acbbf2415ee988529b5c",
}


def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()


def plan(target, source):
    changed = []
    for name in OLD_HASHES:
        current_path = target / "app/automation" / name
        source_path = source / ("pi_" + name)
        current = current_path.read_text(encoding="utf-8")
        replacement = source_path.read_text(encoding="utf-8")
        if current != replacement and digest(current) != OLD_HASHES[name]:
            raise ValueError(f"{name}: installed source differs from the reviewed version")
        compile(replacement, str(current_path), "exec")
        if current != replacement:
            changed.append((current_path, replacement))
    return changed


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


def require_disarmed_gateway(source):
    expected = digest((source / "pi_auto_pump_driver.py").read_text(encoding="utf-8"))
    installed = digest(GATEWAY.read_text(encoding="utf-8"))
    if installed != expected:
        raise ValueError("Install the reviewed 12.5 L protected gateway first")
    result = subprocess.run(("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
                            capture_output=True, text=True, timeout=15, check=True)
    status = json.loads(result.stdout)
    if status.get("armed") is not False or status.get("in_progress") is not False:
        raise ValueError("Pump gateway must be disarmed with no dose in progress")
    if status.get("circulation") != "STOP":
        raise ValueError("Circulation must be STOP during the guarded update")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=ROOT)
    args = parser.parse_args()
    source = Path(__file__).parent
    try:
        changed = plan(args.target, source)
        if args.apply:
            require_disarmed_gateway(source)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"12.5 L pump update not ready: {exc}\n")
    if not changed:
        print("Already installed; no backend files changed")
        return
    if args.check:
        print(f"Ready: {len(changed)} guarded backend modules; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changed:
        backup = path.with_name(f"{path.name}.before_reservoir_125_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, replacement in changed:
        atomic_write(path, replacement)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Pump gateway remains disarmed.")


if __name__ == "__main__":
    main()
