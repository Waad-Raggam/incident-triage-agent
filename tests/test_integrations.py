import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lambdas/layer/python"))

import integrations  # noqa: E402


def test_incident_sets_agent_as_caller(monkeypatch):
    """Phase 1b: INC0010001 had an empty Caller (a required field). The agent now opens tickets as itself."""
    monkeypatch.setattr(integrations, "get_secret", lambda name: {
        "instance_url": "https://dev0.service-now.com", "username": "triage-agent", "password": "x"})
    calls = []

    def fake_http(method, url, headers, body=None, timeout=15):
        calls.append((method, url, body))
        if "sys_user" in url:
            return {"result": [{"sys_id": "agent-sys-id"}]}
        return {"result": {"number": "INC0010002", "sys_id": "inc-sys-id"}}

    monkeypatch.setattr(integrations, "_http", fake_http)
    sn = integrations.ServiceNow()
    out = sn.create_incident("short", "long", urgency=1, correlation_id="2026-11-02-abc")
    sn.create_incident("again", "long")

    posts = [c for c in calls if c[0] == "POST"]
    assert out["number"] == "INC0010002"
    assert posts[0][2]["caller_id"] == "agent-sys-id"
    assert sum("sys_user" in c[1] for c in calls) == 1  # user lookup is cached
