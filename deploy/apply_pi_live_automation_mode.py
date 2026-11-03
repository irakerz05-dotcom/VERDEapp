#!/usr/bin/env python3
"""Guardedly switch Pi mode evaluation to live sensor data; leave outputs disabled."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
MODULE = Path(__file__).with_name("pi_live_automation_mode.py")
IMPORT_OLD = "from app.automation import DisabledActuators, evaluate, MODES, SEMI\n"
IMPORT_NEW = ("from app.automation import DisabledActuators, evaluate, MODES, SEMI, FULL\n"
              "from app.automation.live_mode import evaluate_live\n")
CALL_OLD = ('            automation = evaluate(self.selected_mode, readings, water, '
            'self.config["limits"], bool(self.database_error))')
CALL_NEW = '''            # VERDE-LIVE-AUTOMATION-MODE-v1; hardware outputs remain disabled.
            automation = evaluate_live(
                self.selected_mode, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error), pest=pest)'''


def replace_once(source, old, new, name):
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{name}: expected one reviewed anchor, found {source.count(old)}")
    return source.replace(old, new, 1)


def plan(service_source, module_source):
    updated = replace_once(service_source, IMPORT_OLD, IMPORT_NEW, "automation import")
    updated = replace_once(updated, CALL_OLD, CALL_NEW, "sample mode evaluation")
    compile(updated, "app/service.py", "exec")
    compile(module_source, "app/automation/live_mode.py", "exec")
    return updated


def atomic_write(path, source):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
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
    module_path = args.target / "app/automation/live_mode.py"
    try:
        old_service = service_path.read_text(encoding="utf-8")
        new_module = MODULE.read_text(encoding="utf-8")
        new_service = plan(old_service, new_module)
        old_module = module_path.read_text(encoding="utf-8") if module_path.exists() else None
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Live mode patch not ready: {exc}\n")
    changed = ((service_path, old_service, new_service),
               (module_path, old_module, new_module))
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
            backup = path.with_name(f"{path.name}.before_live_mode_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, _, new in changed:
        atomic_write(path, new)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Pump outputs remain disabled; no GPIO was switched.")


if __name__ == "__main__":
    main()
