"""Make a labelled dataset of metric windows to bootstrap the anomaly model.

A brand-new demo app has no incident history, so we simulate realistic series (latency, error counts,
traffic) and inject anomalies. Labels: anomaly = at least 2 of the last 3 points clearly elevated.
One-point blips stay "normal" on purpose, because those are the alarms we want to call noise.

    python ml/make_training_data.py --out ml/data            # local files
    python ml/make_training_data.py --s3 s3://BUCKET/data    # straight to the ML bucket
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

WINDOW = 30


def series(kind: str, rng: random.Random) -> list[float]:
    if kind == "latency":
        base = rng.uniform(80, 400)
        return [max(1.0, rng.gauss(base, base * rng.uniform(0.04, 0.15))) for _ in range(WINDOW)]
    if kind == "errors":
        lam = rng.uniform(0, 2)
        return [float(sum(1 for _ in range(20) if rng.random() < lam / 20)) for _ in range(WINDOW)]
    base = rng.uniform(20, 60)  # traffic
    return [max(0.0, rng.gauss(base, base * 0.1)) for _ in range(WINDOW)]


def inject(values: list[float], kind: str, rng: random.Random, mode: str) -> list[float]:
    v = list(values)
    med = sorted(v)[len(v) // 2] or 1.0
    if mode == "spike":  # sustained: last 2-3 points
        n = rng.choice([2, 3])
        for i in range(WINDOW - n, WINDOW):
            v[i] = (v[i] + rng.uniform(5, 30)) if kind == "errors" else med * rng.uniform(3, 20)
    elif mode == "blip":  # a single point, should be treated as noise
        i = WINDOW - rng.randint(1, 3)
        v[i] = (v[i] + rng.uniform(2, 6)) if kind == "errors" else med * rng.uniform(1.5, 3)
    elif mode == "drop":  # traffic falls off a cliff
        for i in range(WINDOW - 3, WINDOW):
            v[i] = med * rng.uniform(0.0, 0.2)
    return v


def make(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        kind = rng.choice(["latency", "errors", "traffic"])
        mode = rng.choices(["normal", "blip", "spike", "drop"], weights=[60, 15, 20, 5])[0]
        if mode == "drop" and kind != "traffic":
            mode = "spike"
        v = series(kind, rng)
        if mode != "normal":
            v = inject(v, kind, rng, mode)
        rows.append({"kind": kind, "values": [round(x, 2) for x in v], "label": int(mode in ("spike", "drop"))})
    return rows


def write(rows: list[dict], target: str, name: str) -> None:
    body = "\n".join(json.dumps(r) for r in rows)
    if target.startswith("s3://"):
        import boto3

        bucket, _, prefix = target[5:].partition("/")
        boto3.client("s3").put_object(Bucket=bucket, Key=f"{prefix.rstrip('/')}/{name}/{name}.jsonl", Body=body.encode())
    else:
        p = Path(target) / name
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{name}.jsonl").write_text(body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ml/data")
    ap.add_argument("--s3", default="")
    ap.add_argument("--n", type=int, default=6000)
    a = ap.parse_args()
    target = a.s3 or a.out
    write(make(a.n, seed=1), target, "train")
    write(make(a.n // 3, seed=2), target, "test")
    print(f"wrote train/test to {target}")
