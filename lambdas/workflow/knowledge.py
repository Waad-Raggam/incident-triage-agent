"""Phase 4b: turn a closed incident into a document the Knowledge Base can retrieve next time."""

from __future__ import annotations

import json
import os

import boto3


def incident_markdown(inc: dict, resolution: str) -> str:
    t = inc.get("triage", {})
    evidence = "\n".join(f"- {e}" for e in t.get("evidence", [])) or "- (none recorded)"
    return (
        f"# Incident {inc['incident_id']} ({inc.get('service', '')})\n\n"
        f"Alarm: {inc.get('alarm_name', '')}\n"
        f"Opened: {inc.get('opened_at', '')}  Resolved: {inc.get('resolved_at', '')}\n"
        f"ServiceNow: {inc.get('ticket_number', '')}\n\n"
        f"## Root cause\n{t.get('root_cause', 'unknown')}\n\n"
        f"## Evidence\n{evidence}\n\n"
        f"## Fix applied\n{resolution}\n\n"
        f"## Remediation action\n{inc.get('remediation_result', {}).get('action', t.get('remediation_action', 'none'))}\n"
    )


def publish(inc: dict, resolution: str) -> str:
    bucket = os.environ["KNOWLEDGE_BUCKET"]
    key = f"incidents/{inc.get('service', 'unknown')}/{inc['incident_id']}.md"
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=incident_markdown(inc, resolution).encode(),
                  ContentType="text/markdown")
    meta = {"metadataAttributes": {"service": inc.get("service", ""), "incident_id": inc["incident_id"],
                                   "doc_type": "incident"}}
    s3.put_object(Bucket=bucket, Key=f"{key}.metadata.json", Body=json.dumps(meta).encode())
    _sync()
    return f"s3://{bucket}/{key}"


def _sync() -> None:
    """Start a Knowledge Base ingestion job, if Phase 4 is deployed."""
    ssm = boto3.client("ssm")
    try:
        kb_id = ssm.get_parameter(Name=os.environ["KB_ID_PARAM"])["Parameter"]["Value"]
        ds_id = ssm.get_parameter(Name=os.environ["KB_DS_PARAM"])["Parameter"]["Value"]
    except Exception:
        print("knowledge base not deployed yet; document stored for later sync")
        return
    try:
        boto3.client("bedrock-agent").start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    except Exception as exc:  # e.g. a sync is already running; the next close will pick this doc up
        print(f"ingestion not started: {exc}")
