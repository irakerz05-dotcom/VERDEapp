#!/usr/bin/env python3
"""Guardedly enable live sensor History in the Pi's modified backend checkout.

Fetch VERDE-Software feature/live-sensor-history first. --check is read-only.
--apply backs up changed files and installs the sensor sample module without
touching GPIO, calibration, SMS, automation, or existing SQLite records.
Restart verde.service separately when it is safe to do so.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_COMMIT = "5fc8f2ed8f62441be24cdd9396bb2fb8e14f202a"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")

SERVICE_IMPORT = "from app.sensor_history import record_sensor_sample\n"
SERVICE_CALL = (
    "            if live_snapshot is not None and not self.database_error:\n"
    "                self.db_call(lambda: record_sensor_sample(self.database.path, live_snapshot))\n"
)
WEB_ROUTE = (
    '            if path == "/api/history":\n'
    '                from app.sensor_history import recent_sensor_samples\n'
    '                from urllib.parse import parse_qs\n'
    '                range_name = parse_qs(urlsplit(self.path).query).get("range", ["Today"])[0]\n'
    '                if range_name not in ("Today", "24 Hours", "7 Days"):\n'
    '                    return self.reply(400, {"error": "Unknown history range"})\n'
    '                with service.lock:\n'
    '                    rows = service.db_call(\n'
    '                        lambda: recent_sensor_samples(service.database.path, range_name)\n'
    '                    )\n'
    '                    return self.reply(200 if rows is not None else 503,\n'
    '                                      {"rows": rows or [], "error": service.database_error})\n'
)


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected exactly one reviewed anchor")
    return source.replace(old, new, 1)


def patch_service(source):
    source = replace_once(
        source, "from app.database import Database\n",
        "from app.database import Database\n" + SERVICE_IMPORT, "service import",
    )
    source = replace_once(
        source,
        '            self.db_call(lambda: self.database.snapshot(self.state))\n'
        '            if self.database_error:',
        '            self.db_call(lambda: self.database.snapshot(self.state))\n'
        + SERVICE_CALL + '            if self.database_error:',
        "service sensor record",
    )
    if source.count(SERVICE_IMPORT) != 1 or source.count(SERVICE_CALL) != 1:
        raise ValueError("service sensor-history patch is incomplete")
    compile(source, "app/service.py", "exec")
    return source


def patch_web(source):
    source = replace_once(
        source,
        '            if path in ("/api/events", "/api/history"):\n',
        WEB_ROUTE + '            if path in ("/api/events", "/api/history"):\n',
        "web history route",
    )
    if source.count(WEB_ROUTE) != 1:
        raise ValueError("web sensor-history patch is incomplete")
    compile(source, "app/web/__init__.py", "exec")
    return source


def module_at_commit(root):
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{BACKEND_COMMIT}:app/sensor_history.py"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    compile(result.stdout, "app/sensor_history.py", "exec")
    return result.stdout


def prepare(root):
    service = root / "app/service.py"
    web = root / "app/web/__init__.py"
    module = root / "app/sensor_history.py"
    if not service.is_file() or not web.is_file():
        raise ValueError("Expected Pi backend files are missing")
    if "live_snapshot = integrated.snapshot()" not in service.read_text(encoding="utf-8"):
        raise ValueError("Integrated sensor cache is not present in app/service.py")
    source_module = module_at_commit(root)
    if module.exists() and module.read_text(encoding="utf-8") != source_module:
        raise ValueError("Existing sensor-history module differs from reviewed source")
    current_service = service.read_text(encoding="utf-8")
    current_web = web.read_text(encoding="utf-8")
    planned = {
        service: patch_service(current_service),
        web: patch_web(current_web),
        module: source_module,
    }
    return planned, sum(
        not path.exists() or path.read_text(encoding="utf-8") != contents
        for path, contents in planned.items()
    )


def atomic_write(path, contents):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
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
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    try:
        planned, edits = prepare(root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Sensor History patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {root}; {edits} guarded file updates; syntax valid; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, contents in planned.items():
        if path.exists() and path.read_text(encoding="utf-8") == contents:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.before_sensor_history_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
        atomic_write(path, contents)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Existing SQLite data was preserved.")


if __name__ == "__main__":
    main()
