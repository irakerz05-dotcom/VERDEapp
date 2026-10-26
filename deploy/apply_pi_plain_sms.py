#!/usr/bin/env python3
"""Install farmer-facing SMS wording in the Pi's dirty backend checkout.

Fetch VERDE-Software feature/plain-language-sms first. Run --check, then
--apply. This leaves incident diagnostics, notification policy, recipient,
hardware, and service state unchanged. A restart is required separately.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_COMMIT = "da77bcb"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one SMS patch anchor: {old[:70]!r}")
    return source.replace(old, new, 1)


def source_module(root):
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{BACKEND_COMMIT}:app/notifications/sms_text.py"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    compile(result.stdout, "app/notifications/sms_text.py", "exec")
    return result.stdout


def patched_service(original):
    result = replace_once(
        original,
        "from app.notifications import default_gsm\n",
        "from app.notifications import default_gsm\n"
        "from app.notifications.sms_text import format_sms_alert\n",
    )
    result = replace_once(
        result,
        '                result = guarded(lambda issue=issue: self.gsm.send("VERDE alert: " + issue["message"]))',
        '                result = guarded(lambda issue_key=issue_key, issue=issue: self.gsm.send(\n'
        '                    format_sms_alert(issue_key, issue)))',
    )
    compile(result, "app/service.py", "exec")
    return result


def atomic_write(path, content):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                 prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        if path.exists():
            os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    service = root / "app/service.py"
    module = root / "app/notifications/sms_text.py"
    if not service.is_file() or module.exists():
        raise SystemExit("Expected existing service module and no installed SMS formatter")
    module_text = source_module(root)
    service_text = patched_service(service.read_text(encoding="utf-8"))
    if args.check:
        print(f"Ready: {root}; two guarded edits and formatter syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = service.with_name(f"service.py.before_plain_sms_{stamp}")
    shutil.copy2(service, backup)
    atomic_write(module, module_text)
    atomic_write(service, service_text)
    print(f"Updated {service} and {module}")
    print(f"Backup: {backup}")
    print("Service was NOT restarted; no SMS was sent.")


if __name__ == "__main__":
    main()
