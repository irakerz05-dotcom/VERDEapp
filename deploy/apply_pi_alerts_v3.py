#!/usr/bin/env python3
"""Stop SMS for temporary unclassified slots; keep real camera faults and harvest notices."""

import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
PATCHES = (
    Path(__file__).with_name("pi_alerts_v3_from_v1.patch"),
    Path(__file__).with_name("pi_alerts_v3_from_v2.patch"),
)
FILES = (
    "app/notifications/__init__.py",
    "app/notifications/alert_policy.py",
    "app/notifications/sms_text.py",
)


def apply(root, patch, *options):
    return subprocess.run(["git", "-C", str(root), "apply", *options, str(patch)],
                          capture_output=True, text=True, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    root = args.target.resolve()
    if any(not patch.is_file() for patch in PATCHES):
        parser.exit(1, "Alert v3 patch files are missing\n")
    policy = root / "app/notifications/alert_policy.py"
    notifier = root / "app/notifications/__init__.py"
    if not policy.is_file() or not notifier.is_file():
        parser.exit(1, "Alert v1 must be installed first\n")
    if ('r"vision:slot:(10|[1-9]):harvest_ready"' in notifier.read_text(encoding="utf-8")
            and '"vision:unclassified_slots"' not in policy.read_text(encoding="utf-8")):
        print("Already installed; no files changed")
        return
    chosen = None
    errors = []
    for patch in PATCHES:
        result = apply(root, patch, "--check")
        if result.returncode == 0:
            chosen = patch
            break
        errors.append(f"{patch.name}: {(result.stderr or result.stdout).strip()}")
    if chosen is None:
        parser.exit(1, "Alert v3 patch not ready: " + " | ".join(errors) + "\n")
    if args.check:
        print(f"Ready: {chosen.name}; 3 guarded files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for relative in FILES:
        source = root / relative
        backup = source.with_name(f"{source.name}.before_alerts_v3_{stamp}")
        shutil.copy2(source, backup)
        print(f"Backup: {backup}")
    result = apply(root, chosen)
    if result.returncode:
        parser.exit(1, "Alert v3 patch failed: " +
                    (result.stderr or result.stdout).strip() + "\n")
    for relative in FILES:
        source = root / relative
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
        print(f"Updated: {source}")
    print("Service was NOT restarted. No SMS was sent by this installer.")


if __name__ == "__main__":
    main()
