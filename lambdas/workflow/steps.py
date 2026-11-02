"""Step Functions task handlers. Each step loads the incident from DynamoDB by ID, does one thing,
and returns a small JSON result. See infra/stacks/workflow_stack.py for how they are wired."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import boto3
import remediation
import store
from botocore.config import Config
from integrations import ServiceNow, slack_notify

import knowledge

SERVICE = os.environ.get("SERVICE_NAME", "checkout-api")


def _safe_slack(text: str) -> None:
    try:
        slack_notify(text)
    except Exception as exc:  # chat being down must not break incident handling
        print(f"slack failed: {exc}")


def _seconds_since(iso: str) -> float:
    started = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (datetime.now(UTC) - started).total_seconds()


# ---------------------------------------------------------------- 1. dedupe (Phase 3a)

def dedupe(event, _ctx=None):
    detail = event.get("detail", {})
    alarm_name = detail.get("alarmName", "unknown-alarm")
    incident_id = store.new_incident_id()
    existing = store.acquire_lock(SERVICE, incident_id)
    if existing:
        store.append_related_alarm(existing, alarm_name)
        store.metric("DuplicateAlarm", service=SERVICE)
        return {"incident_id": existing, "duplicate": True}
    store.put_incident(
        incident_id, status="TRIAGING", service=SERVICE, alarm_name=alarm_name,
        alarm=detail, opened_at=store.now_iso(),
    )
    return {"incident_id": incident_id, "duplicate": False}


# ---------------------------------------------------------------- 2. run the agent (Phase 2)

def run_agent(event, _ctx=None):
    incident_id = event["incident_id"]
    inc = store.get_incident(incident_id)
    client = boto3.client("bedrock-agentcore", config=Config(read_timeout=840, retries={"max_attempts": 2}))
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=os.environ["RUNTIME_ARN"],
        runtimeSessionId=f"incident-{incident_id}-{uuid.uuid4().hex}",
        payload=json.dumps({"incident_id": incident_id, "service": SERVICE, "alarm": inc.get("alarm", {})}).encode(),
    )
    body = resp["response"].read() if hasattr(resp["response"], "read") else resp["response"]
    data = json.loads(body)
    result = data["result"]

    # Safety net: an actionable incident always gets a ticket, even if the model forgot to open one
    if result["verdict"] == "actionable" and not result.get("ticket_sys_id"):
        t = ServiceNow().create_incident(
            f"{SERVICE}: {inc.get('alarm_name')} - {result['root_cause'][:100]}",
            result["root_cause"] + "\n\nEvidence:\n" + "\n".join(f"- {e}" for e in result["evidence"]),
            correlation_id=incident_id)
        result["ticket_number"], result["ticket_sys_id"] = t["number"], t["sys_id"]

    store.update_incident(
        incident_id, status="TRIAGED", triage=result, ticket_number=result.get("ticket_number", ""),
        ticket_sys_id=result.get("ticket_sys_id", ""), prompt_version=data.get("prompt_version"),
        model_id=data.get("model_id"), usage=data.get("usage", {}), triage_seconds=data.get("seconds"),
        tools_called=data.get("tools_called", []), stop_reason=data.get("stop_reason", ""),
    )
    store.metric("Triaged", verdict=result["verdict"])
    store.metric("TriageSeconds", data.get("seconds", 0), unit="Seconds")
    store.metric("TotalTokens", data.get("usage", {}).get("totalTokens", 0))
    return {"verdict": result["verdict"], "remediation_action": result["remediation_action"],
            "ticket_number": result.get("ticket_number", "")}


# ---------------------------------------------------------------- 3. approval in ServiceNow (Phase 5)

def request_approval(event, _ctx=None):
    incident_id, token = event["incident_id"], event["task_token"]
    inc = store.get_incident(incident_id)
    t = inc["triage"]
    snow = ServiceNow()
    change = snow.create_change(
        short_description=f"[{t['remediation_action']}] {SERVICE}: {t['root_cause'][:100]}",
        description=(f"Incident {inc.get('ticket_number')} ({incident_id})\n\nRoot cause: {t['root_cause']}\n\n"
                     "Evidence:\n" + "\n".join(f"- {e}" for e in t["evidence"]) +
                     f"\n\nAction if approved: {t['remediation_action']}"
                     + (f" to version {t['rollback_to_version']}" if t.get("rollback_to_version") else "")
                     + f"\nConfidence: {t['confidence']}"),
        incident_sys_id=inc.get("ticket_sys_id", ""), correlation_id=incident_id,
    )
    store.update_incident(incident_id, status="AWAITING_APPROVAL", task_token=token,
                          change_number=change["number"], change_sys_id=change["sys_id"],
                          approval_requested_at=store.now_iso())
    _safe_slack(
        f":rotating_light: *{SERVICE}* {inc.get('ticket_number')}: {t['root_cause']}\n"
        f"Suggested fix: {t['suggested_fix']} (confidence {t['confidence']:.0%})\n"
        f"Approve or reject change *{change['number']}* in ServiceNow: {change['url']}"
    )
    return {"change_number": change["number"]}


# ---------------------------------------------------------------- 4. remediate + verify

def remediate(event, _ctx=None):
    incident_id = event["incident_id"]
    inc = store.get_incident(incident_id)
    result = remediation.execute(inc["triage"]["remediation_action"],
                                 inc["triage"].get("rollback_to_version", ""))
    store.update_incident(incident_id, status="REMEDIATING", remediation_result=result,
                          remediated_at=store.now_iso())
    if inc.get("ticket_sys_id"):
        ServiceNow().add_work_note("incident", inc["ticket_sys_id"], f"Approved remediation executed: {json.dumps(result)}")
    _safe_slack(f":wrench: {inc.get('change_number')} approved. Ran `{result['action']}`: {json.dumps(result)}. Verifying...")
    return result


def verify(event, _ctx=None):
    inc = store.get_incident(event["incident_id"])
    names = [inc["alarm_name"]] + [a["alarm"] for a in inc.get("related_alarms", [])]
    alarms = boto3.client("cloudwatch").describe_alarms(AlarmNames=list(set(names)))["MetricAlarms"]
    states = {a["AlarmName"]: a["StateValue"] for a in alarms}
    return {"recovered": all(s != "ALARM" for s in states.values()), "states": states}


# ---------------------------------------------------------------- 5. endings

def close_and_learn(inc: dict, resolution: str, resolve_ticket: bool, path: str) -> None:
    incident_id = inc["incident_id"]
    store.update_incident(incident_id, status="RESOLVED", resolved_at=store.now_iso(), resolution=resolution)
    inc = store.get_incident(incident_id)
    if resolve_ticket and inc.get("ticket_sys_id"):
        ServiceNow().resolve_incident(inc["ticket_sys_id"], resolution)
    doc = knowledge.publish(inc, resolution)
    store.update_incident(incident_id, knowledge_doc=doc)
    store.release_lock(inc["service"], incident_id)
    store.metric("Resolved", path=path)
    store.metric("TimeToResolve", _seconds_since(inc["opened_at"]), unit="Seconds", path=path)
    _safe_slack(f":white_check_mark: {inc.get('ticket_number')} resolved ({path}). Saved to the knowledge base.")


def close_resolved(event, _ctx=None):
    inc = store.get_incident(event["incident_id"])
    r = inc.get("remediation_result", {})
    close_and_learn(inc, f"Automated {r.get('action')} after on-call approval: {json.dumps(r)}. Alarm cleared.",
                    resolve_ticket=True, path="automated")
    return {"status": "RESOLVED"}


def close_noise(event, _ctx=None):
    inc = store.get_incident(event["incident_id"])
    store.update_incident(inc["incident_id"], status="CLOSED_NOISE", resolved_at=store.now_iso())
    store.release_lock(inc["service"], inc["incident_id"])
    store.metric("Noise", alarm=inc.get("alarm_name", ""))
    return {"status": "CLOSED_NOISE"}


def hand_off(event, _ctx=None):
    """A human takes over. The poller closes the loop when the ServiceNow incident is resolved."""
    incident_id, reason = event["incident_id"], event.get("reason", "needs human triage")
    inc = store.get_incident(incident_id)
    store.update_incident(incident_id, status="HUMAN_TAKEOVER", handoff_reason=reason,
                          feedback="rejected" if "rejected" in reason else "handoff")
    store.metric("HandOff", reason=reason.split(":")[0][:40])
    _safe_slack(f":raising_hand: {SERVICE} {inc.get('ticket_number', '')}: {reason}. Over to on-call.")
    return {"status": "HUMAN_TAKEOVER"}
