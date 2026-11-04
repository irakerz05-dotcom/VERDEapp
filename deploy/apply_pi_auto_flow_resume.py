#!/usr/bin/env python3
"""Install guarded Full-mode recovery after a prior supervised flow arm.

Apply only with the gateway disarmed. This script changes no GPIO and does not
restart the service.
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


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
TARGET = ROOT / "app/automation/pump_runtime.py"
SERVICE = ROOT / "app/service.py"
SOURCE = Path(__file__).with_name("pi_pump_runtime.py")
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
GATEWAY_SOURCE = Path(__file__).with_name("pi_auto_pump_driver.py")
EXPECTED_OLD = "6e0ad68964ca7758252b423d9a290e96c7a3a080883ad0ee25e30a06483377da"
SERVICE_MARKER = "# VERDE-AUTO-FLOW-RESUME-v1"
OLD_CONFIRM = '''    def confirm(self, requested_pump=None):
        with self.lock:
            if self.selected_mode != SEMI:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            fresh_state = self.tick()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot, requested_pump)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
NEW_CONFIRM = '''    def confirm(self, requested_pump=None):
        with self.lock:
            # VERDE-AUTO-FLOW-RESUME-v1
            fresh_state = self.tick()
            automation = fresh_state.get("automation", {})
            critical_override = (self.selected_mode == FULL
                                 and automation.get("active_mode") == SEMI
                                 and automation.get("critical_manual_dose") is True)
            if self.selected_mode != SEMI and not critical_override:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot, requested_pump)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plan(target=TARGET, source=SOURCE, service=SERVICE):
    old = target.read_bytes()
    new = source.read_bytes()
    if digest(old) not in (EXPECTED_OLD, digest(new)):
        raise ValueError("Installed pump runtime differs from reviewed version")
    compile(new, str(target), "exec")
    if b'not automation.get("circulation_stop_required", True)' not in new:
        raise ValueError("Critical circulation stop guard is missing")
    if b'self.command("resume-flow")' not in new:
        raise ValueError("Flow recovery command is missing")
    service_old = service.read_text(encoding="utf-8")
    if SERVICE_MARKER in service_old:
        if NEW_CONFIRM not in service_old or OLD_CONFIRM in service_old:
            raise ValueError("Service recovery marker has mismatched confirm code")
        service_new = service_old
    else:
        if service_old.count(OLD_CONFIRM) != 1:
            raise ValueError("Service confirmation anchor differs from reviewed version")
        service_new = service_old.replace(OLD_CONFIRM, NEW_CONFIRM, 1)
    compile(service_new, str(service), "exec")
    changes = []
    if old != new:
        changes.append((target, new))
    if service_old != service_new:
        changes.append((service, service_new.encode("utf-8")))
    return changes


def require_disarmed():
    if digest(GATEWAY.read_bytes()) != digest(GATEWAY_SOURCE.read_bytes()):
        raise ValueError("Install the reviewed protected gateway first")
    result = subprocess.run(("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
                            check=True, capture_output=True, text=True, timeout=15)
    state = json.loads(result.stdout)
    if (state.get("armed") is not False or state.get("in_progress") is not False
            or state.get("circulation") != "STOP"):
        raise ValueError("Disarm the pump gateway before applying")


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
        parser.exit(1, f"Automatic flow recovery update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded backend files; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_auto_flow_resume_{stamp}")
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
