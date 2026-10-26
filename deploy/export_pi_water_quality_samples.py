#!/usr/bin/env python3
"""Export real, complete Pi water sensor rows for independent labeling.

This reads SQLite only. It never assigns a water-quality label, trains a model,
changes the live service, or copies data into a Git repository.
"""

import argparse
import csv
import json
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


BACKEND = Path.home() / "VERDE-Sensor-Integration"
COLUMNS = ("sample_id", "timestamp", "ph", "ec_mScm", "water_temperature_C",
           "turbidity_NTU_project_reference", "water_sample_batch_id",
           "independent_reference_label", "reference_method", "labeled_at", "notes")
DOMAINS = ((0, 14), (0, 10), (0, 50), (0, 100))


def database_path(backend):
    example = json.loads((backend / "config.example.json").read_text(encoding="utf-8"))
    local = backend / "config.local.json"
    settings = json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}
    configured = settings.get("database_path", example["database_path"])
    if not isinstance(configured, str) or not configured:
        raise ValueError("Invalid backend database_path")
    path = Path(configured)
    return path if path.is_absolute() else backend / path


def valid_row(row):
    for value, (low, high) in zip(row[2:], DOMAINS):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            return False
    try:
        timestamp = datetime.fromisoformat(row[1])
        if timestamp.tzinfo is None:
            return False
    except (TypeError, ValueError):
        return False
    return True


def export(database, output, min_interval_minutes=30):
    database = Path(database).resolve()
    output = Path(output).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Sensor database not found: {database}")
    if output.exists():
        raise FileExistsError(f"Output already exists; choose a new name: {output}")
    if min_interval_minutes < 0:
        raise ValueError("Interval cannot be negative")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
        count = 0
        last_time = None
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(COLUMNS)
                rows = connection.execute(
                    "SELECT id, timestamp, ph, ec, water_temperature, turbidity "
                    "FROM sensor_samples WHERE ph IS NOT NULL AND ec IS NOT NULL "
                    "AND water_temperature IS NOT NULL AND turbidity IS NOT NULL "
                    "ORDER BY timestamp, id"
                )
                for row in rows:
                    if not valid_row(row):
                        continue
                    when = datetime.fromisoformat(row[1]).astimezone(timezone.utc)
                    if last_time is not None and (when - last_time).total_seconds() < min_interval_minutes * 60:
                        continue
                    writer.writerow((*row, "", "", "", "", ""))
                    last_time = when
                    count += 1
                handle.flush()
                os.fsync(handle.fileno())
            # Both files are in one directory: link atomically, never replacing an export.
            os.link(temporary, output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    finally:
        connection.close()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, default=BACKEND)
    parser.add_argument("--database", type=Path, help="Override backend configuration")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-interval-minutes", type=int, default=30)
    args = parser.parse_args()
    try:
        source = args.database or database_path(args.backend)
        count = export(source, args.output, args.min_interval_minutes)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Export failed: {exc}\n")
    print(f"Exported {count} complete, unlabeled real sensor rows to {args.output}")
    print("Assign labels only from an independent reference. Do not use the prototype's prediction as a label.")


if __name__ == "__main__":
    main()
