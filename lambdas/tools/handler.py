"""AgentCore Gateway Lambda target. Gateway passes the tool arguments as the event and the
tool name as `<target>___<tool>` in the client context."""

import json

from triage_tools import call_tool


def handler(event, context):
    full_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool = full_name.split("___", 1)[-1]
    result = call_tool(tool, event if isinstance(event, dict) else {})
    print(json.dumps({"tool": tool, "ok": "error" not in result}))
    return result
