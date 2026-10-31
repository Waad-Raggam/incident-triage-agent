"""Phase 6d: daily drift check (Lambda). Serverless endpoints don't support SageMaker Model Monitor's
data capture, so we check drift ourselves - which also makes the idea easier to explain:

1. Take the last 24h of the live metric, cut it into windows, compute the same features as training.
2. Compare each feature's distribution with the training baseline (decile edges) using PSI.
3. Publish the worst PSI as a CloudWatch metric. If it is above 0.25, start the training pipeline.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta

from features import FEATURE_NAMES, window_features

PSI_RETRAIN = 0.25
WINDOW, STEP = 30, 10


def psi(edges: list[float], values: list[float]) -> float:
    """Population Stability Index against 10 equal-mass bins defined by the baseline deciles."""
    if not values:
        return 0.0
    inner = edges[1:-1]
    counts = [0] * (len(inner) + 1)
    for v in values:
        counts[sum(1 for e in inner if v > e)] += 1
    expected = 1 / len(counts)
    total = 0.0
    for c in counts:
        actual = max(c / len(values), 1e-4)
        total += (actual - expected) * math.log(actual / expected)
    return round(total, 4)


def windows(series: list[float]) -> list[list[float]]:
    return [series[i:i + WINDOW] for i in range(0, len(series) - WINDOW + 1, STEP)]


def drift_report(baseline: dict, series: list[float]) -> dict:
    feats = [window_features(w) for w in windows(series)]
    per_feature = {name: psi(baseline[name], [f[i] for f in feats]) for i, name in enumerate(FEATURE_NAMES)}
    return {"windows": len(feats), "psi": per_feature, "max_psi": max(per_feature.values()) if feats else 0.0}


def handler(event, context):  # pragma: no cover - AWS glue
    import boto3

    s3, cw, sm = boto3.client("s3"), boto3.client("cloudwatch"), boto3.client("sagemaker")
    try:
        baseline = json.loads(s3.get_object(Bucket=os.environ["ML_BUCKET"],
                                            Key="monitoring/baseline_stats.json")["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {"skipped": "no baseline yet - deploy a model first (ml/deploy.py)"}

    end = datetime.now(UTC)
    res = cw.get_metric_data(
        MetricDataQueries=[{"Id": "d", "MetricStat": {"Metric": {
            "Namespace": "AWS/Lambda", "MetricName": "Duration",
            "Dimensions": [{"Name": "FunctionName", "Value": os.environ["SERVICE_NAME"]},
                           {"Name": "Resource", "Value": f"{os.environ['SERVICE_NAME']}:live"}]},
            "Period": 60, "Stat": "p99"}}],
        StartTime=end - timedelta(hours=24), EndTime=end, ScanBy="TimestampAscending")
    series = res["MetricDataResults"][0]["Values"]
    report = drift_report(baseline, series)

    cw.put_metric_data(Namespace="IncidentTriage", MetricData=[
        {"MetricName": "AnomalyModelDriftPSI", "Value": report["max_psi"], "Unit": "None"}])
    if report["max_psi"] > PSI_RETRAIN:
        execs = sm.list_pipeline_executions(PipelineName=os.environ["PIPELINE_NAME"], MaxResults=1,
                                            SortBy="CreationTime", SortOrder="Descending")
        recent = execs.get("PipelineExecutionSummaries", [])
        if not recent or recent[0]["StartTime"] < end - timedelta(hours=24):
            # Add today's real windows to the training set so the new model learns the new normal
            rows = "\n".join(json.dumps({"kind": "live", "values": w, "label": 0}) for w in windows(series))
            s3.put_object(Bucket=os.environ["ML_BUCKET"], Key=f"data/train/live-{end:%Y%m%d}.jsonl",
                          Body=rows.encode())
            sm.start_pipeline_execution(PipelineName=os.environ["PIPELINE_NAME"],
                                        PipelineExecutionDescription=f"drift psi={report['max_psi']}")
            report["retraining_started"] = True
    print(json.dumps(report))
    return report
