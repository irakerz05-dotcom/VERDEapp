#!/usr/bin/env python3
"""Wait for final SIM800 SMS confirmation and avoid ambiguous duplicate retries."""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
PATCH = Path(__file__).with_name("pi_sms_confirmation.patch")
OLD = '''                if result.status in ("SENT", "NOT SENT — COOLDOWN"):
                    self.notification_delivered.add(issue_key)
                    self.notification_retry_after.pop(issue_key, None)
                else:
'''
NEW = '''                if result.status in ("SENT", "NOT SENT — COOLDOWN", "UNCONFIRMED"):
                    self.notification_delivered.add(issue_key)
                    self.notification_retry_after.pop(issue_key, None)
                    if result.status == "UNCONFIRMED":
                        break
                else:
'''


def git_apply(root, *args):
    return subprocess.run(["git", "-C", str(root), "apply", *args, str(PATCH)],
                          capture_output=True, text=True, encoding="utf-8")


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=BACKEND)
    args = parser.parse_args()
    root = args.target.resolve()
    service = root / "app/service.py"
    notifier = root / "app/notifications/__init__.py"
    if not PATCH.is_file() or not service.is_file() or not notifier.is_file():
        parser.exit(1, "Expected Pi service, notifier, and patch files are missing\n")
    source = service.read_text(encoding="utf-8")
    if NEW in source and "class SMSConfirmationUnknown" in notifier.read_text(encoding="utf-8"):
        print("Already installed; no files changed")
        return
    if source.count(OLD) != 1:
        parser.exit(1, "Service SMS dispatch differs from the reviewed anchor\n")
    desired = source.replace(OLD, NEW, 1)
    compile(desired, str(service), "exec")
    result = git_apply(root, "--check")
    if result.returncode:
        parser.exit(1, "SIM800 patch not ready: " +
                    (result.stderr or result.stdout).strip() + "\n")
    if args.check:
        print("Ready: 2 guarded backend files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path in (service, notifier):
        backup = path.with_name(f"{path.name}.before_sms_confirmation_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    result = git_apply(root)
    if result.returncode:
        parser.exit(1, "SIM800 patch failed: " +
                    (result.stderr or result.stdout).strip() + "\n")
    atomic_write(service, desired)
    compile(notifier.read_text(encoding="utf-8"), str(notifier), "exec")
    print("Updated service and SIM800 sender. Service was NOT restarted; no SMS was sent.")


if __name__ == "__main__":
    main()
