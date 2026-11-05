#!/usr/bin/env python3
"""Guardedly add one read-only V8 pest overlay route to the installed Pi web app."""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
SOURCE = Path(__file__).with_name("pi_pest_only_overlay.py")


def patch_web(source):
    old_import = "from app.plant_slots import PlantSlotStore\n"
    new_import = old_import + "from app.ml.vision.pest_overlay import pest_overlay\n"
    old_route = '            if path == "/api/camera/annotated":\n'
    new_route = ('            if path == "/api/camera/pest-overlay":\n'
                 '                try:\n'
                 '                    if service.vision_store is None:\n'
                 '                        raise LookupError("V8 vision report unavailable")\n'
                 '                    overlay = pest_overlay(service.vision_store, service.camera_capture)\n'
                 '                except (OSError, ValueError, TypeError, KeyError, TimeoutError, LookupError):\n'
                 '                    return self.reply(503, {"error": "Matching V8 pest photo unavailable"})\n'
                 '                return self.reply(200, overlay)\n') + old_route
    for old, new, label in ((old_import, new_import, "import"), (old_route, new_route, "route")):
        if source.count(new) == 1:
            continue
        if source.count(old) != 1:
            raise ValueError(f"Installed web {label} differs from reviewed version")
        source = source.replace(old, new, 1)
    compile(source, "app/web/__init__.py", "exec")
    return source


def plan(root=ROOT):
    target = root / "app/web/__init__.py"
    helper = root / "app/ml/vision/pest_overlay.py"
    updated = patch_web(target.read_text(encoding="utf-8"))
    helper_source = SOURCE.read_text(encoding="utf-8")
    compile(helper_source, str(helper), "exec")
    return [(path, body) for path, body in ((target, updated), (helper, helper_source))
            if not path.exists() or path.read_text(encoding="utf-8") != body]


def atomic_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
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
    try:
        changes = plan(args.target)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Pest overlay update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded pest-only files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        if path.exists():
            backup = path.with_name(f"{path.name}.before_pest_overlay_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, body in changes:
        atomic_write(path, body)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Main camera, worker, and pumps were untouched.")


if __name__ == "__main__":
    main()
