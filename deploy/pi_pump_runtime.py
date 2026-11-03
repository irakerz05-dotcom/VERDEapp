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
from app.automation.pump_decision import decide, manual_correction
from app.automation.pump_dose_settings import load as load_dose_settings, save as save_dose_settings, durations as dose_durations, MAX_ML
from app.components import Result


GATEWAY = "/usr/local/libexec/verde_auto_pumps.py"
COMMAND = ("/usr/bin/sudo", "-n", GATEWAY)
CORRECTIVE_RECOMMENDATIONS = ("pH-Up dosing", "pH-Down dosing", "EC nutrient dosing")
CRITICAL_MANUAL_SECONDS = 4.5


def confirmation_available(automation):
    return (automation.get("active_mode") == SEMI and not automation.get("hold_reason")
            and not automation.get("circulation_stop_required", True)
            and any(item in CORRECTIVE_RECOMMENDATIONS
                    for item in automation.get("recommendations", [])))


def snapshot_age_seconds(snapshot):
    try:
        timestamp = datetime.fromisoformat(snapshot["timestamp"])
        if timestamp.tzinfo is None:
            return math.inf
        return (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
    except (KeyError, TypeError, ValueError):
        return math.inf


def manual_wait_reason(gateway, sample_age):
    elapsed = gateway.get("last_dose_elapsed_seconds")
    if elapsed is None:
        return None
    if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        return "Dose timing is unavailable"
    if elapsed < 60:
        return "Wait at least 60 seconds after the previous dose"
    if not math.isfinite(sample_age) or sample_age >= elapsed:
        return "Wait for a new sensor reading after the previous dose"
    return None


def critical_manual_dose(automation, water_value):
    return ("Critical" in str(automation.get("override_reason") or "")
            or water_value == "Critical")


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

    def update_dose_settings(self, volumes):
        return save_dose_settings(volumes)

    def confirm(self, state, live_snapshot, requested_pump=None):
        """Run one farmer-confirmed Semi dose after a fresh service tick."""
        if requested_pump not in ("pump1", "pump2", "pump3"):
            return Result("BLOCKED — SELECT ONE PUMP")
        automation = state.get("automation", {}) if isinstance(state, dict) else {}
        if automation.get("active_mode") != SEMI or automation.get("selected_mode") != SEMI:
            return Result("BLOCKED — SEMI MODE REQUIRED")
        if automation.get("confirmation_available") is not True:
            return Result("BLOCKED — NO CONFIRMABLE RECOMMENDATION")
        if state.get("database", {}).get("status") != "AVAILABLE":
            return Result("BLOCKED — DATABASE UNAVAILABLE")
        if snapshot_age_seconds(live_snapshot) > 65:
            return Result("BLOCKED — STALE SENSOR SAMPLE")
        try:
            gateway = self.command("status")
            if gateway.get("armed") is not True or gateway.get("in_progress"):
                return Result("BLOCKED — PUMP GATEWAY DISARMED OR BUSY")
            sensors = live_snapshot.get("sensors", {}) if isinstance(live_snapshot, dict) else {}
            manual_stop = automation.get("circulation_stop_required") is True
            if manual_stop or gateway.get("arm_mode") == "manual":
                if gateway.get("arm_mode") != "manual" or gateway.get("circulation") != "STOP":
                    return Result("BLOCKED — MANUAL DOSING ARM REQUIRED")
                wait_reason = manual_wait_reason(gateway, snapshot_age_seconds(live_snapshot))
                if wait_reason:
                    return Result("BLOCKED — WAIT FOR NEXT CHECK", detail=wait_reason)
                critical = critical_manual_dose(
                    automation, state.get("water_quality_experimental", {}).get("value"))
                durations = ({pump: CRITICAL_MANUAL_SECONDS for pump in ("pump1", "pump2", "pump3")}
                             if critical else dose_durations(load_dose_settings()))
                proposal = manual_correction(
                    sensors, requested_pump, gateway.get("last_dose_elapsed_seconds"),
                    durations)
                if proposal is None:
                    return Result("BLOCKED — NO FRESH MATCHING READING OR MIXING WAIT")
                action, pump, seconds, volume = proposal
                result = self.command("manual-dose", pump, f"{seconds:.8f}")
                return Result("DOSED", value={**result, "mode": SEMI,
                                              "pump": pump, "action": action,
                                              "requested_seconds": seconds,
                                              "estimated_ml": volume},
                              detail=f"Farmer confirmed manual {action}; mix and check independently")
            if automation.get("hold_reason"):
                return Result("BLOCKED — SENSOR OR VISION HOLD",
                              detail=automation.get("hold_reason") or "")
            if gateway.get("arm_mode") != "flow":
                return Result("BLOCKED — FLOW ARM REQUIRED")
            water = state.get("water_quality_experimental", {})
            plant = state.get("plant_condition", {})
            camera = state.get("camera", {})
            if not all(isinstance(item, dict) for item in (water, plant, camera)):
                return Result("BLOCKED — INCOMPLETE MONITORING STATE")
            proposal = decide(
                selected_mode=SEMI, override_latched=False, request_full=False,
                sensors=sensors, snapshot_age_seconds=snapshot_age_seconds(live_snapshot),
                water_class=water.get("value"),
                camera_fault=camera.get("status") == "FAULT / ERROR",
                vision_fault=plant.get("status") == "FAULT / ERROR",
                last_dose_elapsed_seconds=gateway.get("last_dose_elapsed_seconds"),
                calibrated_dose_seconds=dose_durations(load_dose_settings()),
                circulation_flow_gpio_level="HIGH",
                dosed_ml_by_pump=gateway.get("ml_in_last_24h"),
                farmer_confirmed=True,
                requested_pump=requested_pump,
            )
            if proposal.pump is None:
                return Result("BLOCKED — NO ELIGIBLE DOSE",
                              detail=proposal.reason or "Selected pump is not currently recommended, or the mixing wait is active")
            if gateway.get("circulation") != "RUN":
                self.command("circulation", "run")
            result = self.command("dose", proposal.pump, f"{proposal.dose_seconds:.8f}")
            return Result("DOSED", value={**result, "mode": SEMI,
                                          "pump": proposal.pump,
                                          "action": proposal.dose_action,
                                          "requested_seconds": proposal.dose_seconds,
                                          "estimated_ml": proposal.dose_ml},
                          detail=f"Farmer confirmed {proposal.dose_action}")
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            stopped = self.all_off(str(exc))
            return Result("FAULT / ERROR", detail=f"Pump command failed: {exc}; {stopped.status}")

    def apply(self, automation, live_snapshot, water, plant, camera):
        """Apply one cycle after database writes succeeded; return display state."""
        output = copy.deepcopy(automation)
        try:
            volumes = load_dose_settings()
            output["dose_settings"] = {"volumes_ml": volumes, "max_pulse_ml": MAX_ML,
                                       "flow_ml_per_second": 0.82}
            gateway = self.command("status")
            if gateway.get("in_progress"):
                raise RuntimeError("An interrupted dose needs manual inspection")
            if gateway.get("armed") is not True:
                output["active_mode"] = SEMI
                output["override"] = True
                output["override_reason"] = "Pump controller is disarmed"
                output["actuation_enabled"] = False
                output["confirmation_available"] = False
                output["hardware_status"] = "DISARMED — CIRCULATION CONFIGURATION PENDING"
                output["outputs"] = {name: "OFF / DISARMED" for name in OUTPUTS}
                return output
            if gateway.get("arm_mode") == "manual":
                self.command("safe-off")
                output["active_mode"] = SEMI
                output["actuation_enabled"] = False
                output["manual_wait_reason"] = manual_wait_reason(
                    gateway, snapshot_age_seconds(live_snapshot))
                output["critical_manual_dose"] = critical_manual_dose(
                    output, getattr(water, "value", None))
                output["confirmation_available"] = output.get("selected_mode") == SEMI and any(
                    item in CORRECTIVE_RECOMMENDATIONS
                    for item in output.get("recommendations", [])) and not output["manual_wait_reason"]
                output["hardware_status"] = "MANUAL DOSING ARMED — CIRCULATION STOPPED"
                output["outputs"] = {name: "OFF" for name in OUTPUTS}
                return output
            if automation.get("circulation_stop_required", True):
                self.command("safe-off")
                output["actuation_enabled"] = False
                output["confirmation_available"] = False
                output["hardware_status"] = "SAFETY OVERRIDE — PUMPS STOPPED"
                output["outputs"] = {name: "OFF" for name in OUTPUTS}
                return output
            if automation.get("override"):
                if gateway.get("circulation") != "RUN":
                    self.command("circulation", "run")
                output["actuation_enabled"] = False
                output["confirmation_available"] = confirmation_available(output)
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
                calibrated_dose_seconds=dose_durations(volumes),
                circulation_flow_gpio_level="HIGH",
                dosed_ml_by_pump=gateway.get("ml_in_last_24h"),
                requested_pump=None,
            )
            if decision.override_latched:
                raise RuntimeError(decision.reason or "Pump safety override")
            if gateway.get("circulation") != "RUN":
                self.command("circulation", "run")
            output["actuation_enabled"] = True
            output["confirmation_available"] = confirmation_available(output)
            output["hardware_status"] = "CONNECTED — GUARDED PUMP GATEWAY"
            output["outputs"] = {name: "OFF" for name in OUTPUTS}
            output["outputs"]["circulation_pump"] = "RUN (GPIO24 HIGH)"
            if (output["active_mode"] == FULL and not output.get("hold_reason")
                    and decision.pump is not None):
                result = self.command("dose", decision.pump, f"{decision.dose_seconds:.8f}")
                output["outputs"][decision.dose_action] = (
                    f"DOSED {decision.dose_ml:.2f} mL / {decision.dose_seconds:.2f} s")
                output["dose_event"] = {
                    "mode": FULL, "pump": decision.pump, "action": decision.dose_action,
                    "requested_seconds": decision.dose_seconds,
                    "estimated_ml": result.get("estimated_ml", decision.dose_ml),
                    "sensor_timestamp": live_snapshot.get("timestamp") if isinstance(live_snapshot, dict) else None,
                }
            return output
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            stopped = self.all_off(str(exc))
            output["active_mode"] = SEMI
            output["override"] = True
            output["override_reason"] = f"Pump controller fault: {exc}"
            output["actuation_enabled"] = False
            output["confirmation_available"] = False
            output["hardware_status"] = stopped.status
            output["outputs"] = {name: "OFF / UNVERIFIED" for name in OUTPUTS}
            return output
