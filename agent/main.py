"""AgentCore Runtime entrypoint (Phase 2). Tools come from AgentCore Gateway.

Payload: {"incident_id": "...", "service": "checkout-api", "alarm": {...EventBridge alarm event detail...}}
"""

import logging

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from toolkit import gateway_tools
from triage import run_triage

logging.basicConfig(level=logging.INFO)
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    gateway = gateway_tools()
    with gateway:
        tools = gateway.list_tools_sync()
        run = run_triage(payload.get("alarm", {}), payload["incident_id"], payload.get("service", "checkout-api"),
                         tools)
    return run.to_dict()


if __name__ == "__main__":
    app.run()
