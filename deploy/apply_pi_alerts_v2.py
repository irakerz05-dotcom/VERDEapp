#!/usr/bin/env python3
"""Group unclassified camera slots into one alert after alert installer v1."""

import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
PATCH = Path(__file__).with_name("pi_alerts_v2.patch")
FILES = (
    "app/notifications/__init__.py",
    "app/notifications/alert_policy.py",
    "app/notifications/sms_text.py",
)


def git_apply(root, *args):
    return subprocess.run(["git", "-C", str(root), "apply", *args, str(PATCH)],
                          capture_output=True, text=True, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    root = args.target.resolve()
    if not PATCH.is_file():
        parser.exit(1, "Alert v2 patch is missing\n")
    module = root / "app/notifications/alert_policy.py"
    if not module.is_file():
        parser.exit(1, "Alert v1 must be installed first\n")
    if '"vision:unclassified_slots"' in module.read_text(encoding="utf-8"):
        print("Already installed; no files changed")
        return
    result = git_apply(root, "--check")
    if result.returncode:
        parser.exit(1, "Alert v2 patch not ready: " +
                    (result.stderr or result.stdout).strip() + "\n")
    if args.check:
        print("Ready: 3 guarded notification files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for relative in FILES:
        source = root / relative
        backup = source.with_name(f"{source.name}.before_alerts_v2_{stamp}")
        shutil.copy2(source, backup)
        print(f"Backup: {backup}")
    result = git_apply(root)
    if result.returncode:
        parser.exit(1, "Alert v2 patch failed: " +
                    (result.stderr or result.stdout).strip() + "\n")
    for relative in FILES:
        source = root / relative
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
        print(f"Updated: {source}")
    print("Service was NOT restarted. No SMS was sent by this installer.")


if __name__ == "__main__":
    main()
