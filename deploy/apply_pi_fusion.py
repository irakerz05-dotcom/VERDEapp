#!/usr/bin/env python3
"""Guardedly install the paper's descriptive fusion table in the dirty Pi checkout.

Fetch feature/sensor-vision-fusion in VERDE-Sensor-Integration first. Run --check
before --apply. This never edits calibration/config, restarts the service, or
changes actuation/SMS rules. A later restart may reopen existing SMS incidents.
"""

import argparse
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_BASE = "40c3e2313ac1d735b3de2af478ba6629baaac52c"
BACKEND_COMMIT = "1d47bb4"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")

CHANGES = [
    (
        "from app.fusion import PendingFusion",
        "from app.fusion import TableFusion, required_water_sensor_fault",
    ),
    (
        "        self.fusion = fusion or PendingFusion()",
        "        self.fusion = fusion or TableFusion()",
    ),
    (
        '            fusion = model_result(guarded(lambda: self.fusion.combine(water, plant)), ("High", "Medium", "Low"),\n'
        '                                  water.value is not None and plant.value is not None)',
        '            integrated = getattr(self, "integrated_sensor_service", None)\n'
        '            live_snapshot = None\n'
        '            if integrated is not None:\n'
        '                try:\n'
        '                    live_snapshot = integrated.snapshot()  # Cached; never start another hardware read.\n'
        '                except Exception:\n'
        '                    log.exception("Integrated sensor snapshot unavailable for fusion")\n'
        '            sensor_fault = required_water_sensor_fault(live_snapshot)\n'
        '            fusion_water = (Result("FAULT / ERROR", "Faulty Sensor", detail=sensor_fault)\n'
        '                            if sensor_fault else water)\n'
        '            vision_fault = (plant.status == "FAULT / ERROR"\n'
        '                            or camera.get("status") == "FAULT / ERROR")\n'
        '            fusion_plant = (Result("FAULT / ERROR", "Faulty Vision",\n'
        '                                   detail=plant.detail or camera.get("detail") or "No valid plant classification")\n'
        '                            if vision_fault else plant)\n'
        '            fusion = model_result(guarded(lambda: self.fusion.combine(fusion_water, fusion_plant)),\n'
        '                                  ("High", "Medium", "Low"),\n'
        '                                  fusion_water.value is not None and fusion_plant.value is not None)',
    ),
    (
        '            integrated = getattr(self, "integrated_sensor_service", None)\n'
        '            if integrated is not None:\n'
        '                try:\n'
        '                    issues = merge_live_sensor_issues(issues, integrated.snapshot())\n'
        '                except Exception:\n'
        '                    log.exception("Integrated sensor incidents unavailable")',
        '            if live_snapshot is not None:\n'
        '                issues = merge_live_sensor_issues(issues, live_snapshot)',
    ),
]


def source_at(root, commit, name):
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{name}"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    compile(result.stdout, name, "exec")
    return result.stdout


def prepare(root):
    module_name = "app/fusion/__init__.py"
    old_module = source_at(root, BACKEND_BASE, module_name)
    new_module = source_at(root, BACKEND_COMMIT, module_name)
    module_path = root / module_name
    current_module = module_path.read_text(encoding="utf-8")
    if current_module not in (old_module, new_module):
        raise ValueError(f"{module_name}: differs from reviewed base; preserve Pi changes and inspect manually")

    service_path = root / "app/service.py"
    service = service_path.read_text(encoding="utf-8")
    edits = 0
    for old, new in CHANGES:
        if service.count(new) == 1:
            continue
        if service.count(old) != 1:
            raise ValueError("app/service.py: fusion anchor missing or ambiguous; no files changed")
        service = service.replace(old, new, 1)
        edits += 1
    compile(service, "app/service.py", "exec")
    planned = {service_path: service, module_path: new_module}
    if current_module != new_module:
        edits += 1
    return planned, edits


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    try:
        planned, edits = prepare(root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Fusion patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {root}; {edits} guarded edits; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, contents in planned.items():
        if path.read_text(encoding="utf-8") == contents:
            continue
        backup = path.with_name(f"{path.name}.before_fusion_{stamp}")
        shutil.copy2(path, backup)
        atomic_write(path, contents)
        print(f"Updated {path} (backup: {backup})")
    print("Service was NOT restarted. SMS and safety configuration were NOT changed.")


if __name__ == "__main__":
    main()
