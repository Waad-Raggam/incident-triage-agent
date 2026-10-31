"""Runs every minute. Closes the human-in-the-loop gaps without exposing a public webhook:

- AWAITING_APPROVAL: is the ServiceNow change approved/rejected?  -> resume Step Functions
- HUMAN_TAKEOVER:    is the ServiceNow incident resolved?         -> close and learn (the manual-fix path)
"""

import json

import boto3
import steps
import store
from integrations import ServiceNow

sfn = boto3.client("stepfunctions")


def handler(event, context):
    snow = ServiceNow()
    stats = {"approved": 0, "rejected": 0, "closed_manual": 0}

    for inc in store.incidents_with_status("AWAITING_APPROVAL"):
        approval = snow.get_change_approval(inc["change_sys_id"])
        if approval == "approved":
            store.update_incident(inc["incident_id"], status="APPROVED", feedback="approved",
                                  approved_at=store.now_iso())
            sfn.send_task_success(taskToken=inc["task_token"], output=json.dumps({"approved": True}))
            store.metric("FixApproved")
            stats["approved"] += 1
        elif approval == "rejected":
            store.update_incident(inc["incident_id"], status="REJECTED", feedback="rejected")
            sfn.send_task_failure(taskToken=inc["task_token"], error="Rejected",
                                  cause=f"change {inc.get('change_number')} rejected in ServiceNow")
            store.metric("FixRejected")
            stats["rejected"] += 1

    for inc in store.incidents_with_status("HUMAN_TAKEOVER"):
        if not inc.get("ticket_sys_id"):
            continue
        ticket = snow.get_incident(inc["ticket_sys_id"])
        if ticket.get("state") in ("6", "7"):  # Resolved, Closed
            notes = ticket.get("close_notes") or "Resolved manually by on-call."
            steps.close_and_learn(inc, f"Manual fix: {notes}", resolve_ticket=False, path="manual")
            stats["closed_manual"] += 1

    print(json.dumps(stats))
    return stats
