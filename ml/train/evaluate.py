"""Pipeline evaluation step (SageMaker Processing). Also runs locally:

    python ml/train/evaluate.py --model ml/data/model --test ml/data/test --out ml/data/eval

Writes evaluation.json with precision / recall / f1 on the labelled test set. The pipeline only
registers the model if f1 clears the threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

import joblib

sys.path.insert(0, "/opt/ml/processing/lib")  # features.py in the pipeline's processing job
from features import window_features  # noqa: E402


def load_bundle(model_path: str):
    p = Path(model_path)
    tar = next(p.glob("*.tar.gz"), None)
    if tar:  # SageMaker gives us model.tar.gz
        with tarfile.open(tar) as t:
            for m in t.getmembers():  # our own artifact, but still refuse path tricks
                if m.name.startswith(("/", "..")) or ".." in m.name:
                    raise ValueError(f"unsafe path in model tar: {m.name}")
            t.extractall(p)
    return joblib.load(p / "model.joblib")


def metrics(y_true: list[int], y_pred: list[int]) -> dict:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
            "tp": tp, "fp": fp, "fn": fn, "n": len(y_true)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="/opt/ml/processing/model")
    ap.add_argument("--test", default="/opt/ml/processing/test")
    ap.add_argument("--out", default="/opt/ml/processing/evaluation")
    a = ap.parse_args()

    bundle = load_bundle(a.model)
    rows = []
    for f in Path(a.test).glob("*.jsonl"):
        rows += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    scores = -bundle["model"].score_samples([window_features(r["values"]) for r in rows])
    y_pred = [int(s > bundle["threshold"]) for s in scores]
    result = {"anomaly_detection": metrics([r["label"] for r in rows], y_pred)}

    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "evaluation.json").write_text(json.dumps(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
