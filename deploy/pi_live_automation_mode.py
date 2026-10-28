"""Mode decisions from the integrated Pi sensor cache; no GPIO operations.

The legacy sensor adapters are placeholders on the Pi. They must not hold the
mode override when the integrated acquisition is healthy. This module keeps
all physical outputs disabled while the pump controller is being qualified.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


FULL = "Full Automation Mode"
SEMI = "Semi-Automation Mode"
OUTPUTS = ("ph_up", "ph_down", "nutrient_dosing", "circulation_pump")
REQUIRED = {
    "ph": "value",
    "ec": "value_mScm",
    "water_temperature": "value_C",
    "turbidity": "value_ntu",
}
MAX_SAMPLE_AGE_SECONDS = 65


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _status(result):
    return str(getattr(result, "status", "") or "")


def _value(result):
    return getattr(result, "value", None)


def _age_seconds(snapshot, now):
    try:
        timestamp = datetime.fromisoformat(snapshot["timestamp"])
        if timestamp.tzinfo is None:
            return math.inf
        return (now - timestamp.astimezone(timezone.utc)).total_seconds()
    except (KeyError, TypeError, ValueError):
        return math.inf


def evaluate_live(selected_mode, snapshot, water, plant, camera, limits,
                  extra_fault=False, *, now=None):
    """Evaluate safety from fresh live readings, with descriptive outputs only."""
    if selected_mode not in (FULL, SEMI):
        raise ValueError("Unknown operating mode")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    sensors = snapshot.get("sensors", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(sensors, dict):
        sensors = {}
    age = _age_seconds(snapshot, now) if isinstance(snapshot, dict) else math.inf
    faults = []
    circulation_stop_reasons = []
    holds = []
    if not 0 <= age <= MAX_SAMPLE_AGE_SECONDS:
        faults.append("Integrated sensor sample is stale")
        circulation_stop_reasons.append("Integrated sensor sample is stale")
    for name, field in REQUIRED.items():
        sensor = sensors.get(name)
        if not isinstance(sensor, dict):
            holds.append(name + " reading missing")
            faults.append(name + " unavailable")
            circulation_stop_reasons.append(name + " unavailable")
            continue
        status = str(sensor.get("status") or "")
        failures = sensor.get("consecutive_failures")
        persistent = (type(failures) is int and failures >= 2)
        if (status.startswith(("ERROR", "FAULT", "UNAVAILABLE"))
                or (sensor.get("valid") is False and persistent)):
            faults.append(name + " fault")
            circulation_stop_reasons.append(name + " fault")
        ready = (status.startswith("OK") or status == "CALIBRATED")
        if (not ready or not _finite(sensor.get(field)) or sensor.get("retained")
                or sensor.get("stale") or sensor.get("valid") is False):
            holds.append(name + " reading not fresh")
        if str(sensor.get("classification") or "").upper() == "CRITICAL":
            faults.append(name + " Critical")
        value = sensor.get(field)
        numeric_critical = (
            (name == "ph" and _finite(value) and (value < 4.5 or value > 8.0))
            or (name == "ec" and _finite(value) and (value < 0.5 or value > 4.0))
            or (name == "water_temperature" and _finite(value) and value > 35.0)
            or (name == "turbidity" and _finite(value) and value >= 20.0)
        )
        if numeric_critical and name + " Critical" not in faults:
            faults.append(name + " Critical")
    if _value(water) == "Critical":
        faults.append("water quality Critical")
    if _status(plant) == "FAULT / ERROR" or (isinstance(camera, dict)
                                              and camera.get("status") == "FAULT / ERROR"):
        faults.append("Faulty Vision")
        circulation_stop_reasons.append("Faulty Vision")
    if extra_fault:
        faults.append("system fault")
        circulation_stop_reasons.append("system fault")
    if _value(water) not in ("Optimal", "Suboptimal", "Critical"):
        holds.append("water classification unavailable")
    if _value(plant) not in ("Healthy", "Yellowing", "Wilting", "Harvest-Ready"):
        holds.append("plant classification unavailable")
    override = bool(faults)
    active = SEMI if override else selected_mode
    ph = sensors.get("ph") or {}
    ec = sensors.get("ec") or {}
    recommendations = []
    if "ph reading not fresh" not in holds and _finite(ph.get("value")):
        bounds = limits.get("ph_optimal") if isinstance(limits, dict) else None
        if isinstance(bounds, (tuple, list)) and len(bounds) == 2:
            if ph["value"] < bounds[0]:
                recommendations.append("pH-Up dosing")
            elif ph["value"] > bounds[1]:
                recommendations.append("pH-Down dosing")
    if "ec reading not fresh" not in holds and _finite(ec.get("value_mScm")):
        bounds = limits.get("ec_optimal") if isinstance(limits, dict) else None
        if isinstance(bounds, (tuple, list)) and len(bounds) == 2:
            if ec["value_mScm"] < bounds[0]:
                recommendations.append("EC nutrient dosing")
            elif ec["value_mScm"] > bounds[1]:
                recommendations.append("High EC: manual inspection; correction procedure pending")
    return {
        "selected_mode": selected_mode,
        "active_mode": active,
        "override": override,
        "override_reason": "; ".join(faults) if faults else None,
        "circulation_stop_required": bool(circulation_stop_reasons),
        "hold_reason": "; ".join(holds) if holds else None,
        "recommendations": recommendations,
        "confirmation_required": active == SEMI,
        "actuation_enabled": False,
        "outputs": {name: "OFF (hardware integration pending)" for name in OUTPUTS},
        "hardware_status": "UNAVAILABLE — CONTROL INTEGRATION PENDING",
        "critical_turbidity": "turbidity Critical" in faults,
    }
