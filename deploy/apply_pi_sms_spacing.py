#!/usr/bin/env python3
"""Install a shared 30-second gap between all Pi GSM SMS submissions."""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
NOTIFIER_EDITS = (
    ('    PHONE = re.compile(r"^\\+?[0-9]{7,15}$")\n',
     '    PHONE = re.compile(r"^\\+?[0-9]{7,15}$")\n'
     '    MIN_SUBMISSION_GAP_SECONDS = 30\n'),
    ('        self._last_message = None\n\n    def _open(self):',
     '        self._last_message = None\n'
     '        self._last_submission_at = None\n\n    def _open(self):'),
    ('                return Result("NOT SENT — COOLDOWN", detail="Duplicate alert suppressed")\n\n'
     '            last_error = None',
     '                return Result("NOT SENT — COOLDOWN", detail="Duplicate alert suppressed")\n'
     '            if self._last_submission_at is not None:\n'
     '                remaining = self.MIN_SUBMISSION_GAP_SECONDS - (current - self._last_submission_at)\n'
     '                if remaining > 0:\n'
     '                    return Result("DEFERRED — SMS SPACING", remaining, "s",\n'
     '                                  "Waiting before the next SMS submission")\n\n'
     '            last_error = None'),
    ('            for attempt in range(1, self.retries + 2):\n                try:',
     '            for attempt in range(1, self.retries + 2):\n'
     '                submitted = False\n                try:'),
    ('                        modem.write(message.encode("ascii", errors="replace") + b"\\x1a")',
     '                        self._last_submission_at = self._clock()\n'
     '                        submitted = True\n'
     '                        modem.write(message.encode("ascii", errors="replace") + b"\\x1a")'),
    ('                except Exception as exc:\n                    last_error = exc\n'
     '                    if attempt <= self.retries:',
     '                except Exception as exc:\n                    last_error = exc\n'
     '                    if submitted:\n                        break\n'
     '                    if attempt <= self.retries:'),
)
SERVICE_EDITS = ((
    '                if result.status in ("SENT", "NOT SENT — COOLDOWN", "UNCONFIRMED"):',
    '                if result.status == "DEFERRED — SMS SPACING":\n'
    '                    self.notification_retry_after[issue_key] = (\n'
    '                        time.monotonic() + max(0, float(result.value or 0)))\n'
    '                    break\n'
    '                if result.status in ("SENT", "NOT SENT — COOLDOWN", "UNCONFIRMED"):'
),)


def plan(source, edits, name):
    updated = source
    for old, new in edits:
        if new in updated:
            continue
        if old not in updated:
            raise ValueError(f"{name}: expected reviewed anchor is missing: {old[:65]!r}")
        if updated.count(old) != 1:
            raise ValueError(f"{name}: expected exactly one reviewed anchor: {old[:65]!r}")
        updated = updated.replace(old, new, 1)
    return updated


def atomic_write(path, source):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
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
    root = args.target.resolve()
    files = (
        (root / "app/notifications/__init__.py", NOTIFIER_EDITS),
        (root / "app/service.py", SERVICE_EDITS),
    )
    prepared = []
    try:
        for path, edits in files:
            source = path.read_text(encoding="utf-8")
            updated = plan(source, edits, path.name)
            compile(updated, str(path), "exec")
            prepared.append((path, source, updated))
    except (OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, f"SMS spacing patch not ready: {exc}\n")
    changed = [(path, updated) for path, source, updated in prepared if source != updated]
    if not changed:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changed)} guarded backend files; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changed:
        backup = path.with_name(f"{path.name}.before_sms_spacing_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, updated in changed:
        atomic_write(path, updated)
        print(f"Updated: {path}")
    print("Service was NOT restarted. No SMS was sent by this installer.")


if __name__ == "__main__":
    main()
