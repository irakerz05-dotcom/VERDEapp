#!/usr/bin/env python3
"""Guardedly connect VERDE's service to the disarmed protected pump gateway."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
IMPORT_OLD = "from app.automation.live_mode import evaluate_live\n"
IMPORT_NEW = (IMPORT_OLD + "from app.automation.pump_runtime import PumpRuntime\n")
ACTUATOR_OLD = "        self.actuators = DisabledActuators()"
ACTUATOR_NEW = "        self.actuators = PumpRuntime()"
STARTUP_OLD = ('        self.event("actuator", "Startup: all outputs commanded '
               'SAFE/OFF; physical hardware unavailable")')
STARTUP_NEW = ('        self.event("actuator", "Startup: protected pump gateway '
               'requested SAFE/OFF")')
TAIL_OLD = '''                self.actuators.all_off("Database error")
            return copy.deepcopy(self.state)'''
TAIL_NEW = '''                self.actuators.all_off("Database error")
                self.selected_mode = SEMI
            else:
                # VERDE-PUMP-RUNTIME-v1: gateway starts disarmed and owns GPIO.
                applied = self.actuators.apply(
                    self.state["automation"], live_snapshot,
                    experimental_water, plant, camera)
                if applied["active_mode"] == SEMI and self.selected_mode == FULL:
                    self.selected_mode = SEMI
                    self.event("mode", "Pump controller safety override selected Semi-Automation", {
                        "reason": applied.get("override_reason"),
                    })
                self.state["automation"] = applied
            return copy.deepcopy(self.state)'''
SHUTDOWN_OLD = ('        self.event("actuator", "Shutdown: SAFE/OFF requested; '
                'physical hardware unavailable")')
SHUTDOWN_NEW = ('        self.event("actuator", "Shutdown: protected pump gateway '
                'requested SAFE/OFF")')


def replace_once(source, old, new, label):
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected one reviewed anchor, found {source.count(old)}")
    return source.replace(old, new, 1)


def plan(service_source, runtime_source, decision_source):
    source = replace_once(service_source, IMPORT_OLD, IMPORT_NEW, "runtime import")
    source = replace_once(source, ACTUATOR_OLD, ACTUATOR_NEW, "actuator setup")
    source = replace_once(source, STARTUP_OLD, STARTUP_NEW, "startup event")
    source = replace_once(source, TAIL_OLD, TAIL_NEW, "sample safety tail")
    source = replace_once(source, SHUTDOWN_OLD, SHUTDOWN_NEW, "shutdown event")
    compile(source, "app/service.py", "exec")
    compile(runtime_source, "app/automation/pump_runtime.py", "exec")
    compile(decision_source, "app/automation/pump_decision.py", "exec")
    return source


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
    runtime_path = args.target / "app/automation/pump_runtime.py"
    decision_path = args.target / "app/automation/pump_decision.py"
    try:
        service = service_path.read_text(encoding="utf-8")
        runtime = Path(__file__).with_name("pi_pump_runtime.py").read_text(encoding="utf-8")
        decision = Path(__file__).with_name("pi_pump_decision.py").read_text(encoding="utf-8")
        updated = plan(service, runtime, decision)
        prior_runtime = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else None
        prior_decision = decision_path.read_text(encoding="utf-8") if decision_path.exists() else None
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Pump runtime patch not ready: {exc}\n")
    changed = [(service_path, service, updated),
               (runtime_path, prior_runtime, runtime),
               (decision_path, prior_decision, decision)]
    changed = [(path, old, new) for path, old, new in changed if old != new]
    if not changed:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changed)} guarded backend files; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, old, _ in changed:
        if old is not None:
            backup = path.with_name(f"{path.name}.before_pump_runtime_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, _, new in changed:
        atomic_write(path, new)
        print(f"Updated: {path}")
    print("Service was NOT restarted. The protected gateway remains disarmed.")


if __name__ == "__main__":
    main()
