"""DynamoDB access for incidents + per-service locks, and CloudWatch metrics."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache

import boto3
from boto3.dynamodb.conditions import Attr, Key

LOCK_TTL_SECONDS = 6 * 3600
METRIC_NS = "IncidentTriage"


@lru_cache(maxsize=1)
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE"])


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_incident_id() -> str:
    return f"{datetime.now(UTC):%Y-%m-%d}-{uuid.uuid4().hex[:6]}"


def to_ddb(value):
    """DynamoDB wants Decimal, not float."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_ddb(v) for v in value]
    return value


def from_ddb(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_ddb(v) for v in value]
    return value


def acquire_lock(service: str, incident_id: str) -> str | None:
    """Returns None if we got the lock, else the ID of the incident already open for this service."""
    now = int(time.time())
    try:
        table().put_item(
            Item={"pk": f"LOCK#{service}", "incident_id": incident_id, "expires_at": now + LOCK_TTL_SECONDS},
            ConditionExpression=Attr("pk").not_exists() | Attr("expires_at").lt(now),
        )
        return None
    except table().meta.client.exceptions.ConditionalCheckFailedException:
        return table().get_item(Key={"pk": f"LOCK#{service}"})["Item"]["incident_id"]


def release_lock(service: str, incident_id: str) -> None:
    try:
        table().delete_item(Key={"pk": f"LOCK#{service}"}, ConditionExpression=Attr("incident_id").eq(incident_id))
    except table().meta.client.exceptions.ConditionalCheckFailedException:
        pass  # someone else's lock now


def put_incident(incident_id: str, **fields) -> None:
    table().put_item(Item=to_ddb({"pk": f"INCIDENT#{incident_id}", "incident_id": incident_id, **fields}))


def get_incident(incident_id: str) -> dict:
    return from_ddb(table().get_item(Key={"pk": f"INCIDENT#{incident_id}"}).get("Item", {}))


def update_incident(incident_id: str, **fields) -> None:
    fields["updated_at"] = now_iso()
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": to_ddb(v) for k, v in fields.items()}
    table().update_item(
        Key={"pk": f"INCIDENT#{incident_id}"},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def append_related_alarm(incident_id: str, alarm_name: str) -> None:
    table().update_item(
        Key={"pk": f"INCIDENT#{incident_id}"},
        UpdateExpression="SET related_alarms = list_append(if_not_exists(related_alarms, :empty), :a)",
        ExpressionAttributeValues={":a": [{"alarm": alarm_name, "at": now_iso()}], ":empty": []},
    )


def incidents_with_status(status: str) -> list[dict]:
    resp = table().query(IndexName="status-index", KeyConditionExpression=Key("status").eq(status))
    return [from_ddb(i) for i in resp["Items"]]


def metric(name: str, value: float = 1, unit: str = "Count", **dims) -> None:
    try:
        boto3.client("cloudwatch").put_metric_data(
            Namespace=METRIC_NS,
            MetricData=[{"MetricName": name, "Value": value, "Unit": unit,
                         "Dimensions": [{"Name": k, "Value": str(v)} for k, v in dims.items()]}],
        )
    except Exception as exc:
        print(f"metric {name} failed: {exc}")
