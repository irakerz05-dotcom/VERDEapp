#!/usr/bin/env python3
"""Capture one new, valid Pi water reading into an unlabeled physical batch.

This polls the service's cached API. It never triggers sensor acquisition,
changes calibration, restarts the service, or assigns a quality class.
"""

import argparse
import csv
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


API = "http://127.0.0.1:8000/api/sensors/latest"
DEFAULT_OUTPUT = Path.home() / "verde-water-quality-batches.csv"
COLUMNS = ("sample_id", "timestamp", "ph", "ec_mScm", "water_temperature_C",
           "turbidity_NTU_project_reference", "water_sample_batch_id",
           "independent_reference_label", "reference_method", "labeled_at", "notes")
FIELDS = (("ph", "value", "OK", 0, 14),
          ("ec", "value_mScm", "OK", 0, 10),
          ("water_temperature", "value_C", "OK", 0, 50),
          ("turbidity", "value_ntu", "CALIBRATED", 0, 100))
BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def reading(snapshot, started, now):
    """Accept only a complete acquisition that happened after this capture began."""
    if not isinstance(snapshot, dict):
        raise ValueError("Sensor snapshot is not an object")
    system, sensors = snapshot.get("system"), snapshot.get("sensors")
    if not isinstance(system, dict) or not isinstance(sensors, dict):
        raise ValueError("Sensor cache is incomplete")
    sample = system.get("sample")
    session = system.get("csv_path")
    if (isinstance(sample, bool) or not isinstance(sample, int) or sample < 1
            or not isinstance(session, str) or not session):
        raise ValueError("No completed sensor acquisition")
    try:
        measured = datetime.fromisoformat(snapshot["timestamp"])
        if measured.tzinfo is None:
            raise ValueError("Sensor timestamp has no timezone")
        measured_utc = measured.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Sensor timestamp is invalid") from exc
    if measured_utc <= started:
        raise ValueError("Waiting for the next sensor acquisition")
    age = (now - measured_utc).total_seconds()
    if age < -5 or age > 65:
        raise ValueError("Sensor acquisition is stale or in the future")
    values = []
    for name, field, expected, low, high in FIELDS:
        sensor = sensors.get(name)
        if not isinstance(sensor, dict):
            raise ValueError(f"{name} reading is missing")
        status = str(sensor.get("status") or "")
        valid_status = status.startswith(expected) if expected == "OK" else status == expected
        value = sensor.get(field)
        if (not valid_status or sensor.get("valid") is False
                or sensor.get("retained") is True or sensor.get("stale") is True
                or sensor.get("spike") is True or sensor.get("read_error") is not None
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            raise ValueError(f"{name} is not a fresh valid reading ({status or 'no status'})")
        values.append(float(value))
    return f"{Path(session).name}#{sample}", measured.isoformat(), values


def wait_for_reading(started, timeout_seconds=120, fetch=None, clock=None, sleeper=None):
    fetch = fetch or fetch_snapshot
    clock = clock or (lambda: datetime.now(timezone.utc))
    sleeper = sleeper or time.sleep
    deadline = time.monotonic() + timeout_seconds
    last_error = "No new sensor acquisition"
    while time.monotonic() < deadline:
        try:
            return reading(fetch(), started, clock())
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        sleeper(3)
    raise TimeoutError(f"No complete fresh four-sensor sample within {timeout_seconds}s: {last_error}")


def fetch_snapshot():
    with urlopen(API, timeout=5) as response:
        return json.load(response)


def save_row(output, batch_id, captured):
    if not BATCH_ID.fullmatch(batch_id):
        raise ValueError("Batch ID must be 1–64 letters, numbers, dots, underscores or hyphens")
    output = Path(output).resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError("Capture CSV must be outside the Git repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    sample_id, timestamp, values = captured
    if output.exists():
        with output.open(newline="", encoding="utf-8") as handle:
            existing = csv.DictReader(handle)
            if tuple(existing.fieldnames or ()) != COLUMNS:
                raise ValueError("Existing CSV has incompatible columns")
            if any(row["sample_id"] == sample_id for row in existing):
                raise ValueError("This sensor acquisition is already captured")
    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if handle.tell() == 0:
            writer.writerow(COLUMNS)
        writer.writerow((sample_id, timestamp, *values, batch_id, "", "", "", ""))
        handle.flush()
        os.fsync(handle.fileno())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True,
                        help="Stable ID for one physical solution, not one row")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    if not BATCH_ID.fullmatch(args.batch_id):
        parser.error("Invalid physical batch ID")
    if not 10 <= args.timeout_seconds <= 600:
        parser.error("Timeout must be 10–600 seconds")
    started = datetime.now(timezone.utc)
    print("Waiting for a new complete Pi sensor acquisition. Do not move the probe during capture.")
    try:
        captured = wait_for_reading(started, args.timeout_seconds)
        output = save_row(args.output, args.batch_id, captured)
    except (OSError, ValueError, TimeoutError) as exc:
        parser.exit(1, f"Capture failed: {exc}\n")
    print(f"Saved sample {captured[0]} for physical batch {args.batch_id} in {output}")
    print("Reference label remains blank. Use an independent method before training.")


if __name__ == "__main__":
    main()
