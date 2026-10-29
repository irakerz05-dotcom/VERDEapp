#!/usr/bin/env python3
"""Guardedly add dashboard pump dose targets to the installed Pi service."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path("/home/verde/VERDE-Sensor-Integration")
GATEWAY = "/usr/local/libexec/verde_auto_pumps.py"
EXPECTED_RUNTIME = "cbe7cbccc6fc55adbfaf97fca5b9c337c8195cd9542bbe8deb90708cc3458081"
SERVICE_ANCHOR = '''    def confirm(self):
        with self.lock:
            if self.selected_mode != SEMI:
                return Result("BLOCKED — SEMI MODE REQUIRED").as_dict()
            fresh_state = self.tick()
            live_snapshot = self.sensor_snapshot()
            result = self.actuators.confirm(fresh_state, live_snapshot)
            self.event("actuator", result.status, result.as_dict())
            return result.as_dict()'''
SERVICE_NEW = SERVICE_ANCHOR + '''

    def set_pump_dose_settings(self, volumes):
        with self.lock:
            if self.selected_mode != SEMI or not isinstance(self.actuators, PumpRuntime):
                raise ValueError("Select Semi-Automation before changing pump volumes")
            saved = self.actuators.update_dose_settings(volumes)
            self.event("pump_dose_settings", "Pump dose volumes updated", {"volumes_ml": saved})
            return {"volumes_ml": saved}'''
WEB_ANCHOR = '''                if path == "/api/confirm":
                    result = service.confirm()
                    return self.reply(200 if result.get("status") == "DOSED" else 409, result)'''
WEB_NEW = '''                if path == "/api/pump/dose-settings":
                    try:
                        if set(body) != {"volumes_ml"}:
                            raise ValueError("Only volumes_ml is accepted")
                        return self.reply(200, service.set_pump_dose_settings(body["volumes_ml"]))
                    except ValueError as exc:
                        return self.reply(400, {"error": str(exc)})
                    except OSError:
                        return self.reply(503, {"error": "Could not save pump volumes on the Pi"})
''' + WEB_ANCHOR


def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()


def replace_once(source, old, new, label):
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: installed source differs from the reviewed version")
    return source.replace(old, new, 1)


def plan(target, source):
    service_path = target / "app/service.py"
    web_path = target / "app/web/__init__.py"
    runtime_path = target / "app/automation/pump_runtime.py"
    settings_path = target / "app/automation/pump_dose_settings.py"
    service = service_path.read_text(encoding="utf-8")
    web = web_path.read_text(encoding="utf-8")
    runtime = runtime_path.read_text(encoding="utf-8")
    if "VERDE-PUMP-RUNTIME-v1" not in service:
        raise ValueError("Protected pump runtime is not installed")
    new_runtime = (source / "pi_pump_runtime.py").read_text(encoding="utf-8")
    new_settings = (source / "pi_pump_dose_settings.py").read_text(encoding="utf-8")
    if runtime != new_runtime and digest(runtime) != EXPECTED_RUNTIME:
        raise ValueError("Pump runtime differs from the reviewed 18 L version")
    if settings_path.exists() and settings_path.read_text(encoding="utf-8") != new_settings:
        raise ValueError("Pump dose settings module already exists with different content")
    replacements = (
        (service_path, replace_once(service, SERVICE_ANCHOR, SERVICE_NEW, "service")),
        (web_path, replace_once(web, WEB_ANCHOR, WEB_NEW, "web")),
        (runtime_path, new_runtime),
        (settings_path, new_settings),
    )
    for path, replacement in replacements:
        compile(replacement, str(path), "exec")
    return [(path, replacement) for path, replacement in replacements
            if not path.exists() or path.read_text(encoding="utf-8") != replacement]


def require_disarmed():
    result = subprocess.run(("/usr/bin/sudo", "-n", GATEWAY, "status"),
                            capture_output=True, text=True, timeout=15, check=True)
    import json
    state = json.loads(result.stdout)
    if state.get("armed") is not False or state.get("in_progress") is not False:
        raise ValueError("Disarm the protected gateway before updating backend files")
    if state.get("circulation") != "STOP":
        raise ValueError("Circulation must be stopped for the update")


def atomic_write(path, source):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(source)
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
    parser.add_argument("--target", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        changes = plan(args.target, Path(__file__).parent)
        if args.apply and changes:
            require_disarmed()
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Pump dose settings update not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded backend files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        if path.exists():
            backup = path.with_name(f"{path.name}.before_pump_dose_settings_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
    for path, source in changes:
        atomic_write(path, source)
        print(f"Updated: {path}")
    print("Service was NOT restarted. Gateway remains disarmed; no dose was sent.")


if __name__ == "__main__":
    main()
