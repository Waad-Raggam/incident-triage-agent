"""SageMaker training script (scikit-learn container, script mode). Also runs locally:

    python ml/train/train.py --train ml/data/train --model-dir ml/data/model

Model: IsolationForest trained on NORMAL windows only (novelty detection). The decision threshold is
the 99th percentile of training scores. Saves baseline feature stats for drift monitoring.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import joblib
import numpy as np
from features import FEATURE_NAMES, window_features
from sklearn.ensemble import IsolationForest


def load(path: str) -> tuple[np.ndarray, np.ndarray]:
    rows = []
    for f in Path(path).glob("*.jsonl"):
        rows += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    X = np.array([window_features(r["values"]) for r in rows])
    y = np.array([r.get("label", 0) for r in rows])
    return X, y


def baseline_stats(X: np.ndarray) -> dict:
    """Decile edges per feature: the reference distribution the drift check compares against."""
    return {name: np.quantile(X[:, i], np.linspace(0, 1, 11)).round(6).tolist()
            for i, name in enumerate(FEATURE_NAMES)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default=os.environ.get("SM_CHANNEL_TRAIN", "ml/data/train"))
    ap.add_argument("--model-dir", default=os.environ.get("SM_MODEL_DIR", "ml/data/model"))
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--threshold-quantile", type=float, default=0.99)
    a = ap.parse_args()

    X, y = load(a.train)
    normal = X[y == 0] if y.any() else X
    model = IsolationForest(n_estimators=a.n_estimators, random_state=42).fit(normal)
    scores = -model.score_samples(normal)
    threshold = float(np.quantile(scores, a.threshold_quantile))

    out = Path(a.model_dir)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "threshold": threshold, "features": FEATURE_NAMES}, out / "model.joblib")
    (out / "baseline_stats.json").write_text(json.dumps(baseline_stats(normal)))
    print(json.dumps({"train_rows": len(X), "normal_rows": len(normal), "threshold": threshold}))


if __name__ == "__main__":
    main()
