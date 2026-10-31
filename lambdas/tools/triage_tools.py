"""The agent's tools. Plain functions so the same code runs:
- behind AgentCore Gateway (handler.py, a Lambda target), and
- in-process when you run the agent on your laptop (Phase 1).

Every tool returns JSON-serialisable dicts and never raises: errors come back as
{"error": "..."} so the agent can reason about them instead of crashing.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
from datetime import UTC, datetime, timedelta
from functools import cache

import boto3

MAX_LOG_ROWS = 30


@cache
def _client(name: str):
    return boto3.client(name)


def _iso(dt) -> str:
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


# ---------------------------------------------------------------- evidence (read-only)

def get_alarm(alarm_name: str) -> dict:
    cw = _client("cloudwatch")
    alarms = cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"]
    if not alarms:
        return {"error": f"alarm {alarm_name} not found"}
    a = alarms[0]
    history = cw.describe_alarm_history(AlarmName=alarm_name, HistoryItemType="StateUpdate", MaxRecords=5)
    return {
        "name": a["AlarmName"],
        "description": a.get("AlarmDescription", ""),
        "state": a["StateValue"],
        "reason": a.get("StateReason", ""),
        "metric": a.get("MetricName"),
        "namespace": a.get("Namespace"),
        "dimensions": {d["Name"]: d["Value"] for d in a.get("Dimensions", [])},
        "statistic": a.get("Statistic") or a.get("ExtendedStatistic"),
        "threshold": a.get("Threshold"),
        "recent_state_changes": [
            {"at": _iso(h["Timestamp"]), "summary": h["HistorySummary"]} for h in history["AlarmHistoryItems"]
        ],
    }


def get_metric_series(namespace: str, metric_name: str, dimensions: dict, stat: str = "Sum",
                      minutes: int = 60) -> dict:
    minutes = max(5, min(int(minutes), 24 * 60))
    end = datetime.now(UTC)
    resp = _client("cloudwatch").get_metric_data(
        MetricDataQueries=[{
            "Id": "m",
            "MetricStat": {
                "Metric": {"Namespace": namespace, "MetricName": metric_name,
                           "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()]},
                "Period": 60,
                "Stat": stat,
            },
        }],
        StartTime=end - timedelta(minutes=minutes),
        EndTime=end,
        ScanBy="TimestampAscending",
    )
    r = resp["MetricDataResults"][0]
    points = [{"t": _iso(t), "v": round(v, 2)} for t, v in zip(r["Timestamps"], r["Values"], strict=False)]
    values = [p["v"] for p in points]
    return {
        "metric": f"{namespace}/{metric_name} ({stat})",
        "points": points[-60:],
        "summary": {
            "count": len(values),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "median": statistics.median(values) if values else None,
            "last": values[-1] if values else None,
        },
    }


DEFAULT_LOG_QUERY = (
    "fields @timestamp, level, msg, error, version, dependency, latency_ms "
    "| filter level != 'INFO' | sort @timestamp desc | limit 30"
)


def query_logs(log_group: str, query: str = DEFAULT_LOG_QUERY, minutes: int = 30) -> dict:
    logs = _client("logs")
    end = int(time.time())
    start = end - max(5, min(int(minutes), 24 * 60)) * 60
    if "limit" not in query:
        query += f" | limit {MAX_LOG_ROWS}"
    qid = logs.start_query(logGroupName=log_group, startTime=start, endTime=end, queryString=query)["queryId"]
    for _ in range(30):
        res = logs.get_query_results(queryId=qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)
    rows = [{f["field"]: f["value"] for f in row if not f["field"].startswith("@ptr")}
            for row in res.get("results", [])[:MAX_LOG_ROWS]]
    return {"status": res["status"], "rows": rows, "stats": res.get("statistics", {})}


def get_recent_deploys(function_name: str, alias: str = "live") -> dict:
    lam = _client("lambda")
    current = lam.get_alias(FunctionName=function_name, Name=alias)
    versions = []
    for page in lam.get_paginator("list_versions_by_function").paginate(FunctionName=function_name):
        versions += [v for v in page["Versions"] if v["Version"] != "$LATEST"]
    versions.sort(key=lambda v: int(v["Version"]), reverse=True)
    return {
        "alias": alias,
        "alias_points_to": current["FunctionVersion"],
        "alias_description": current.get("Description", ""),
        "recent_versions": [
            {"version": v["Version"], "description": v.get("Description", ""), "published_at": v["LastModified"]}
            for v in versions[:5]
        ],
    }


def get_feature_flags(service: str) -> dict:
    try:
        raw = _client("ssm").get_parameter(Name=f"/{service}/flags")["Parameter"]
        return {"flags": json.loads(raw["Value"]), "last_modified": _iso(raw["LastModifiedDate"])}
    except Exception as exc:
        return {"error": str(exc)}


def score_anomaly(values: list[float]) -> dict:
    """Is the latest value abnormal compared with the rest of the window?

    Uses the SageMaker model from Phase 6 when its endpoint exists; otherwise a robust z-score.
    """
    values = [float(v) for v in values if v is not None]
    if len(values) < 6:
        return {"error": "need at least 6 values"}
    endpoint = os.environ.get("ANOMALY_ENDPOINT", "")
    if endpoint:
        try:
            resp = _client("sagemaker-runtime").invoke_endpoint(
                EndpointName=endpoint, ContentType="application/json", Body=json.dumps({"values": values}),
            )
            out = json.loads(resp["Body"].read())
            return {**out, "model": f"sagemaker:{endpoint}"}
        except Exception as exc:  # endpoint not deployed yet / scaled to zero error -> fall back
            fallback_reason = str(exc)[:200]
    else:
        fallback_reason = "no endpoint configured"
    return {**robust_zscore(values), "model": "robust-zscore", "fallback_reason": fallback_reason}


def robust_zscore(values: list[float], threshold: float = 4.0) -> dict:
    baseline, latest = values[:-3], values[-3:]
    med = statistics.median(baseline)
    mad = statistics.median([abs(v - med) for v in baseline])
    scale = max(1.4826 * mad, 0.05 * abs(med), 1.0)  # same floors as the ML features
    # 2nd-highest of the last 3: one blip is noise, two elevated points are a signal
    score = sorted((abs(v - med) / scale for v in latest), reverse=True)[1]
    score = 0.0 if math.isnan(score) else round(min(score, 1e6), 2)
    return {"score": score, "is_anomaly": score > threshold, "baseline_median": round(med, 2)}


# ---------------------------------------------------------------- knowledge (Phase 4)

def search_past_incidents(query: str, service: str = "") -> dict:
    try:
        kb_id = _client("ssm").get_parameter(Name=os.environ.get("KB_ID_PARAM", "/incident-triage/knowledge-base-id"))[
            "Parameter"]["Value"]
    except Exception:
        return {"results": [], "note": "knowledge base not deployed yet (Phase 4)"}
    cfg: dict = {"vectorSearchConfiguration": {"numberOfResults": 3}}
    if service:
        cfg["vectorSearchConfiguration"]["filter"] = {"equals": {"key": "service", "value": service}}
    resp = _client("bedrock-agent-runtime").retrieve(
        knowledgeBaseId=kb_id, retrievalQuery={"text": query[:1000]}, retrievalConfiguration=cfg,
    )
    return {
        "results": [
            {
                "score": round(r.get("score", 0), 3),
                "source": r.get("location", {}).get("s3Location", {}).get("uri", ""),
                "incident_id": r.get("metadata", {}).get("incident_id", ""),
                "text": r["content"]["text"][:1500],
            }
            for r in resp["retrievalResults"]
        ]
    }


# ---------------------------------------------------------------- actions (write, but never infra)

def create_incident_ticket(short_description: str, description: str, urgency: int = 2,
                           incident_id: str = "") -> dict:
    from integrations import ServiceNow  # lambda layer / local path

    return ServiceNow().create_incident(short_description, description, int(urgency), incident_id)


def notify_oncall(message: str) -> dict:
    from integrations import slack_notify

    return slack_notify(message[:3000])


TOOLS = {
    f.__name__: f
    for f in (get_alarm, get_metric_series, query_logs, get_recent_deploys, get_feature_flags, score_anomaly,
              search_past_incidents, create_incident_ticket, notify_oncall)
}


def call_tool(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{name} failed: {type(exc).__name__}: {str(exc)[:500]}"}
