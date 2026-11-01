#!/usr/bin/python3
"""Protected VERDE pump gateway built around the existing manual controller.

Install this and a copy of verde_manual_pumps.py as root-owned files. The
service may invoke only status, safe-off, circulation, and dose through sudo.
The gateway starts disarmed and never arms itself.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path


CONTROLLER = Path("/usr/local/libexec/verde_manual_pumps.py")
STATE_PATH = Path("/var/lib/verde/pump_dose_state.json")
ARM_PATH = Path("/etc/verde/pumps-armed")
FLOW_GPIO_LEVEL = "dh"   # Physically observed twice: HIGH = flowing.
STOP_GPIO_LEVEL = "dl"   # Physically observed twice: LOW = stopped.
FLOW_ML_PER_SECOND = 0.82
MIX_SECONDS = 60.0
WINDOW_SECONDS = 24 * 60 * 60
MAX_AUTO_SECONDS = 4.5
PUMPS = ("pump1", "pump2", "pump3")
ARM_RECORD = "GPIO24 HIGH=FLOW LOW=STOP; 18L\n"


def protected_controller():
    metadata = CONTROLLER.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise RuntimeError("Manual controller copy is not root-owned and protected")
    spec = importlib.util.spec_from_file_location("verde_protected_manual_pumps", CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.DOSING_PINS != {"pump1": 27, "pump2": 22, "pump3": 23}:
        raise RuntimeError("Manual pump GPIO mapping changed")
    if module.CIRCULATION_PIN != 24 or module.MAX_SECONDS != 5.0:
        raise RuntimeError("Manual controller safety limit changed")
    return module


def armed():
    try:
        metadata = ARM_PATH.stat()
        return (metadata.st_uid == 0 and not metadata.st_mode & 0o077
                and ARM_PATH.read_text(encoding="utf-8") == ARM_RECORD)
    except FileNotFoundError:
        return False


def atomic_json(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_state(clock):
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {"version": 1, "events": [], "in_progress": False}
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("events"), list)
            or not isinstance(data.get("in_progress"), bool)):
        raise RuntimeError("Pump state is invalid; dosing blocked")
    events = []
    for event in data["events"]:
        if (not isinstance(event, dict) or event.get("pump") not in PUMPS
                or not isinstance(event.get("at"), (int, float))
                or not math.isfinite(event["at"])
                or not isinstance(event.get("ml"), (int, float))
                or not math.isfinite(event["ml"]) or event["ml"] <= 0):
            raise RuntimeError("Pump event ledger is invalid; dosing blocked")
        if clock - event["at"] < WINDOW_SECONDS:
            events.append(event)
    data["events"] = events
    return data


def totals(data):
    return {pump: sum(event["ml"] for event in data["events"]
                      if event["pump"] == pump) for pump in PUMPS}


def last_elapsed(data, clock):
    return (None if not data["events"] else
            max(0.0, clock - max(event["at"] for event in data["events"])))


def circulation_state(controller):
    state = controller.pin_state(24)
    if re.match(r"^24:\s+op\s+dh\b.*\|\s+hi\b", state):
        return "RUN"
    if re.match(r"^24:\s+op\s+dl\b.*\|\s+lo\b", state):
        return "STOP"
    return "UNVERIFIED"


def set_circulation(controller, state):
    controller.set_level(24, FLOW_GPIO_LEVEL if state == "RUN" else STOP_GPIO_LEVEL)
    if circulation_state(controller) != state:
        raise RuntimeError(f"GPIO24 did not confirm circulation {state}")


def status(controller, data, clock):
    return {
        "armed": armed(),
        "circulation": circulation_state(controller),
        "dosing_pins": {name: controller.pin_state(pin)
                        for name, pin in controller.DOSING_PINS.items()},
        "ml_in_last_24h": totals(data),
        "last_dose_elapsed_seconds": last_elapsed(data, clock),
        "in_progress": data["in_progress"],
        "limits_ml_in_24h": None,
    }


def dose(controller, data, clock, pump, seconds):
    if not armed():
        raise RuntimeError("Pump controller is disarmed")
    if data["in_progress"]:
        raise RuntimeError("An interrupted dose needs manual inspection")
    if circulation_state(controller) != "RUN":
        raise RuntimeError("Circulation is not confirmed running")
    if not isinstance(seconds, float) or not math.isfinite(seconds) or not 0 < seconds <= MAX_AUTO_SECONDS:
        raise RuntimeError(f"Dose duration must be greater than zero and at most {MAX_AUTO_SECONDS} seconds")
    elapsed = last_elapsed(data, clock)
    if elapsed is not None and elapsed < MIX_SECONDS:
        raise RuntimeError("The 60-second mixing wait has not elapsed")
    volume = FLOW_ML_PER_SECOND * seconds
    controller.require_dosing_off()
    data["events"].append({"pump": pump, "at": clock, "ml": volume})
    data["in_progress"] = True
    atomic_json(STATE_PATH, data)  # Reserve the full amount before energizing.
    try:
        with contextlib.redirect_stdout(sys.stderr):
            controller.dose(pump, seconds)
        data["events"][-1]["at"] = time.time()  # Wait 60 s from dose completion.
        data["in_progress"] = False
        atomic_json(STATE_PATH, data)
    except BaseException:
        with contextlib.redirect_stdout(sys.stderr):
            controller.dosing_off()
        raise
    return {"pump": pump, "seconds": seconds, "estimated_ml": volume}


def main():
    import fcntl

    if os.geteuid() != 0:
        raise RuntimeError("The protected pump gateway must run as root")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("safe-off")
    commands.add_parser("arm")
    commands.add_parser("disarm")
    circulation = commands.add_parser("circulation")
    circulation.add_argument("state", choices=("run", "stop"))
    dosing = commands.add_parser("dose")
    dosing.add_argument("pump", choices=PUMPS)
    dosing.add_argument("seconds", type=float)
    args = parser.parse_args()
    controller = protected_controller()
    lock = controller.lock_control()
    try:
        if args.command in ("safe-off", "disarm"):
            if args.command == "disarm":
                ARM_PATH.unlink(missing_ok=True)
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    controller.dosing_off()
            finally:
                set_circulation(controller, "STOP")
            result = {"armed": armed(), "circulation": "STOP", "dosing": "OFF"}
        elif args.command == "circulation" and args.state == "stop":
            set_circulation(controller, "STOP")
            result = {"circulation": "STOP"}
        else:
            clock = time.time()
            data = load_state(clock)
            if args.command == "status":
                result = status(controller, data, clock)
            elif args.command == "arm":
                if data["in_progress"]:
                    raise RuntimeError("Interrupted dose needs manual inspection")
                with contextlib.redirect_stdout(sys.stderr):
                    controller.dosing_off()
                set_circulation(controller, "RUN")
                try:
                    if input("Is water physically flowing? Type FLOWING to arm: ").strip() != "FLOWING":
                        raise RuntimeError("Physical flow not confirmed; controller stays disarmed")
                    ARM_PATH.write_text(ARM_RECORD, encoding="utf-8")
                    os.chmod(ARM_PATH, 0o600)
                except BaseException:
                    set_circulation(controller, "STOP")
                    raise
                result = status(controller, data, time.time())
            elif args.command == "circulation":
                if not armed():
                    raise RuntimeError("Pump controller is disarmed")
                if data["in_progress"]:
                    raise RuntimeError("Interrupted dose needs manual inspection")
                controller.require_dosing_off()
                set_circulation(controller, "RUN")
                result = status(controller, data, time.time())
            else:
                result = dose(controller, data, clock, args.pump, args.seconds)
        print(json.dumps(result, separators=(",", ":")))
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Pump gateway blocked: {exc}", file=sys.stderr)
        raise SystemExit(1)
