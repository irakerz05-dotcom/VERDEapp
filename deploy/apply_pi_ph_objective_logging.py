#!/usr/bin/env python3
"""Guardedly add paper pH recommendations and automatic dose database events."""

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
GATEWAY = "/usr/local/libexec/verde_auto_pumps.py"
OLD_HASHES = {
    "live_mode.py": "d55b9c0eeec17fb6bf03eb12aa280e9a08ad7e0c9678a5a32016cdd9239a223c",
    "pump_runtime.py": "f06f03f5ebcc59143743437222421b518650e9ef785c956bbfc7521e5a5ddecb",
}
SERVICE_OLD = '''                self.state["automation"] = applied
            return copy.deepcopy(self.state)'''
SERVICE_NEW = '''                self.state["automation"] = applied
                if applied.get("dose_event"):
                    self.event("actuator", "Automatic dose completed", applied["dose_event"])
                    if self.database_error:
                        stopped = self.actuators.all_off("Automatic dose event could not be logged")
                        self.selected_mode = SEMI
                        self.state["database"] = {"status": "FAULT / ERROR", "detail": self.database_error}
                        self.state["automation"]["active_mode"] = SEMI
                        self.state["automation"]["selected_mode"] = SEMI
                        self.state["automation"]["actuation_enabled"] = False
                        self.state["automation"]["override"] = True
                        self.state["automation"]["override_reason"] = "Database logging failed after dose"
                        self.state["automation"]["hardware_status"] = stopped.status
                        self.state["automation"]["outputs"] = {
                            name: "OFF / UNVERIFIED" for name in applied["outputs"]}
                        self.state["alerts"].append("Automatic dose event logging failed; pumps stopped")
            return copy.deepcopy(self.state)'''


def digest(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def plan(target, source):
    service_path = target / "app/service.py"
    service = service_path.read_text(encoding="utf-8")
    if SERVICE_NEW in service:
        new_service = service
    elif service.count(SERVICE_OLD) == 1 and "VERDE-PUMP-RUNTIME-v1" in service:
        new_service = service.replace(SERVICE_OLD, SERVICE_NEW, 1)
    else:
        raise ValueError("Installed service does not match the reviewed pump runtime")
    changes = []
    for path, old, new in ((service_path, service, new_service),):
        compile(new, str(path), "exec")
        if old != new:
            changes.append((path, new))
    for name, source_name in (("live_mode.py", "pi_live_automation_mode.py"),
                              ("pump_runtime.py", "pi_pump_runtime.py")):
        path = target / "app/automation" / name
        old = path.read_text(encoding="utf-8")
        new = (source / source_name).read_text(encoding="utf-8")
        compile(new, str(path), "exec")
        if old != new and digest(old) != OLD_HASHES[name]:
            raise ValueError(f"{name}: installed source differs from reviewed version")
        if old != new:
            changes.append((path, new))
    return changes


def require_disarmed():
    result = subprocess.run(("/usr/bin/sudo", "-n", GATEWAY, "status"),
                            capture_output=True, text=True, timeout=15, check=True)
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
        parser.exit(1, f"pH objective logging patch not ready: {exc}\n")
    if not changes:
        print("Already installed; no files changed")
        return
    if args.check:
        print(f"Ready: {len(changes)} guarded backend files; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, _ in changes:
        backup = path.with_name(f"{path.name}.before_ph_objective_logging_{stamp}")
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    for path, source in changes:
        atomic_write(path, source)
        print(f"Updated: {path}")
    print("Service was NOT restarted; no pump command was sent.")


if __name__ == "__main__":
    main()
