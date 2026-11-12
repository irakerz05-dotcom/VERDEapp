#!/usr/bin/env python3
"""Apply a fixed -0.7 C water-temperature correction on the Pi.

--check validates the installed reader without changing it. --apply backs up
and patches only the sensor service source. Neither mode restarts services or
operates GPIO. The running service uses the correction after its next restart.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


TARGET = Path("/home/verde/VERDE-Sensor-Integration/verde_sensor_service.py")
MARKER = "# VERDE-WATER-TEMPERATURE-OFFSET-v1"
OLD = '''                value = read_ds18b20(self.ds18b20_device, raw)
                self.ds18b20_failures = 0
                status = f"OK: {self.ds18b20_device.name}; no software offset"
                self._sensor_diagnostic("water_temperature", raw[0] if raw else None,
                                        value, status, attempt=attempt)
                return {
                    "value_C": value, "unit": "C",
                    "classification": classify_water_temperature(value),
                    "status": status, "read_timestamp": timestamp_now(),
                    "read_error": None,
                }
'''
NEW = '''                # VERDE-WATER-TEMPERATURE-OFFSET-v1
                raw_value = read_ds18b20(self.ds18b20_device, raw)
                value = raw_value - 0.7
                self.ds18b20_failures = 0
                status = f"OK: {self.ds18b20_device.name}; software offset -0.7 C"
                self._sensor_diagnostic("water_temperature", raw[0] if raw else None,
                                        value, status, attempt=attempt)
                return {
                    "value_C": value, "raw_value_C": raw_value, "unit": "C",
                    "classification": classify_water_temperature(value),
                    "status": status, "read_timestamp": timestamp_now(),
                    "read_error": None,
                }
'''


def plan(source: str) -> tuple[str, bool]:
    if MARKER in source:
        if source.count(MARKER) != 1 or source.count(NEW) != 1:
            raise ValueError("Water-temperature offset patch is incomplete")
        compile(source, str(TARGET), "exec")
        return source, False
    if source.count(OLD) != 1 or source.count("# VERDE-SENSOR-RECOVERY-v3") != 1:
        raise ValueError("Installed sensor reader differs from the reviewed version")
    updated = source.replace(OLD, NEW, 1)
    compile(updated, str(TARGET), "exec")
    return updated, True


def atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        original = TARGET.read_text(encoding="utf-8")
        updated, changed = plan(original)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Water-temperature offset not ready: {exc}\n")
    if not changed:
        print("Already installed; no files changed")
        return
    if args.check:
        print("Ready: fixed -0.7 C water-temperature correction; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = TARGET.with_name(f"{TARGET.name}.before_water_temp_offset_{stamp}")
    shutil.copy2(TARGET, backup)
    print(f"Backup: {backup}")
    try:
        atomic_write(TARGET, updated)
    except OSError:
        shutil.copy2(backup, TARGET)
        raise
    print(f"Updated: {TARGET}")
    print("Service was NOT restarted. No pump command or GPIO action was issued.")


if __name__ == "__main__":
    main()
