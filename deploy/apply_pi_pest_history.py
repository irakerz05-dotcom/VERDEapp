#!/usr/bin/env python3
"""Retain enough raw camera captures for delayed V8 pest annotations."""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
HELPER = Path(__file__).with_name("pi_pest_only_overlay.py")


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"Installed {label} differs from reviewed version")
    return source.replace(old, new, 1)


def plan(root=ROOT):
    capture = root / "app/camera/capture.py"
    web = root / "app/web/__init__.py"
    helper = root / "app/ml/vision/pest_overlay.py"
    capture_text = capture.read_text(encoding="utf-8")
    capture_text = replace_once(capture_text, "HISTORY_LIMIT = 5\n", "HISTORY_LIMIT = 12\n", "camera history limit")
    capture_text = replace_once(capture_text,
        'HISTORY_ID = re.compile(r"capture-[0-4]\\.jpg\\Z")',
        'HISTORY_ID = re.compile(r"capture-(?:[0-9]|1[01])\\.jpg\\Z")',
        "camera history identifiers")
    web_text = replace_once(web.read_text(encoding="utf-8"),
        'return self.reply(200, {"captures": service.camera_capture.history(), "limit": 5})',
        'return self.reply(200, {"captures": service.camera_capture.history(), "limit": 12})',
        "camera history response")
    helper_text = HELPER.read_text(encoding="utf-8")
    for path, body in ((capture, capture_text), (web, web_text), (helper, helper_text)):
        compile(body, str(path), "exec")
    return [(path, body) for path, body in ((capture, capture_text), (web, web_text), (helper, helper_text))
            if not path.exists() or path.read_text(encoding="utf-8") != body]


def atomic_write(path, body):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
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
        parser.exit(1, f"Pest history update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded pest history files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        if path.exists():
            backup = path.with_name(f"{path.name}.before_pest_history_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, body in changes:
        atomic_write(path, body)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Main camera route, vision worker, and pumps were untouched.")


if __name__ == "__main__":
    main()
