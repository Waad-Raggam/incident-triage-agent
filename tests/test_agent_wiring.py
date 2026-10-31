"""End-to-end agent wiring test, offline: a scripted fake model drives the real Strands loop,
the real fixture tools and the real structured output. No AWS, no Bedrock."""

import json
from pathlib import Path

from strands.models.model import Model
from toolkit import fixture_tools
from triage import run_triage

CASE = json.loads((Path(__file__).parent.parent / "evals/incidents/bad-deploy-errors.json").read_text())


class ScriptedModel(Model):
    """Turn 1: get_alarm. Turn 2: create_incident_ticket. Then: answer via the structured output tool."""

    def __init__(self):
        self.turn = 0

    def update_config(self, **kw):
        pass

    def get_config(self):
        return {"model_id": "scripted"}

    async def structured_output(self, *a, **kw):  # pragma: no cover - not used by the agent loop
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kw):
        names = [t["name"] for t in tool_specs or []]
        self.turn += 1
        if self.turn == 1:
            name, args = "get_alarm", {"alarm_name": "checkout-api-errors"}
        elif self.turn == 2:
            name, args = "create_incident_ticket", {"short_description": "x", "description": "y",
                                                    "incident_id": "t-1"}
        else:
            name = next(n for n in names if n not in [s for s in names if s.startswith(("get_", "query_", "score_",
                                                                                         "search_", "create_",
                                                                                         "notify_"))])
            args = {"verdict": "actionable", "root_cause": "version 2 deploy", "evidence": ["alias -> 2"],
                    "similar_incidents": [], "suggested_fix": "roll back", "remediation_action": "rollback_deploy",
                    "confidence": 0.8, "ticket_number": "INC0099999", "ticket_sys_id": "fixture-sys-id"}
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"t{self.turn}", "name": name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
                            "metrics": {"latencyMs": 1}}}


def test_agent_runs_tools_and_returns_structured_result():
    calls = []
    run = run_triage({"alarmName": "checkout-api-errors"}, "t-1", "checkout-api",
                     fixture_tools(CASE["fixtures"], calls), use_memory=False, model=ScriptedModel())
    assert run.result.remediation_action == "rollback_deploy"
    assert run.result.ticket_number == "INC0099999"
    assert [c["tool"] for c in calls] == ["get_alarm", "create_incident_ticket"]
    assert "get_alarm" in run.tools_called
    assert run.usage.get("totalTokens", 0) > 0


def test_agent_failure_falls_back_to_human():
    class Broken(ScriptedModel):
        async def stream(self, *a, **kw):
            raise RuntimeError("bedrock down")
            yield  # pragma: no cover

    run = run_triage({}, "t-2", "checkout-api", fixture_tools({}), use_memory=False, model=Broken())
    assert run.result.remediation_action == "none"
    assert run.result.confidence == 0
    assert run.stop_reason.startswith("error")
