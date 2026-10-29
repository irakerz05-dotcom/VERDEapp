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
    "app/plant_slots.py": ("pi_plant_slots_six.py", "21248c4a4aae70ad7c5b8c4f085e465069a9be12c5f71e848710300e9d887fb2"),
    "app/fusion/slots.py": ("pi_fusion_six.py", "d83cc7a73b35789be29dc5ca55eec3cb365f5ea9ed29f6ba0b0c5f4752487a6f"),
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
            raise ValueError(f"{relative}: installed source differs from reviewed ten-slot module")
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
        backup = path.with_name(f"{path.name}.before_six_slots_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, source in changes:
        atomic_write(path, source)
        print(f"Updated: {path}")
    print("Planting dates for P1–P6 are retained. Older P7–P10 rows remain archived in SQLite.")
    print("Service was NOT restarted; no GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
