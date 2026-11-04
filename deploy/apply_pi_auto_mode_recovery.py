#!/usr/bin/env python3
"""Install automatic Full-mode selection after fresh water readings recover.

This changes service code only. It does not issue a pump command or restart the
service. The existing gateway still decides whether physical dosing can run.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

TARGET = Path("/home/verde/VERDE-Sensor-Integration/app/service.py")
MARKER = "# VERDE-AUTO-MODE-RECOVERY-v1"
EARLY_NEW = '''            # VERDE-LIVE-AUTOMATION-MODE-v1; hardware outputs remain disabled.
            # VERDE-PUMP-MODE-RESUME-v2: retain the farmer's requested mode.
            automation = evaluate_live(
                self.selected_mode, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error), pest=pest)'''
REPLACEMENT = '''            # VERDE-LIVE-AUTOMATION-MODE-v1; hardware outputs remain disabled.
            # VERDE-PUMP-MODE-RESUME-v2: retain the farmer's requested mode.
            ''' + MARKER + '''
            recovered = evaluate_live(
                FULL, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error), pest=pest)
            if (self.selected_mode == SEMI
                    and getattr(experimental_water, "value", None) in ("Optimal", "Suboptimal")
                    and not recovered["override"] and not recovered.get("hold_reason")):
                self.selected_mode = FULL
                self.event("mode", "Fresh water readings restored Full Automation", {
                    "water_quality": experimental_water.value,
                })
            automation = evaluate_live(
                self.selected_mode, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error), pest=pest)'''


def plan(target=TARGET):
    original = target.read_text(encoding="utf-8")
    if MARKER in original:
        if REPLACEMENT not in original or EARLY_NEW in original:
            raise ValueError("Installed auto-mode marker differs from reviewed patch")
        return None
    if original.count(EARLY_NEW) != 1:
        raise ValueError("Installed service mode anchor differs from reviewed version")
    updated = original.replace(EARLY_NEW, REPLACEMENT, 1)
    compile(updated, str(target), "exec")
    return updated.encode("utf-8")


def apply(target, data):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = target.with_name(f"{target.name}.before_auto_mode_recovery_{stamp}")
    shutil.copy2(target, backup)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Backup: {backup}")
    print(f"Updated: {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        updated = plan()
        if updated is None:
            print("Already installed; no files changed")
        elif args.check:
            print("Ready: guarded service mode transition; syntax valid; no files changed")
        else:
            apply(TARGET, updated)
            print("Service was NOT restarted; no pump command was issued")
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Automatic mode recovery update not ready: {exc}\n")


if __name__ == "__main__":
    main()
