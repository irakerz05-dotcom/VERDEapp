#!/usr/bin/env python3
"""Guardedly switch planting records and slot fusion to six fixed NFT places."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
MODULES = {
    "app/plant_slots.py": ("pi_plant_slots_six_v4.py", "f5d99043b0d6241795014fc97b4bbfb6cb25539f3b7565019c963e33c142dd32"),
    "app/fusion/slots.py": ("pi_fusion_six.py", "7539eb913d28ea3cda76cf08699dcef5ef0b45015b7d6b47ad9066c11646986f"),
}


def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()


def plan(root=BACKEND):
    web = (root / "app/web/__init__.py").read_text(encoding="utf-8")
    service = (root / "app/service.py").read_text(encoding="utf-8")
    if "from app.plant_slots import PlantSlotStore" not in web:
        raise ValueError("Planting-record route is missing")
    if "from app.fusion.slots import fuse_vision_artifact" not in service:
        raise ValueError("Per-slot fusion integration is missing")
    changes = []
    for relative, (source_name, expected_hash) in MODULES.items():
        target = root / relative
        current = target.read_text(encoding="utf-8")
        proposed = Path(__file__).with_name(source_name).read_text(encoding="utf-8")
        if current != proposed and digest(current) != expected_hash:
            raise ValueError(f"{relative}: installed source differs from reviewed eight-slot module")
        compile(proposed, relative, "exec")
        if current != proposed:
            changes.append((target, proposed))
    return changes


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    try:
        changes = plan(args.target)
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"Six-slot update not ready: {exc}\n")
    if not changes:
        print("Already installed; no backend files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded backend modules; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_six_slots_v4_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, source in changes:
        atomic_write(path, source)
        print(f"Updated: {path}")
    print("P1–P6 dates migrate to plant_slots_v4; P7/P8 remain archived in plant_slots_v3.")
    print("Service was NOT restarted; no GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
