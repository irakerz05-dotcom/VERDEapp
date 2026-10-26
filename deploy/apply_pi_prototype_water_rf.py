#!/usr/bin/env python3
"""Guardedly install the descriptive, synthetic water RF on the modified Pi.

Fetch backend feature/prototype-water-rf first. --check changes nothing.
--apply backs up changed source, then writes model files atomically. The
service is not restarted, and no automation, GPIO, SMS, or calibration file
is modified.
"""

import argparse
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND_COMMIT = "211b3c111284b7df2f442648ede286bf690e4f21"
DEFAULT_TARGET = Path("/home/verde/VERDE-Sensor-Integration")


def replace_once(source, old, new, label):
    if source.count(new) == 1:
        return source
    if source.count(old) != 1:
        raise ValueError(f"{label}: expected exactly one reviewed anchor")
    return source.replace(old, new, 1)


def patch_service(source):
    changes = (
        ("from app.ml.water_quality import PendingClassifier, FEATURES, CLASSES\n",
         "from app.ml.water_quality import PendingClassifier, FEATURES, CLASSES\n"
         "from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live\n",
         "prototype import"),
        ("        self.classifier = classifier or PendingClassifier()\n",
         "        self.classifier = classifier or PendingClassifier()\n"
         "        self.prototype_classifier = PrototypeRFClassifier()\n",
         "prototype constructor"),
        ("            sensor_fault = required_water_sensor_fault(live_snapshot)\n",
         "            experimental_water = guarded(lambda: self.prototype_classifier.classify(\n"
         "                features_from_live(live_snapshot)), error_status=\"MODEL UNAVAILABLE\")\n"
         "            sensor_fault = required_water_sensor_fault(live_snapshot)\n",
         "classify cached live sample"),
        ("                            if sensor_fault else water)\n",
         "                            if sensor_fault else experimental_water)\n",
         "descriptive fusion input"),
        ('                "camera": camera, "water_quality": water.as_dict(), "plant_condition": plant.as_dict(),\n',
         '                "camera": camera, "water_quality": water.as_dict(),\n'
         '                "water_quality_experimental": experimental_water.as_dict(),\n'
         '                "plant_condition": plant.as_dict(),\n',
         "status output"),
        ('                              "camera": unavailable, "water_quality": unavailable, "plant_condition": unavailable,\n',
         '                              "camera": unavailable, "water_quality": unavailable,\n'
         '                              "water_quality_experimental": unavailable, "plant_condition": unavailable,\n',
         "failure output"),
    )
    for old, new, label in changes:
        source = replace_once(source, old, new, label)
    compile(source, "app/service.py", "exec")
    return source


def patch_fusion(source):
    source = replace_once(
        source,
        '                or (sensor_status != "Faulty Sensor" and water.status != "READY")\n',
        '                or (sensor_status != "Faulty Sensor" and water.status not in ("READY", "EXPERIMENTAL"))\n',
        "experimental fusion status",
    )
    source = replace_once(
        source,
        '        if faults:\n            detail += " " + "; ".join(faults)\n',
        '        if water.status == "EXPERIMENTAL":\n'
        '            detail = "Prototype from synthetic paper-rule examples; unvalidated with real labeled water. " + detail\n'
        '        if faults:\n            detail += " " + "; ".join(faults)\n',
        "fusion provenance",
    )
    compile(source, "app/fusion/__init__.py", "exec")
    return source


def git_file(root, name):
    return subprocess.run(["git", "-C", str(root), "show", f"{BACKEND_COMMIT}:{name}"],
                          check=True, capture_output=True).stdout


def prepare(root):
    service = root / "app/service.py"
    fusion = root / "app/fusion/__init__.py"
    module = root / "app/ml/water_quality/prototype_rf.py"
    artifact = root / "models/water_quality_rf_prototype.json.gz"
    if not service.is_file() or not fusion.is_file():
        raise ValueError("Expected Pi backend service and fusion files are missing")
    if "live_snapshot = integrated.snapshot()" not in service.read_text(encoding="utf-8"):
        raise ValueError("Integrated Pi sensor cache is unavailable")
    module_bytes = git_file(root, "app/ml/water_quality/prototype_rf.py")
    artifact_bytes = git_file(root, "models/water_quality_rf_prototype.json.gz")
    compile(module_bytes, str(module), "exec")
    import gzip
    import json
    model = json.loads(gzip.decompress(artifact_bytes))
    if (model.get("training_source") != "synthetic_paper_thresholds"
            or len(model.get("trees", ())) != 100):
        raise ValueError("Unexpected prototype model artifact")
    for path, data in ((module, module_bytes), (artifact, artifact_bytes)):
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f"Existing file differs from reviewed prototype: {path}")
    planned = {
        service: patch_service(service.read_text(encoding="utf-8")).encode(),
        fusion: patch_fusion(fusion.read_text(encoding="utf-8")).encode(),
        module: module_bytes,
        artifact: artifact_bytes,
    }
    return planned, sum(not path.exists() or path.read_bytes() != data
                        for path, data in planned.items())


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    root = args.target.resolve()
    try:
        planned, edits = prepare(root)
    except (OSError, ValueError, subprocess.CalledProcessError, SyntaxError) as exc:
        parser.exit(1, f"Prototype RF patch not ready: {exc}\n")
    if args.check:
        print(f"Ready: {root}; {edits} guarded updates; model validated; no files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, contents in planned.items():
        if path.exists() and path.read_bytes() == contents:
            continue
        if path.exists():
            backup = path.with_name(f"{path.name}.before_prototype_rf_{stamp}")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")
        atomic_write(path, contents)
        print(f"Updated: {path}")
    print("Service was NOT restarted. No GPIO, calibration, automation, or SMS settings were changed.")


if __name__ == "__main__":
    main()
