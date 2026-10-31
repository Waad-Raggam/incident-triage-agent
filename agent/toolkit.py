"""Three ways to give the agent its tools, same agent code for all three:

- "local":   call the tool functions in-process with your own AWS credentials (Phase 1)
- "gateway": call them through AgentCore Gateway over MCP, signed with SigV4 (Phase 2+, in the cloud)
- "fixture": return canned outputs from an eval case, no AWS calls at all (Phase 7 evals)
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from strands.tools.tools import PythonAgentTool

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "lambdas" / "tools" / "schema.json"


def _load_schema() -> list[dict]:
    path = Path(os.environ.get("TOOL_SCHEMA_PATH", SCHEMA_PATH))
    return json.loads(path.read_text())


def _wrap(spec: dict, fn: Callable[[str, dict], dict]) -> PythonAgentTool:
    tool_spec = {"name": spec["name"], "description": spec["description"],
                 "inputSchema": {"json": spec["inputSchema"]}}

    def run(tool_use, **_):
        out = fn(spec["name"], tool_use.get("input") or {})
        return {"toolUseId": tool_use["toolUseId"], "status": "error" if "error" in out else "success",
                "content": [{"json": out}]}

    return PythonAgentTool(spec["name"], tool_spec, run)


def local_tools() -> list:
    for p in (REPO / "lambdas" / "tools", REPO / "lambdas" / "layer" / "python"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from triage_tools import call_tool

    return [_wrap(s, call_tool) for s in _load_schema()]


def fixture_tools(fixtures: dict, calls: list | None = None) -> list:
    """fixtures: {tool_name: output_dict}. Unknown tools return an error, like a real outage would."""
    calls = calls if calls is not None else []

    def call(name: str, args: dict) -> dict:
        calls.append({"tool": name, "args": args})
        if name == "create_incident_ticket":
            return {"number": "INC0099999", "sys_id": "fixture-sys-id", "url": "https://example/incident"}
        if name == "notify_oncall":
            return {"sent": True}
        return fixtures.get(name, {"error": f"{name}: no data"})

    return [_wrap(s, call) for s in _load_schema()]


def gateway_tools():
    """MCP client for AgentCore Gateway. Use it as a context manager or pass it straight to Agent(tools=[...])."""
    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
    from strands.tools.mcp import MCPClient

    url = os.environ["GATEWAY_URL"]
    region = os.environ.get("AWS_REGION", "us-east-1")
    return MCPClient(lambda: aws_iam_streamablehttp_client(endpoint=url, aws_service="bedrock-agentcore",
                                                           aws_region=region))
