"""AgentCore Memory (Phase 3).

- actor_id   = the service name, so long-term facts are per service ("checkout-api's errors alarm is
               flaky on Mondays", "payment-client deploys broke it twice").
- session_id = the incident ID, so short-term events stay grouped per incident.
The semantic strategy (configured in CDK) extracts facts into /services/{actorId}/facts.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def _client():
    from bedrock_agentcore.memory import MemoryClient

    return MemoryClient(region_name=os.environ.get("AWS_REGION", "us-east-1"))


def recall(service: str, query: str, top_k: int = 5) -> list[str]:
    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        return []
    try:
        records = _client().retrieve_memories(
            memory_id=memory_id, namespace=f"/services/{service}/facts", query=query, top_k=top_k
        )
        return [r.get("content", {}).get("text", "") for r in records if r.get("content")]
    except Exception as exc:  # memory must never block triage
        log.warning("memory recall failed: %s", exc)
        return []


def remember(service: str, incident_id: str, request: str, outcome: str) -> None:
    memory_id = os.environ.get("MEMORY_ID")
    if not memory_id:
        return
    try:
        _client().create_event(
            memory_id=memory_id, actor_id=service, session_id=incident_id,
            messages=[(request[:8000], "USER"), (outcome[:8000], "ASSISTANT")],
        )
    except Exception as exc:
        log.warning("memory write failed: %s", exc)


def as_prompt_block(facts: list[str]) -> str:
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"## What you remember about this service\n{lines}\n(Use these as hints; verify with evidence.)"
