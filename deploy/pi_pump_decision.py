"""Pure VERDE pump decisions. This module never opens GPIO or starts a pump.

The live service must enforce these decisions again immediately before actuation.
Physical output remains unavailable until a privileged controller, dose calibration,
and circulation polarity have been verified on the Pi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


FULL = "Full Automation Mode"
SEMI = "Semi-Automation Mode"
MIX_SECONDS = 60.0
MAX_SAMPLE_AGE_SECONDS = 65.0
ASSUMED_FLOW_ML_PER_SECOND = 0.82
MAX_RUN_SECONDS = 4.5  # 3.69 mL at 0.82 mL/s, scaled from the 20 L proposal.
DOSE_VOLUME_ML = ASSUMED_FLOW_ML_PER_SECOND * MAX_RUN_SECONDS
PUMP_BY_ACTION = {
    "nutrient_dosing": "pump1",  # GPIO27
    "ph_up": "pump2",           # GPIO22
    "ph_down": "pump3",         # GPIO23
}


@dataclass(frozen=True)
class Decision:
    active_mode: str
    override_latched: bool
    reason: str | None
    circulation: str
    circulation_gpio_level: str | None
    dose_action: str | None
    pump: str | None
    dose_seconds: float | None
    dose_ml: float | None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sensor_ready(sensor, value_field):
    if not isinstance(sensor, dict) or not _finite(sensor.get(value_field)):
        return False
    status = str(sensor.get("status") or "")
    if sensor.get("retained") or sensor.get("stale"):
        return False
    if sensor.get("valid") is False:
        return False
    return status.startswith("OK") or status == "CALIBRATED"


def _sensor_fault(sensor):
    if not isinstance(sensor, dict):
        return True
    status = str(sensor.get("status") or "").upper()
    failures = sensor.get("consecutive_failures")
    return (status.startswith(("ERROR", "FAULT", "UNAVAILABLE"))
            or (sensor.get("valid") is False and isinstance(failures, int)
                and not isinstance(failures, bool) and failures >= 2))


def manual_correction(sensors, requested_pump, last_dose_elapsed_seconds,
                      calibrated_dose_seconds):
    """One farmer-selected correction from a fresh matching sensor; no GPIO."""
    if requested_pump not in PUMP_BY_ACTION.values() or not isinstance(sensors, dict):
        return None
    if requested_pump == "pump1":
        sensor = sensors.get("ec")
        action = "nutrient_dosing"
        eligible = (_sensor_ready(sensor, "value_mScm")
                    and sensor["value_mScm"] < 1.2)
    else:
        sensor = sensors.get("ph")
        action = "ph_up" if requested_pump == "pump2" else "ph_down"
        eligible = (_sensor_ready(sensor, "value")
                    and (sensor["value"] < 5.5 if requested_pump == "pump2"
                         else sensor["value"] > 6.5))
    if not eligible:
        return None
    mixed = (last_dose_elapsed_seconds is None
             or (_finite(last_dose_elapsed_seconds)
                 and last_dose_elapsed_seconds >= MIX_SECONDS))
    seconds = (calibrated_dose_seconds.get(requested_pump)
               if isinstance(calibrated_dose_seconds, dict) else None)
    if not mixed or not _finite(seconds) or not 0 < seconds <= MAX_RUN_SECONDS:
        return None
    return action, requested_pump, seconds, seconds * ASSUMED_FLOW_ML_PER_SECOND


def decide(*, selected_mode, override_latched, request_full, sensors,
           snapshot_age_seconds, water_class, camera_fault, vision_fault,
           last_dose_elapsed_seconds, calibrated_dose_seconds,
           circulation_flow_gpio_level, dosed_ml_by_pump=None,
           farmer_confirmed=False, requested_pump=None, last_dose_pump=None):
    """Return a proposed action; no state or hardware is changed.

    The farmer's selected mode is retained across a safety override. A prior
    override clears only after a fresh, healthy water evaluation.
    """
    if selected_mode not in (FULL, SEMI):
        raise ValueError("Unknown operating mode")
    if circulation_flow_gpio_level not in (None, "LOW", "HIGH"):
        raise ValueError("Circulation flow GPIO level must be LOW, HIGH, or unverified")
    if not isinstance(sensors, dict):
        sensors = {}
    required = {
        "ph": ("value",),
        "ec": ("value_mScm",),
        "water_temperature": ("value_C",),
        "turbidity": ("value_ntu",),
    }
    unready = [name for name, (field,) in required.items()
               if not _sensor_ready(sensors.get(name), field)]
    faulty = [name for name in required if _sensor_fault(sensors.get(name))]
    stale = (not _finite(snapshot_age_seconds) or snapshot_age_seconds < 0
             or snapshot_age_seconds > MAX_SAMPLE_AGE_SECONDS)
    critical = [name for name in required
                if str((sensors.get(name) or {}).get("classification") or "").upper() == "CRITICAL"]
    ph_value = (sensors.get("ph") or {}).get("value")
    ec_value = (sensors.get("ec") or {}).get("value_mScm")
    if _finite(ph_value) and (ph_value < 4.5 or ph_value > 8.0) and "ph" not in critical:
        critical.append("ph")
    if _finite(ec_value) and (ec_value < 0.5 or ec_value > 4.0) and "ec" not in critical:
        critical.append("ec")
    if water_class == "Critical":
        critical.append("water quality")
    fault_reason = None
    if stale:
        fault_reason = "Sensor acquisition is stale"
    elif faulty:
        fault_reason = "Faulty Sensor: " + ", ".join(faulty)
    elif camera_fault or vision_fault:
        fault_reason = "Faulty Vision"
    elif critical:
        fault_reason = "Critical condition: " + ", ".join(critical)

    healthy = (not fault_reason and not unready
               and water_class in ("Optimal", "Suboptimal"))
    latched = bool(fault_reason or (override_latched and not healthy))
    active_mode = SEMI if latched else selected_mode
    reason = fault_reason or ("Waiting for fresh sensor readings: " + ", ".join(unready)
                              if unready else None)
    # The NC contact may reverse the load behavior relative to a NO contact.
    # GPIO24 is not driven until its actual flow level is physically verified.
    # Critical water conditions are also a circulation stop.  The service
    # switches to Semi-Automation for the same safety override, and only a
    # fresh, normal evaluation may return to the farmer's requested mode.
    stop_for_fault = bool(stale or faulty or camera_fault or vision_fault or critical)
    circulation = ("BLOCKED: polarity unverified" if circulation_flow_gpio_level is None
                   else "STOP" if stop_for_fault else "RUN")
    circulation_gpio_level = (None if circulation_flow_gpio_level is None else
                              circulation_flow_gpio_level if circulation == "RUN" else
                              "HIGH" if circulation_flow_gpio_level == "LOW" else "LOW")

    action = None
    pump = None
    seconds = None
    dose_ml = None
    automatic = (active_mode == FULL and reason is None
                 and water_class in ("Optimal", "Suboptimal"))
    confirmed = (farmer_confirmed and active_mode == SEMI and not stale
                 and not faulty and not unready and not camera_fault and not vision_fault
                 and not critical and water_class in ("Optimal", "Suboptimal"))
    if automatic or confirmed:
        ph = sensors["ph"]["value"]
        ec = sensors["ec"]["value_mScm"]
        eligible_actions = []
        if ph < 5.5:
            eligible_actions.append("ph_up")
        elif ph > 6.5:
            eligible_actions.append("ph_down")
        if ec < 1.2:
            eligible_actions.append("nutrient_dosing")
        # High EC has no deterministic correction pump.
        # Give low EC the next pulse after a pH dose so repeated pH readings
        # cannot starve Pump 1. The gateway still permits only one pump at once.
        if (requested_pump is None and last_dose_pump in ("pump2", "pump3")
                and "nutrient_dosing" in eligible_actions):
            eligible_actions.remove("nutrient_dosing")
            eligible_actions.insert(0, "nutrient_dosing")
        action = next((candidate for candidate in eligible_actions
                       if requested_pump is None
                       or PUMP_BY_ACTION[candidate] == requested_pump), None)
        if action:
            pump = PUMP_BY_ACTION[action]
            duration = calibrated_dose_seconds.get(pump) if isinstance(calibrated_dose_seconds, dict) else None
            mixed = (last_dose_elapsed_seconds is None
                     or (_finite(last_dose_elapsed_seconds)
                         and last_dose_elapsed_seconds >= MIX_SECONDS
                         and snapshot_age_seconds < last_dose_elapsed_seconds))
            if (not mixed or not _finite(duration)
                    or not 0 < duration <= MAX_RUN_SECONDS):
                action = pump = None
            else:
                next_ml = min(DOSE_VOLUME_ML,
                              float(duration) * ASSUMED_FLOW_ML_PER_SECOND)
                seconds = next_ml / ASSUMED_FLOW_ML_PER_SECOND
                dose_ml = next_ml

    return Decision(active_mode, latched, reason, circulation,
                    circulation_gpio_level, action, pump, seconds, dose_ml)
