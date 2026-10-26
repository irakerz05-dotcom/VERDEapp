"""Read-only live inference for the tiny, threshold-labeled real-sensor RF pilot.

The service publishes this result separately from its official classifier,
synthetic prototype, fusion, automation, and SMS decisions.
"""

import gzip
import json
import math
from pathlib import Path


ARTIFACT = Path("/home/verde/verde-water-rf-pilot-holdout-optimal02.json.gz")
FEATURES = ("ph", "ec", "water_temperature", "turbidity")
CLASSES = {"Optimal", "Suboptimal", "Critical"}
LIMITS = ((0, 14), (0, 10), (0, 50), (0, 100))
SOURCE = "real_pi_readings_labeled_by_paper_thresholds"


def threshold_class(values):
    ph, ec, temperature, turbidity = values
    if ph < 4.5 or ph > 8 or ec < 0.5 or ec > 4 or temperature > 35 or turbidity > 20:
        return "Critical"
    if 5.5 <= ph <= 6.5 and 1.2 <= ec <= 1.8 and 18 <= temperature <= 24 and turbidity < 5:
        return "Optimal"
    return "Suboptimal"


def load_model(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        model = json.load(handle)
    if (model.get("format_version") != 1 or model.get("training_source") != SOURCE
            or tuple(model.get("features", ())) != FEATURES
            or set(model.get("classes", ())) != CLASSES
            or not isinstance(model.get("training_batch_ids"), list)
            or not isinstance(model.get("held_out_batch_ids"), list)
            or len(model.get("mean", ())) != 4 or len(model.get("scale", ())) != 4
            or len(model.get("trees", ())) != 100):
        raise ValueError("Incompatible real-data pilot artifact")
    return model


def predict(model, values):
    scaled = []
    for value, mean, scale in zip(values, model["mean"], model["scale"]):
        if not all(math.isfinite(x) for x in (value, mean, scale)) or scale <= 0:
            raise ValueError("Invalid pilot scaling")
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
            raise ValueError("Invalid pilot tree")
    return model["classes"][max(range(len(scores)), key=scores.__getitem__)]


class RealDataPilotClassifier:
    def __init__(self, artifact=ARTIFACT):
        self.model = None
        self.load_error = None
        try:
            self.model = load_model(artifact)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"

    def classify(self, features, fluctuating=()):
        if self.model is None:
            return {"status": "CLASSIFIER NOT LOADED", "value": None,
                    "detail": self.load_error or "Pilot model unavailable"}
        if not isinstance(features, dict) or set(features) != set(FEATURES):
            return {"status": "SENSOR INPUT UNAVAILABLE", "value": None,
                    "detail": "Four fresh water sensor readings are required."}
        values = []
        for name, (low, high) in zip(FEATURES, LIMITS):
            value = features[name]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not low <= value <= high):
                return {"status": "SENSOR INPUT UNAVAILABLE", "value": None,
                        "detail": f"Fresh valid {name} reading required."}
            values.append(float(value))
        try:
            predicted = predict(self.model, values)
        except (IndexError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            return {"status": "MODEL UNAVAILABLE", "value": None,
                    "detail": f"Pilot inference failed: {type(exc).__name__}"}
        rule = threshold_class(values)
        detail = ("Experimental RF fitted to three real Pi readings with paper-threshold labels; "
                  "no independent validation. Project-relative turbidity reference. "
                  f"Paper thresholds: {rule}.")
        if predicted != rule:
            detail += " Pilot and thresholds disagree; inspect the readings."
        if fluctuating:
            detail += " Raw signal fluctuating for " + ", ".join(fluctuating) + "; provisional reading."
        return {"status": "EXPERIMENTAL", "value": predicted, "detail": detail}
