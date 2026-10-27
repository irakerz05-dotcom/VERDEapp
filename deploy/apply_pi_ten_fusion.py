#!/usr/bin/env python3
"""Guardedly expose Table 3 fusion for ten fixed NFT positions on the Pi.

Reads the existing fresh YOLO artifact; never changes GPIO, automation, SMS,
calibration, or the aggregate fusion. --check writes nothing; --apply backs up
the service and does not restart it.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
MODULE = Path(__file__).with_name("pi_fusion_ten.py")


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected exactly one reviewed source anchor")
    return source.replace(old, new, 1)


def patch_service(source):
    changes = (
        ("from app.fusion import TableFusion, required_water_sensor_fault\n",
         "from app.fusion import TableFusion, required_water_sensor_fault\n"
         "from app.fusion.slots import fuse_vision_artifact\n", "fusion import"),
        ("            automation = evaluate(self.selected_mode, readings, water, self.config[\"limits\"], bool(self.database_error))\n",
         "            fusion_by_slot = None\n"
         "            try:\n"
         "                fusion_by_slot = fuse_vision_artifact(\n"
         "                    fusion_water, plant, camera, getattr(self, \"vision_store\", None))\n"
         "            except Exception:\n"
         "                log.exception(\"Ten-slot fusion unavailable for this cycle\")\n"
         "            automation = evaluate(self.selected_mode, readings, water, self.config[\"limits\"], bool(self.database_error))\n",
         "descriptive slot fusion"),
        ('                "pest_detection": pest.as_dict(), "fusion": fusion.as_dict(),\n',
         '                "pest_detection": pest.as_dict(), "fusion": fusion.as_dict(),\n'
         '                "fusion_by_slot": fusion_by_slot,\n', "fusion API field"),
    )
    for old, new, label in changes:
        source = replace_once(source, old, new, label)
    compile(source, "app/service.py", "exec")
    return source


def prepare(root=BACKEND):
    service = root / "app/service.py"
    target = root / "app/fusion/slots.py"
    source = service.read_text(encoding="utf-8")
    if ("self.vision_store = VisionArtifactStore(" not in source
            or "fusion_water =" not in source
            or '"water_quality_experimental"' not in source):
        raise ValueError("Expected Pi vision artifact and prototype water fusion are missing")
    desired_module = MODULE.read_text(encoding="utf-8")
    compile(desired_module, str(target), "exec")
    if target.exists() and target.read_text(encoding="utf-8") != desired_module:
        raise ValueError("Existing per-slot fusion module differs; no files changed")
    desired_service = patch_service(source)
    planned = {service: desired_service, target: desired_module}
    return planned, sum(not path.exists() or path.read_text(encoding="utf-8") != data
                        for path, data in planned.items())


def atomic_write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
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
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    try:
        planned, edits = prepare(args.target.resolve())
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Ten-slot fusion patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {edits} guarded file updates; source syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, contents in planned.items():
        if path.exists() and path.read_text(encoding="utf-8") == contents:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.before_ten_fusion_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
        atomic_write(path, contents)
        print(f"Updated: {path}")
    print("Service was NOT restarted. GPIO, safety, and SMS rules were not changed.")


if __name__ == "__main__":
    main()
