#!/usr/bin/env python3
"""Guardedly enable farmer-confirmed Semi doses through the protected gateway."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
EXPECTED_INSTALLED = {
    "app/automation/pump_runtime.py": "e15b38f48eefdb99465f33f7db79b606459d67536902e7ea2a678066e40d2f00",
    "app/automation/pump_decision.py": "73e3453444137524ab483d1fb970b747132d3b02523b357cde2df0a97c0e699b",
}
SERVICE_OLD = '''    def confirm(self):
        with self.lock:
            result = self.actuators.request("Farmer confirmed recommendation")
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
SERVICE_NEW = '''    def confirm(self, requested_pump=None):
        with self.lock:
            if self.selected_mode != SEMI:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            fresh_state = self.tick()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot, requested_pump)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
WEB_OLD = '''                if path == "/api/confirm":
                    return self.reply(409, service.confirm())'''
WEB_NEW = '''                if path == "/api/confirm":
                    requested_pump = body.get("pump")
                    result = service.confirm(requested_pump)
                    return self.reply(200 if result.get("status") == "DOSED" else 409, result)'''


def replace_once(source, old, new, label):
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected one reviewed anchor, found {source.count(old)}")
    return source.replace(old, new, 1)


def plan(service, web, runtime, decision):
    if "VERDE-PUMP-RUNTIME-v1" not in service:
        raise ValueError("Protected pump runtime is not installed")
    updated_service = replace_once(service, SERVICE_OLD, SERVICE_NEW, "service confirmation")
    updated_web = replace_once(web, WEB_OLD, WEB_NEW, "web confirmation")
    for name, source in (("app/service.py", updated_service),
                         ("app/web/__init__.py", updated_web),
                         ("app/automation/pump_runtime.py", runtime),
                         ("app/automation/pump_decision.py", decision)):
        compile(source, name, "exec")
    return updated_service, updated_web


def atomic_write(path, source):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
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
    service_path = args.target / "app/service.py"
    web_path = args.target / "app/web/__init__.py"
    runtime_path = args.target / "app/automation/pump_runtime.py"
    decision_path = args.target / "app/automation/pump_decision.py"
    try:
        service = service_path.read_text(encoding="utf-8")
        web = web_path.read_text(encoding="utf-8")
        old_runtime = runtime_path.read_text(encoding="utf-8")
        old_decision = decision_path.read_text(encoding="utf-8")
        runtime = Path(__file__).with_name("pi_pump_runtime.py").read_text(encoding="utf-8")
        decision = Path(__file__).with_name("pi_pump_decision.py").read_text(encoding="utf-8")
        for label, old, new in (("app/automation/pump_runtime.py", old_runtime, runtime),
                                ("app/automation/pump_decision.py", old_decision, decision)):
            if old != new and hashlib.sha256(old.encode()).hexdigest() != EXPECTED_INSTALLED[label]:
                raise ValueError(f"{label}: installed version differs from the reviewed circulation policy")
        updated_service, updated_web = plan(service, web, runtime, decision)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Pump confirmation patch not ready: {exc}\n")
    changed = [(service_path, service, updated_service),
               (web_path, web, updated_web),
               (runtime_path, old_runtime, runtime),
               (decision_path, old_decision, decision)]
    changed = [(path, old, new) for path, old, new in changed if old != new]
    if not changed:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changed)} guarded backend files; source syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _, _ in changed:
        backup = path.with_name(f"{path.name}.before_pump_confirm_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, _, new in changed:
        atomic_write(path, new)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Protected gateway remains disarmed.")


if __name__ == "__main__":
    main()
