#!/usr/bin/env python3
"""Compare an OFFLINE pilot RF with a separately captured held-out batch.

Threshold agreement is not independent validation or an accuracy estimate.
This reads local files only and never changes the live VERDE service.
"""

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.train_pi_water_pilot import CLASSES, FEATURES, audit_pilot


SOURCE = "real_pi_readings_labeled_by_paper_thresholds"


def load_pilot(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        model = json.load(handle)
    if (model.get("format_version") != 1 or model.get("training_source") != SOURCE
            or model.get("features") != list(FEATURES)
            or set(model.get("classes", ())) != set(CLASSES)
            or not isinstance(model.get("training_batch_ids"), list)
            or not isinstance(model.get("held_out_batch_ids"), list)
            or len(model.get("mean", ())) != 4 or len(model.get("scale", ())) != 4
            or len(model.get("trees", ())) != 100):
        raise ValueError("Pilot model is incompatible or lacks holdout provenance; refit with --holdout-batch")
    return model


def predict(model, values):
    scaled = []
    for value, mean, scale in zip(values, model["mean"], model["scale"]):
        if not all(math.isfinite(x) for x in (value, mean, scale)) or scale <= 0:
            raise ValueError("Invalid model scaling")
        scaled.append((value - mean) / scale)
    scores = [0.0] * len(model["classes"])
    for tree in model["trees"]:
        node = 0
        for _ in range(1000):
            if tree["left"][node] == -1:
                for index, score in enumerate(tree["leaf"][node]):
                    scores[index] += score
                break
            feature = tree["feature"][node]
            node = (tree["left"][node] if scaled[feature] <= tree["threshold"][node]
                    else tree["right"][node])
        else:
            raise ValueError("Invalid model tree")
    return model["classes"][max(range(len(scores)), key=scores.__getitem__)]


def compare(model, samples, batch_id):
    if batch_id not in model["held_out_batch_ids"] or batch_id in model["training_batch_ids"]:
        raise ValueError("Batch was not explicitly held out of this model's fit")
    rows = [row for row in samples if row["batch"] == batch_id]
    if not rows:
        raise ValueError("No usable readings in held-out batch")
    return {
        "batch_id": batch_id,
        "comparison": "pilot prediction versus threshold-derived class; no independent reference",
        "readings": [{"sample_id": row["sample_id"],
                      "pilot_prediction": predict(model, row["values"]),
                      "threshold_class": row["label"]} for row in rows],
        "accuracy": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--exclude-sample", action="append", default=[])
    args = parser.parse_args()
    try:
        samples, _ = audit_pilot(args.csv, args.exclude_sample)
        print(json.dumps(compare(load_pilot(args.model), samples, args.batch_id), indent=2))
    except (OSError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Pilot comparison failed: {exc}\n")


if __name__ == "__main__":
    main()
