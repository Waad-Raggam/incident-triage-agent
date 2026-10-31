"""SageMaker inference handlers. Request: {"values": [...]}  Response: {"score", "threshold", "is_anomaly"}."""

import json
import os

import joblib
from features import window_features


def model_fn(model_dir):
    return joblib.load(os.path.join(model_dir, "model.joblib"))


def input_fn(body, content_type="application/json"):
    data = json.loads(body)
    return [float(v) for v in data["values"]]


def predict_fn(values, bundle):
    score = float(-bundle["model"].score_samples([window_features(values)])[0])
    return {"score": round(score, 4), "threshold": round(bundle["threshold"], 4),
            "is_anomaly": score > bundle["threshold"]}


def output_fn(prediction, accept="application/json"):
    return json.dumps(prediction), "application/json"
