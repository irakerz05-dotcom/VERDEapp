"""Guarded live pump control for the installed Pi service.

The root-owned gateway enforces hardware limits and starts disarmed. This
module checks live readings again before calling it, and never owns GPIO.
"""

from __future__ import annotations

import copy
import json
import math
import subprocess
from datetime import datetime, timezone

from app.automation import FULL, SEMI, OUTPUTS
from app.automation.pump_decision import decide
from app.components import Result


GATEWAY = "/usr/local/libexec/verde_auto_pumps.py"
COMMAND = ("/usr/bin/sudo", "-n", GATEWAY)
DOSE_SECONDS = {"pump1": 5.0, "pump2": 5.0, "pump3": 5.0}


def snapshot_age_seconds(snapshot):
    try:
        timestamp = datetime.fromisoformat(snapshot["timestamp"])
        if timestamp.tzinfo is None:
            return math.inf
        return (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    except (KeyError, TypeError, ValueError):
        return math.inf


class PumpRuntime:
    def __init__(self):
        self.latest = None

    @staticmethod
    def command(*arguments):
        result = subprocess.run(
            (*COMMAND, *map(str, arguments)), capture_output=True, text=True,
            check=False, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or
                                f"Pump gateway exit {result.returncode}").strip())
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Pump gateway did not return JSON") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Pump gateway returned an invalid response")
        return payload

    def all_off(self, reason):
        try:
            self.command("safe-off")
            return Result("SAFE/OFF", detail=reason)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return Result("FAULT / ERROR", detail=f"Could not stop pumps: {exc}")

    def request(self, action):
        return Result("BLOCKED — CONFIRMATION NOT YET INTEGRATED", detail=action)

    def apply(self, automation, live_snapshot, water, plant, camera):
        """Apply one cycle after database writes succeeded; return display state."""
        output = copy.deepcopy(automation)
        try:
            gateway = self.command("status")
            if gateway.get("in_progress"):
                raise RuntimeError("An interrupted dose needs manual inspection")
            if gateway.get("armed") is not True:
                output["selected_mode"] = SEMI
                output["active_mode"] = SEMI
                output["override"] = True
                output["override_reason"] = "Pump controller is disarmed"
                output["actuation_enabled"] = False
                output["hardware_status"] = "DISARMED — CIRCULATION CONFIGURATION PENDING"
                output["outputs"] = {name: "OFF / DISARMED" for name in OUTPUTS}
                return output
            if automation.get("circulation_stop_required", True):
                self.command("safe-off")
                output["actuation_enabled"] = False
                output["hardware_status"] = "FAULT OVERRIDE — PUMPS STOPPED"
                output["outputs"] = {name: "OFF" for name in OUTPUTS}
                return output
            if automation.get("override"):
                if gateway.get("circulation") != "RUN":
                    self.command("circulation", "run")
                output["actuation_enabled"] = False
                output["hardware_status"] = "CRITICAL — SEMI-AUTOMATION; DOSING HELD"
                output["outputs"] = {name: "OFF" for name in OUTPUTS}
                output["outputs"]["circulation_pump"] = "RUN (GPIO24 HIGH)"
                return output
            sensors = live_snapshot.get("sensors", {}) if isinstance(live_snapshot, dict) else {}
            decision = decide(
                selected_mode=output["active_mode"], override_latched=False,
                request_full=False, sensors=sensors,
                snapshot_age_seconds=snapshot_age_seconds(live_snapshot),
                water_class=getattr(water, "value", None),
                camera_fault=(isinstance(camera, dict) and camera.get("status") == "FAULT / ERROR"),
                vision_fault=(getattr(plant, "status", None) == "FAULT / ERROR"),
                last_dose_elapsed_seconds=gateway.get("last_dose_elapsed_seconds"),
                calibrated_dose_seconds=DOSE_SECONDS,
                circulation_flow_gpio_level="HIGH",
                dosed_ml_by_pump=gateway.get("ml_in_last_24h"),
            )
            if decision.override_latched:
                raise RuntimeError(decision.reason or "Pump safety override")
            if gateway.get("circulation") != "RUN":
                self.command("circulation", "run")
            output["actuation_enabled"] = True
            output["hardware_status"] = "CONNECTED — GUARDED PUMP GATEWAY"
            output["outputs"] = {name: "OFF" for name in OUTPUTS}
            output["outputs"]["circulation_pump"] = "RUN (GPIO24 HIGH)"
            if (output["active_mode"] == FULL and not output.get("hold_reason")
                    and decision.pump is not None):
                self.command("dose", decision.pump, f"{decision.dose_seconds:.8f}")
                output["outputs"][decision.dose_action] = (
                    f"DOSED {decision.dose_ml:.2f} mL / {decision.dose_seconds:.2f} s")
            return output
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            stopped = self.all_off(str(exc))
            output["selected_mode"] = SEMI
            output["active_mode"] = SEMI
            output["override"] = True
            output["override_reason"] = f"Pump controller fault: {exc}"
            output["actuation_enabled"] = False
            output["hardware_status"] = stopped.status
            output["outputs"] = {name: "OFF / UNVERIFIED" for name in OUTPUTS}
            return output
