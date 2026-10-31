import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from drift import drift_report, psi
from features import FEATURE_NAMES, window_features

ROOT = Path(__file__).parent.parent


def test_features_shape_and_signal():
    flat = window_features([100.0] * 30)
    spike = window_features([100.0] * 27 + [500.0, 520.0, 510.0])
    assert len(flat) == len(FEATURE_NAMES)
    assert spike[0] > flat[0] and spike[FEATURE_NAMES.index('n_recent_high')] == 3


def test_features_need_enough_points():
    with pytest.raises(ValueError):
        window_features([1, 2, 3])


def test_psi_zero_when_same_distribution_and_high_when_shifted():
    edges = [float(i) for i in range(11)]  # deciles of uniform 0..10
    same = [i / 10 + 0.05 for i in range(100)]
    shifted = [9.5] * 100
    assert psi(edges, same) < 0.05
    assert psi(edges, shifted) > 1.0


def test_drift_report_runs_on_a_day_of_minutes():
    baseline = {n: [float(i) for i in range(11)] for n in FEATURE_NAMES}
    rep = drift_report(baseline, [100.0 + (i % 7) for i in range(1440)])
    assert rep["windows"] > 100 and set(rep["psi"]) == set(FEATURE_NAMES)


@pytest.mark.skipif(importlib.util.find_spec("sklearn") is None, reason="scikit-learn not installed")
def test_train_and_evaluate_end_to_end(tmp_path):
    """Generate data -> train -> evaluate, exactly like the pipeline does, on a small sample."""
    run = lambda *a: subprocess.run([sys.executable, *a], check=True, capture_output=True, text=True, cwd=ROOT)  # noqa: E731
    run("ml/make_training_data.py", "--out", str(tmp_path), "--n", "3000")
    run("ml/train/train.py", "--train", str(tmp_path / "train"), "--model-dir", str(tmp_path / "model"))
    run("ml/train/evaluate.py", "--model", str(tmp_path / "model"), "--test", str(tmp_path / "test"),
        "--out", str(tmp_path / "eval"))
    result = json.loads((tmp_path / "eval/evaluation.json").read_text())["anomaly_detection"]
    assert result["f1"] >= 0.8, result

    sys.path.insert(0, str(ROOT / "ml/train"))
    import inference

    bundle = inference.model_fn(str(tmp_path / "model"))
    normal = inference.predict_fn([100.0 + (i % 5) for i in range(30)], bundle)
    spike = inference.predict_fn([100.0 + (i % 5) for i in range(27)] + [900, 950, 990], bundle)
    assert spike["is_anomaly"] and not normal["is_anomaly"]
