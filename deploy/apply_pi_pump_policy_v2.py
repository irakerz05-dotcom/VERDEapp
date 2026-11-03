#!/usr/bin/env python3
"""Guardedly install automatic safety recovery and selectable Semi doses.

Run --check before --apply. Applying requires the updated gateway to be
disarmed with circulation stopped. The script changes no GPIO and does not
restart the service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
GATEWAY = Path("/usr/local/libexec/verde_auto_pumps.py")
OLD_MODULE_HASHES = {
    "live_mode.py": "591a0369eb56a8c46b921820d98c10e724580eb020f46ea97eeceb6206687826",
    "pump_runtime.py": "3349c8b8a36fe9b48ef4175b148c5a328137f36313fa17912ebc7738bf8f41b8",
    "pump_decision.py": "e51350b50b1446a5ff38196386e2ecc87eb847643459b3ae78d3c8671f979558",
}
MARKER = "# VERDE-PUMP-MODE-RESUME-v2: retain the farmer's requested mode."

EARLY_OLD = '''            # VERDE-LIVE-AUTOMATION-MODE-v1; hardware outputs remain disabled.
            automation = evaluate_live(
                self.selected_mode, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error))
            if automation["override"] and self.selected_mode == FULL:
                self.selected_mode = SEMI
                self.event("mode", "Safety override selected Semi-Automation", {
                    "reason": automation["override_reason"],
                })
                automation = evaluate_live(
                    self.selected_mode, live_snapshot, experimental_water, plant, camera,
                    self.config["limits"], bool(self.database_error))'''
EARLY_NEW = '''            # VERDE-LIVE-AUTOMATION-MODE-v1; hardware outputs remain disabled.
            ''' + MARKER + '''
            automation = evaluate_live(
                self.selected_mode, live_snapshot, experimental_water, plant, camera,
                self.config["limits"], bool(self.database_error), pest=pest)'''
RUNTIME_OLD = '''                if applied["active_mode"] == SEMI and self.selected_mode == FULL:
                    self.selected_mode = SEMI
                    self.event("mode", "Pump controller safety override selected Semi-Automation", {
                        "reason": applied.get("override_reason"),
                    })
'''
CONFIRM_OLD = '''    def confirm(self):
        with self.lock:
            if self.selected_mode != SEMI:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            fresh_state = self.tick()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
CONFIRM_NEW = '''    def confirm(self, requested_pump=None):
        with self.lock:
            if self.selected_mode != SEMI:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            fresh_state = self.tick()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot, requested_pump)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
WEB_OLD = '''                if path == "/api/confirm":
                    result = service.confirm()
                    return self.reply(200 if result.get("status") == "DOSED" else 409, result)'''
WEB_NEW = '''                if path == "/api/confirm":
                    requested_pump = body.get("pump")
                    result = service.confirm(requested_pump)
                    return self.reply(200 if result.get("status") == "DOSED" else 409, result)'''
WEB_EVENT_ROUTE = '''            if path in ("/api/events", "/api/history"):
                with service.lock:
                    rows = service.db_call(lambda: service.database.recent("events" if path.endswith("events") else "snapshots"))
                    return self.reply(200 if rows is not None else 503,
                                      {"rows": rows or [], "error": service.database_error})'''
WEB_PUMP_ROUTE = '''            if path == "/api/pump/history":
                try:
                    query = parse_qs(urlsplit(self.path).query, strict_parsing=True)
                    values = query.get("since", [])
                    if len(query) != 1 or len(values) != 1:
                        raise ValueError("One since timestamp is required")
                    since = datetime.fromisoformat(values[0].replace("Z", "+00:00"))
                    if since.tzinfo is None:
                        raise ValueError("since must include a timezone")
                    age = (datetime.now(timezone.utc) - since.astimezone(timezone.utc)).total_seconds()
                    if not -60 <= age <= timedelta(days=8).total_seconds():
                        raise ValueError("since must be within the last eight days")
                except ValueError as exc:
                    return self.reply(400, {"error": str(exc)})
                with service.lock:
                    rows = service.db_call(lambda: service.database.pump_events(values[0]))
                    return self.reply(200 if rows is not None else 503,
                                      {"rows": rows or [], "error": service.database_error})
''' + WEB_EVENT_ROUTE
DB_RECENT = '''    def recent(self, table, limit=30):
        if table not in ("events", "snapshots"):
            raise ValueError("Unknown table")
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))]'''
DB_PUMP_EVENTS = '''    def pump_events(self, since, limit=10080):
        """Return actuator events for the requested history range, newest first."""
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                "SELECT * FROM events WHERE category = 'actuator' "
                "AND julianday(timestamp) >= julianday(?) "
                "ORDER BY id DESC LIMIT ?", (since, limit))]

''' + DB_RECENT


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_exact(source, old, new, label):
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected one reviewed anchor, found {source.count(old)}")
    return source.replace(old, new, 1)


def patch_service(source):
    if MARKER in source:
        if EARLY_OLD in source or RUNTIME_OLD in source or CONFIRM_OLD in source:
            raise ValueError("Mode-resume marker is present with legacy service anchors")
        return source
    source = replace_exact(source, EARLY_OLD, EARLY_NEW, "live mode override")
    source = replace_exact(source, RUNTIME_OLD, "", "pump runtime override")
    source = replace_exact(source,
                           '                self.actuators.all_off("Database error")\n'
                           '                self.selected_mode = SEMI\n',
                           '                self.actuators.all_off("Database error")\n',
                           "database override")
    source = replace_exact(source,
                           '                self.actuators.all_off("Unexpected exception")\n'
                           '                self.selected_mode = SEMI\n',
                           '                self.actuators.all_off("Unexpected exception")\n',
                           "unexpected-exception override")
    source = replace_exact(source,
                           '                        stopped = self.actuators.all_off("Automatic dose event could not be logged")\n'
                           '                        self.selected_mode = SEMI\n',
                           '                        stopped = self.actuators.all_off("Automatic dose event could not be logged")\n',
                           "dose-event override")
    source = replace_exact(source,
                           '                        self.state["automation"]["active_mode"] = SEMI\n'
                           '                        self.state["automation"]["selected_mode"] = SEMI\n',
                           '                        self.state["automation"]["active_mode"] = SEMI\n',
                           "dose-event display mode")
    source = replace_exact(source, CONFIRM_OLD, CONFIRM_NEW, "pump confirmation")
    compile(source, "app/service.py", "exec")
    return source


def patch_web(source):
    if WEB_NEW not in source:
        source = replace_exact(source, WEB_OLD, WEB_NEW, "confirmation route")
    if WEB_PUMP_ROUTE not in source:
        source = replace_exact(source, "import sqlite3\n",
                               "import sqlite3\nfrom datetime import datetime, timedelta, timezone\n",
                               "web datetime import")
        source = replace_exact(source, "from urllib.parse import urlsplit\n",
                               "from urllib.parse import parse_qs, urlsplit\n",
                               "web query import")
        source = replace_exact(source, WEB_EVENT_ROUTE, WEB_PUMP_ROUTE,
                               "pump history route")
    compile(source, "app/web/__init__.py", "exec")
    return source


def patch_database(source):
    if DB_PUMP_EVENTS not in source:
        source = replace_exact(source, DB_RECENT, DB_PUMP_EVENTS,
                               "pump history query")
    compile(source, "app/database/__init__.py", "exec")
    return source


def plan(target, source_directory):
    changes = []
    service_path = target / "app/service.py"
    web_path = target / "app/web/__init__.py"
    database_path = target / "app/database/__init__.py"
    for path, transform in ((service_path, patch_service), (web_path, patch_web),
                            (database_path, patch_database)):
        old = path.read_text(encoding="utf-8")
        new = transform(old)
        if old != new:
            changes.append((path, old, new))
    for target_name, source_name in (("live_mode.py", "pi_live_automation_mode.py"),
                                     ("pump_runtime.py", "pi_pump_runtime.py"),
                                     ("pump_decision.py", "pi_pump_decision.py")):
        path = target / "app/automation" / target_name
        old = path.read_text(encoding="utf-8")
        new = (source_directory / source_name).read_text(encoding="utf-8")
        if old != new and digest(old.encode()) != OLD_MODULE_HASHES[target_name]:
            raise ValueError(f"{target_name}: installed version differs from reviewed Pi source")
        compile(new, str(path), "exec")
        if old != new:
            changes.append((path, old, new))
    return changes


def require_disarmed(source_directory):
    source = source_directory / "pi_auto_pump_driver.py"
    if digest(GATEWAY.read_bytes()) != digest(source.read_bytes()):
        raise ValueError("Install the reviewed updated gateway first")
    result = subprocess.run(("/usr/bin/sudo", "-n", str(GATEWAY), "status"),
                            capture_output=True, text=True, timeout=15, check=True)
    state = json.loads(result.stdout)
    if state.get("armed") is not False or state.get("in_progress") is not False:
        raise ValueError("Gateway must be disarmed with no dose in progress")
    if state.get("circulation") != "STOP":
        raise ValueError("Circulation must be stopped during the update")


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
    parser.add_argument("--target", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        changes = plan(args.target, Path(__file__).parent)
        if args.apply and changes:
            require_disarmed(Path(__file__).parent)
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError,
            json.JSONDecodeError) as exc:
        parser.exit(1, f"Pump policy update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded backend files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path, _, _ in changes:
        backup = path.with_name(f"{path.name}.before_pump_policy_v2_{stamp}")
        shutil.copy2(path, backup)
        backups.append((path, backup))
        print(f"Backup: {backup}")
    try:
        for path, _, new in changes:
            atomic_write(path, new)
            print(f"Updated: {path}")
    except OSError:
        for path, backup in backups:
            shutil.copy2(backup, path)
        raise
    print("Service was NOT restarted. No GPIO or pump command was issued.")


if __name__ == "__main__":
    main()
