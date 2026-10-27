#!/usr/bin/env python3
"""Apply the reviewed alert and GSM change to the Pi's dirty backend tree.

--check is read-only. --apply backs up touched files and leaves verde.service
running until a separate restart. The patch does not change GPIO, calibration,
mode safety evaluation, recipient settings, or camera/model configuration.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")
PATCH = Path(__file__).with_name("pi_alerts_v1.patch")
SERVICE_BLOCKS = Path(__file__).with_name("pi_alerts_service_blocks.json")
TOUCHED = (
    "app/service.py",
    "app/notifications/__init__.py",
    "app/notifications/sms_text.py",
    "app/notifications/alert_policy.py",
)


def run_git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8")


def patch_service(source):
    blocks = json.loads(SERVICE_BLOCKS.read_text(encoding="utf-8"))
    for index, block in enumerate(blocks, 1):
        old, new = block["old"], block["new"]
        if source.count(old) != 1:
            raise ValueError(f"Service alert anchor {index} differs from reviewed source")
        source = source.replace(old, new, 1)
    compile(source, "app/service.py", "exec")
    return source


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def check(root):
    if not PATCH.is_file() or not SERVICE_BLOCKS.is_file():
        raise ValueError("Alert patch files are missing")
    if not (root / "app/service.py").is_file():
        raise ValueError("Pi backend service source is missing")
    service = (root / "app/service.py").read_text(encoding="utf-8")
    if "from app.notifications.alert_policy import enrich_issues" in service:
        if ("self.notification_retry_after = {}" in service
                and (root / "app/notifications/alert_policy.py").is_file()
                and "vision:slot:" in (root / "app/notifications/sms_text.py").read_text(encoding="utf-8")):
            return True, None
        raise ValueError("Alert patch is partially installed; inspect the backend before retrying")
    result = run_git(root, "apply", "--check", str(PATCH))
    if result.returncode:
        raise ValueError("Pi backend differs from reviewed alert anchors: "
                         + (result.stderr or result.stdout).strip())
    return False, patch_service(service)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    try:
        installed, desired_service = check(root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Alert patch not ready: {exc}\n")
    if args.check:
        print("Already installed; no files changed" if installed else
              "Ready: 4 guarded backend files; no files changed")
        return
    if installed:
        print("Already installed; no files changed or SMS sent")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for relative in TOUCHED:
        source = root / relative
        if source.is_file():
            backup = source.with_name(f"{source.name}.before_alerts_{stamp}")
            shutil.copy2(source, backup)
            print(f"Backup: {backup}")
    result = run_git(root, "apply", str(PATCH))
    if result.returncode:
        parser.exit(1, f"Alert patch failed: {(result.stderr or result.stdout).strip()}\n")
    atomic_write(root / "app/service.py", desired_service)
    for relative in TOUCHED:
        source = root / relative
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
        print(f"Updated: {source}")
    print("Service was NOT restarted. No SMS was sent by this installer.")


if __name__ == "__main__":
    main()
