#!/usr/bin/env python3
"""Fit an OFFLINE RF pilot to captured Pi readings labeled by paper rules.

This is a threshold imitation exercise, not independent validation. The output
cannot be loaded by VERDE's live prototype loader. No service or GPIO is touched.
"""

import argparse
import csv
import gzip
import json
import math
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ("sample_id", "timestamp", "ph", "ec_mScm", "water_temperature_C",
           "turbidity_NTU_project_reference", "water_sample_batch_id",
           "independent_reference_label", "reference_method", "labeled_at", "notes")
FEATURES = ("ph", "ec", "water_temperature", "turbidity")
CLASSES = ("Optimal", "Suboptimal", "Critical")
LIMITS = ((0, 14), (0, 10), (0, 50), (0, 100))
SEED = 20261026


def paper_label(values):
    ph, ec, temperature, turbidity = values
    if ph < 4.5 or ph > 8 or ec < 0.5 or ec > 4 or temperature > 35 or turbidity > 20:
        return "Critical"
    if 5.5 <= ph <= 6.5 and 1.2 <= ec <= 1.8 and 18 <= temperature <= 24 and turbidity < 5:
        return "Optimal"
    return "Suboptimal"


def audit_pilot(path, exclusions=()):
    """Validate every row; exclude only explicitly named boundary observations."""
    exclusions = set(exclusions)
    seen = set()
    samples = []
    batch_labels = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(COLUMNS).issubset(reader.fieldnames):
            raise ValueError("CSV does not match the Pi water batch columns")
        for line, row in enumerate(reader, 2):
            sample_id = (row["sample_id"] or "").strip()
            batch = (row["water_sample_batch_id"] or "").strip()
            if not sample_id or sample_id in seen or not batch:
                raise ValueError(f"Line {line}: duplicate/empty sample ID or empty batch ID")
            seen.add(sample_id)
            try:
                stamp = datetime.fromisoformat(row["timestamp"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Line {line}: invalid timestamp") from exc
            if stamp.tzinfo is None:
                raise ValueError(f"Line {line}: timestamp needs timezone")
            values = []
            for column, (low, high) in zip(COLUMNS[2:6], LIMITS):
                try:
                    value = float(row[column])
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Line {line}: invalid {column}") from exc
                if not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"Line {line}: {column} outside accepted sensor range")
                values.append(value)
            if any((row[name] or "").strip() for name in
                   ("independent_reference_label", "reference_method", "labeled_at")):
                raise ValueError(f"Line {line}: pilot requires an unlabeled capture CSV")
            if sample_id in exclusions:
                continue
            label = paper_label(values)
            if batch in batch_labels and batch_labels[batch] != label:
                raise ValueError(f"Batch {batch} has conflicting threshold labels; inspect the boundary readings and explicitly exclude only unsuitable samples")
            batch_labels[batch] = label
            samples.append({"sample_id": sample_id, "batch": batch,
                            "label": label, "values": values})
    unknown = exclusions - seen
    if unknown:
        raise ValueError(f"Unknown excluded sample ID(s): {', '.join(sorted(unknown))}")
    by_class = Counter(batch_labels.values())
    return samples, {
        "training_source": "real_pi_readings_labeled_by_paper_thresholds",
        "validation": "None: no independent labels or held-out water batches",
        "rows_in_csv": len(seen), "excluded_sample_ids": sorted(exclusions),
        "usable_rows": len(samples), "batches_by_class": dict(by_class),
        "ready_for_exploratory_fit": all(by_class[name] >= 1 for name in CLASSES),
    }


def export_tree(estimator):
    tree = estimator.tree_
    return {
        "left": tree.children_left.tolist(),
        "right": tree.children_right.tolist(),
        "feature": tree.feature.tolist(),
        "threshold": tree.threshold.tolist(),
        "leaf": [[float(v / sum(row)) for v in row]
                 for row in tree.value[:, 0, :]],
    }


def fit_pilot(samples, summary, output, holdout_batches=()):
    holdout_batches = set(holdout_batches)
    available_batches = {row["batch"] for row in samples}
    if holdout_batches - available_batches:
        raise ValueError("Unknown held-out batch ID(s): " + ", ".join(sorted(holdout_batches - available_batches)))
    training = [row for row in samples if row["batch"] not in holdout_batches]
    training_classes = {row["label"] for row in training}
    if training_classes != set(CLASSES):
        raise ValueError("Need at least one training batch in each of the three classes after holdout")
    output = Path(output).resolve()
    if output.is_relative_to(ROOT) or output.exists():
        raise ValueError("Choose a new output path outside the Git repository")
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError("Offline pilot needs scikit-learn, NumPy and SciPy") from exc
    model = make_pipeline(StandardScaler(), RandomForestClassifier(
        n_estimators=100, max_depth=10, random_state=SEED, n_jobs=1))
    model.fit([row["values"] for row in training], [row["label"] for row in training])
    scaler, forest = model.steps[0][1], model.steps[1][1]
    artifact = {
        "format_version": 1, "training_source": summary["training_source"],
        "validation": summary["validation"], "features": list(FEATURES),
        "units": ["pH", "mS/cm", "C", "project-relative NTU"],
        "classes": forest.classes_.tolist(), "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "trees": [export_tree(tree) for tree in forest.estimators_],
        "audit": summary,
        "training_batch_ids": sorted({row["batch"] for row in training}),
        "held_out_batch_ids": sorted(holdout_batches),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
                compressed.write(json.dumps(artifact, separators=(",", ":"), allow_nan=False).encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="Unlabeled Pi water batch CSV")
    parser.add_argument("--exclude-sample", action="append", default=[],
                        help="Explicitly omit a boundary reading by its full sample ID")
    parser.add_argument("--holdout-batch", action="append", default=[],
                        help="Keep this complete batch out of fitting for offline comparison")
    parser.add_argument("--pilot-output", type=Path,
                        help="Fit a new offline pilot artifact outside Git")
    args = parser.parse_args()
    try:
        samples, summary = audit_pilot(args.csv, args.exclude_sample)
        print(json.dumps(summary, indent=2))
        if args.pilot_output:
            output = fit_pilot(samples, summary, args.pilot_output, args.holdout_batch)
            print(f"Offline exploratory RF saved to {output}; no accuracy claimed; NOT installed on Pi")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Pilot not fitted: {exc}\n")


if __name__ == "__main__":
    main()
