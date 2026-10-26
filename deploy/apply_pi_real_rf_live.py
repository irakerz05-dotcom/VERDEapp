#!/usr/bin/env python3
"""Guardedly expose the real-reading RF pilot as a separate live API result.

The official classifier, synthetic fusion input, safety mode, SMS, GPIO, and
calibration are untouched. --check writes nothing; --apply backs up the service
but does not restart it.
"""

import argparse
import gzip
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
MODEL = Path("/home/verde/verde-water-rf-pilot-holdout-optimal02.json.gz")
MODULE = Path(__file__).with_name("pi_real_rf_live.py")


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected exactly one reviewed source anchor")
    return source.replace(old, new, 1)


def patch_service(source):
    changes = (
        ("from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs\n",
         "from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs\n"
         "from app.ml.water_quality.real_rf_pilot import RealDataPilotClassifier\n", "pilot import"),
        ("        self.prototype_classifier = PrototypeRFClassifier()\n",
         "        self.prototype_classifier = PrototypeRFClassifier()\n"
         "        self.real_pilot_classifier = RealDataPilotClassifier()\n", "pilot constructor"),
        ("            sensor_fault = required_water_sensor_fault(live_snapshot)\n",
         "            real_pilot_water = guarded(lambda: Result(**self.real_pilot_classifier.classify(\n"
         "                features_from_live(live_snapshot), fluctuating=fluctuating_inputs(live_snapshot))),\n"
         "                error_status=\"MODEL UNAVAILABLE\")\n"
         "            sensor_fault = required_water_sensor_fault(live_snapshot)\n", "pilot live inference"),
        ('                "water_quality_experimental": experimental_water.as_dict(),\n',
         '                "water_quality_experimental": experimental_water.as_dict(),\n'
         '                "water_quality_real_pilot": real_pilot_water.as_dict(),\n', "pilot API result"),
        ('                              "water_quality_experimental": unavailable, "plant_condition": unavailable,\n',
         '                              "water_quality_experimental": unavailable,\n'
         '                              "water_quality_real_pilot": unavailable, "plant_condition": unavailable,\n',
         "pilot error state"),
    )
    for old, new, label in changes:
        source = replace_once(source, old, new, label)
    compile(source, "app/service.py", "exec")
    return source


def prepare(root=BACKEND, model_path=MODEL):
    service = root / "app/service.py"
    module = root / "app/ml/water_quality/real_rf_pilot.py"
    source = service.read_text(encoding="utf-8")
    if ("live_snapshot = integrated.snapshot()" not in source
            or "fusion_water =" not in source
            or "automation = evaluate(" not in source):
        raise ValueError("Expected live-cache and safety boundaries are missing")
    model_source = MODULE.read_bytes()
    compile(model_source, str(module), "exec")
    with gzip.open(model_path, "rt", encoding="utf-8") as handle:
        model = json.load(handle)
    if (model.get("training_source") != "real_pi_readings_labeled_by_paper_thresholds"
            or model.get("format_version") != 1
            or model.get("features") != ["ph", "ec", "water_temperature", "turbidity"]
            or len(model.get("training_batch_ids", ())) != 3
            or "optimal-solution-02" not in model.get("held_out_batch_ids", ())
            or len(model.get("trees", ())) != 100):
        raise ValueError("Expected three-batch, threshold-labeled pilot with Optimal-02 held out")
    if module.exists() and module.read_bytes() != model_source:
        raise ValueError("Existing pilot module differs from reviewed source")
    planned = {service: patch_service(source).encode("utf-8"), module: model_source}
    return planned, sum(not path.exists() or path.read_bytes() != data
                        for path, data in planned.items())


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
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
    parser.add_argument("--target", type=Path, default=BACKEND)
    parser.add_argument("--model", type=Path, default=MODEL)
    args = parser.parse_args()
    try:
        planned, edits = prepare(args.target.resolve(), args.model.resolve())
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Live pilot patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {edits} guarded edits; model and source validated; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    for path, data in planned.items():
        if path.exists() and path.read_bytes() == data:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.before_real_rf_live_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
        atomic_write(path, data)
        print(f"Updated: {path}")
    print("Service was NOT restarted. The live pilot is descriptive only; safety paths are unchanged.")


if __name__ == "__main__":
    main()
