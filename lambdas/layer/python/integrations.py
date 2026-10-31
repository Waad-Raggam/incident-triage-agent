"""ServiceNow + Slack clients shared by the tools Lambda, the workflow Lambdas and the local agent.

Credentials live in Secrets Manager (never in code or env vars):
  incident-triage/servicenow  -> {"instance_url": "...", "username": "...", "password": "..."}
  incident-triage/slack       -> {"webhook_url": "..."}
Only the standard library + boto3 are used, so no extra Lambda dependencies are needed.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

import boto3


@lru_cache(maxsize=8)
def get_secret(name: str) -> dict:
    sm = boto3.client("secretsmanager")
    return json.loads(sm.get_secret_value(SecretId=name)["SecretString"])


def _http(method: str, url: str, headers: dict, body: dict | None = None, timeout: int = 15) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode() or "{}"
            return json.loads(raw) if raw.strip().startswith(("{", "[")) else {"raw": raw}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {exc.read().decode()[:300]}") from exc


class ServiceNow:
    """Minimal Table API client: incidents + change requests."""

    def __init__(self, secret_name: str | None = None):
        s = get_secret(secret_name or os.environ.get("SERVICENOW_SECRET", "incident-triage/servicenow"))
        self.base = s["instance_url"].rstrip("/")
        token = base64.b64encode(f"{s['username']}:{s['password']}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json",
                        "Content-Type": "application/json"}

    def _table(self, method: str, table: str, sys_id: str = "", body: dict | None = None,
               query: dict | None = None) -> dict:
        url = f"{self.base}/api/now/table/{table}" + (f"/{sys_id}" if sys_id else "")
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return _http(method, url, self.headers, body)["result"]

    def create_incident(self, short_description: str, description: str, urgency: int = 2,
                        correlation_id: str = "") -> dict:
        r = self._table("POST", "incident", body={
            "short_description": short_description[:160],
            "description": description,
            "urgency": str(urgency),
            "impact": str(urgency),
            "category": "software",
            "correlation_id": correlation_id,
            "caller_id": "",
        })
        return {"number": r["number"], "sys_id": r["sys_id"], "url": self.link("incident", r["sys_id"])}

    def get_incident(self, sys_id: str) -> dict:
        r = self._table("GET", "incident", sys_id, query={"sysparm_fields": "number,state,close_notes,close_code"})
        return r

    def resolve_incident(self, sys_id: str, notes: str) -> None:
        self._table("PATCH", "incident", sys_id, body={
            "state": "6", "close_code": "Solved (Permanently)", "close_notes": notes[:3900],
        })

    def add_work_note(self, table: str, sys_id: str, note: str) -> None:
        self._table("PATCH", table, sys_id, body={"work_notes": note[:3900]})

    def create_change(self, short_description: str, description: str, incident_sys_id: str,
                      correlation_id: str) -> dict:
        r = self._table("POST", "change_request", body={
            "short_description": short_description[:160],
            "description": description,
            "type": "normal",
            "justification": "Suggested by the incident triage agent; needs on-call approval.",
            "implementation_plan": "Automated by AWS Step Functions after approval.",
            "backout_plan": "Re-run the previous state (automatic for rollbacks).",
            "parent": incident_sys_id,
            "correlation_id": correlation_id,
            "approval": "requested",
        })
        return {"number": r["number"], "sys_id": r["sys_id"], "url": self.link("change_request", r["sys_id"])}

    def get_change_approval(self, sys_id: str) -> str:
        """Returns 'requested' | 'approved' | 'rejected' | 'not requested'."""
        return self._table("GET", "change_request", sys_id, query={"sysparm_fields": "approval"})["approval"]

    def link(self, table: str, sys_id: str) -> str:
        return f"{self.base}/nav_to.do?uri={table}.do?sys_id={sys_id}"


def slack_notify(text: str, secret_name: str | None = None) -> dict:
    s = get_secret(secret_name or os.environ.get("SLACK_SECRET", "incident-triage/slack"))
    _http("POST", s["webhook_url"], {"Content-Type": "application/json"}, {"text": text})
    return {"sent": True}
