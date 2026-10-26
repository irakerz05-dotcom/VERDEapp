#!/usr/bin/env python3
"""Use fresh median-filtered Pi values in descriptive RF despite raw ADC spikes.

The RF result names fluctuating sensors and stays provisional. Batch capture
still rejects spikes; fusion, automation, GPIO, SMS and calibration are not
changed. --check is read-only; --apply backs up files but does not restart.
"""

import argparse
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path


BACKEND = Path("/home/verde/VERDE-Sensor-Integration")
MODEL = "app/ml/water_quality/prototype_rf.py"
SERVICE = "app/service.py"
REPLACEMENTS = {
    MODEL: (
        ('or sensor.get("stale") is True or sensor.get("spike") is True\n'
         '                or sensor.get("read_error") is not None):',
         'or sensor.get("stale") is True or sensor.get("read_error") is not None):'),
        ('    return values\n\n\ndef _load_artifact(path):',
         '''    return values


def fluctuating_inputs(snapshot):
    """Keep raw ADC spike evidence separate from filtered RF feature values."""
    sensors = snapshot.get("sensors") if isinstance(snapshot, dict) else None
    if not isinstance(sensors, dict):
        return ()
    return tuple(name for name in FEATURES
                 if isinstance(sensors.get(name), dict) and sensors[name].get("spike") is True)


def _load_artifact(path):'''),
        ('    def classify(self, features):',
         '    def classify(self, features, fluctuating=()):'),
        ('        return Result("EXPERIMENTAL", predicted,\n'
         '                      detail="Prototype Random Forest trained on paper-rule examples; not validated with labeled measurements. Turbidity uses a project-assigned NTU reference.")',
         '''        detail = ("Prototype Random Forest trained on paper-rule examples; not validated with labeled measurements. "
                  "Turbidity uses a project-assigned NTU reference.")
        if fluctuating:
            detail += (" Raw signal fluctuating for " + ", ".join(fluctuating)
                       + "; prediction uses the latest median-filtered value and is provisional.")
        return Result("EXPERIMENTAL", predicted, detail=detail)'''),
    ),
    SERVICE: (
        ('from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live',
         'from app.ml.water_quality.prototype_rf import PrototypeRFClassifier, features_from_live, fluctuating_inputs'),
        ('            experimental_water = guarded(lambda: self.prototype_classifier.classify(\n'
         '                features_from_live(live_snapshot)), error_status="MODEL UNAVAILABLE")',
         '            experimental_water = guarded(lambda: self.prototype_classifier.classify(\n'
         '                features_from_live(live_snapshot), fluctuating=fluctuating_inputs(live_snapshot)),\n'
         '                error_status="MODEL UNAVAILABLE")'),
    ),
}


def transform(source, changes, name):
    for old, new in changes:
        if source.count(old) != 1 or new in source:
            raise ValueError(f"{name}: expected one reviewed source anchor")
        source = source.replace(old, new, 1)
    compile(source, name, "exec")
    return source


def prepare(root=BACKEND):
    prepared = []
    for name, changes in REPLACEMENTS.items():
        path = root / name
        prepared.append((path, transform(path.read_text(encoding="utf-8"), changes, name)))
    return prepared


def apply(root=BACKEND):
    prepared = prepare(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups = []
    for path, _ in prepared:
        backup = path.with_name(f"{path.name}.before_rf_filtered_spikes_{stamp}")
        shutil.copy2(path, backup)
        backups.append(backup)
    for path, updated in prepared:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, path.stat().st_mode)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return backups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(f"Ready: {len(prepare())} guarded RF files; syntax valid; no files changed")
    else:
        for backup in apply():
            print(f"Backup: {backup}")
        print("Experimental RF updated. Service was NOT restarted.")


if __name__ == "__main__":
    main()
