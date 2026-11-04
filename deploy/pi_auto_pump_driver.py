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
MANUAL_ARM_RECORD = "MANUAL DOSING ONLY; GPIO24 STOP; 18L\n"
MANUAL_FROM_FLOW_RECORD = "MANUAL DOSING; PRIOR FLOW VERIFIED; GPIO24 STOP; 18L\n"
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def manual_flow_record():
    boot_id = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f-]{36}", boot_id):
        raise RuntimeError("Current boot identity is unavailable")
    return MANUAL_FROM_FLOW_RECORD.rstrip("\n") + f"; BOOT={boot_id}\n"


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


def arm_mode():
    try:
        metadata = ARM_PATH.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o077:
            return None
        record = ARM_PATH.read_text(encoding="utf-8")
        if record == ARM_RECORD:
            return "flow"
        if record == MANUAL_ARM_RECORD:
            return "manual"
        return "manual" if record == manual_flow_record() else None
    except FileNotFoundError:
        return None


def auto_resume_available():
    try:
        metadata = ARM_PATH.stat()
        return (metadata.st_uid == 0 and not metadata.st_mode & 0o077
                and ARM_PATH.read_text(encoding="utf-8") == manual_flow_record())
    except FileNotFoundError:
        return False


def flow_arm_current_boot():
    try:
        return (arm_mode() == "flow" and
                ARM_PATH.stat().st_mtime >= time.time() - time.monotonic() - 5)
    except FileNotFoundError:
        return False


def armed():
    return arm_mode() is not None


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
        "arm_mode": arm_mode(),
        "auto_resume_available": auto_resume_available(),
        "circulation": circulation_state(controller),
        "dosing_pins": {name: controller.pin_state(pin)
                        for name, pin in controller.DOSING_PINS.items()},
        "ml_in_last_24h": totals(data),
        "last_dose_elapsed_seconds": last_elapsed(data, clock),
        "in_progress": data["in_progress"],
        "limits_ml_in_24h": None,
    }


def resume_flow(controller, data):
    if not auto_resume_available():
        raise RuntimeError("A prior supervised flow arm is required")
    if data["in_progress"]:
        raise RuntimeError("Interrupted dose needs manual inspection")
    if circulation_state(controller) != "STOP":
        raise RuntimeError("Circulation must be stopped before flow resumes")
    controller.require_dosing_off()
    try:
        set_circulation(controller, "RUN")
        ARM_PATH.write_text(ARM_RECORD, encoding="utf-8")
        os.chmod(ARM_PATH, 0o600)
    except BaseException:
        set_circulation(controller, "STOP")
        ARM_PATH.write_text(manual_flow_record(), encoding="utf-8")
        os.chmod(ARM_PATH, 0o600)
        raise
    return status(controller, data, time.time())


def dose(controller, data, clock, pump, seconds, *, manual=False):
    if arm_mode() != ("manual" if manual else "flow"):
        raise RuntimeError("Pump controller is not armed for this dosing mode")
    if data["in_progress"]:
        raise RuntimeError("An interrupted dose needs manual inspection")
    required_circulation = "STOP" if manual else "RUN"
    if circulation_state(controller) != required_circulation:
        raise RuntimeError(f"Circulation must be {required_circulation} for this dose")
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
    commands.add_parser("arm-manual")
    commands.add_parser("resume-flow")
    commands.add_parser("disarm")
    circulation = commands.add_parser("circulation")
    circulation.add_argument("state", choices=("run", "stop"))
    dosing = commands.add_parser("dose")
    dosing.add_argument("pump", choices=PUMPS)
    dosing.add_argument("seconds", type=float)
    manual_dosing = commands.add_parser("manual-dose")
    manual_dosing.add_argument("pump", choices=PUMPS)
    manual_dosing.add_argument("seconds", type=float)
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
                ARM_PATH.unlink(missing_ok=True)
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
            elif args.command == "arm-manual":
                if data["in_progress"]:
                    raise RuntimeError("Interrupted dose needs manual inspection")
                prior_flow_verified = flow_arm_current_boot()
                ARM_PATH.unlink(missing_ok=True)
                with contextlib.redirect_stdout(sys.stderr):
                    controller.dosing_off()
                set_circulation(controller, "STOP")
                if input("Circulation is stopped. Watch the outlet, mix the reservoir manually, and check an independent meter after dosing. Type MANUAL to arm: ").strip() != "MANUAL":
                    raise RuntimeError("Manual dosing was not confirmed; controller stays disarmed")
                ARM_PATH.write_text(
                    manual_flow_record() if prior_flow_verified else MANUAL_ARM_RECORD,
                    encoding="utf-8")
                os.chmod(ARM_PATH, 0o600)
                result = status(controller, data, time.time())
            elif args.command == "resume-flow":
                result = resume_flow(controller, data)
            elif args.command == "circulation":
                if arm_mode() != "flow":
                    raise RuntimeError("Circulation requires flow arming")
                if data["in_progress"]:
                    raise RuntimeError("Interrupted dose needs manual inspection")
                controller.require_dosing_off()
                set_circulation(controller, "RUN")
                result = status(controller, data, time.time())
            else:
                result = dose(controller, data, clock, args.pump, args.seconds,
                              manual=args.command == "manual-dose")
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
