import json
from pathlib import Path

import triage_tools
from triage_tools import call_tool, robust_zscore

SCHEMA = json.loads((Path(__file__).parent.parent / "lambdas/tools/schema.json").read_text())


def test_schema_matches_implementations():
    assert {t["name"] for t in SCHEMA} == set(triage_tools.TOOLS)
    for t in SCHEMA:
        assert t["inputSchema"]["type"] == "object"
        for req in t["inputSchema"].get("required", []):
            assert req in t["inputSchema"]["properties"], (t["name"], req)


def test_unknown_tool_and_bad_args_return_errors_not_exceptions():
    assert "error" in call_tool("rm_rf", {})
    assert "bad arguments" in call_tool("score_anomaly", {"nope": 1})["error"]


def test_robust_zscore_flags_sustained_spike_not_flat_series():
    flat = [100.0] * 27 + [101.0, 99.0, 100.0]
    spike = [100.0 + (i % 3) for i in range(27)] + [900.0, 950.0, 1000.0]
    assert not robust_zscore(flat)["is_anomaly"]
    assert robust_zscore(spike)["is_anomaly"]


def test_score_anomaly_falls_back_without_endpoint(monkeypatch):
    monkeypatch.delenv("ANOMALY_ENDPOINT", raising=False)
    out = call_tool("score_anomaly", {"values": [1, 1, 1, 1, 1, 1, 50, 60, 70]})
    assert out["model"] == "robust-zscore" and out["is_anomaly"]


def test_gateway_handler_strips_target_prefix(monkeypatch):
    import handler

    seen = {}
    monkeypatch.setattr(handler, "call_tool", lambda name, args: seen.update(name=name, args=args) or {"ok": 1})

    class Ctx:
        class client_context:  # noqa: N801
            custom = {"bedrockAgentCoreToolName": "triage-tools___get_feature_flags"}

    assert handler.handler({"service": "checkout-api"}, Ctx) == {"ok": 1}
    assert seen == {"name": "get_feature_flags", "args": {"service": "checkout-api"}}
