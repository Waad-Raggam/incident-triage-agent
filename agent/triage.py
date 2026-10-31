"""The triage agent itself: one function used by the cloud runtime, the local CLI and the evals."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import memory
from schemas import FALLBACK, TriageResult
from strands import Agent
from strands.models import BedrockModel

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).parent / "prompts"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
LIMITS = {"turns": 16, "total_tokens": 250_000}


@dataclass
class TriageRun:
    result: TriageResult
    prompt_version: str
    model_id: str
    seconds: float
    usage: dict = field(default_factory=dict)
    tools_called: list[str] = field(default_factory=list)
    stop_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "result": self.result.model_dump(),
            "prompt_version": self.prompt_version,
            "model_id": self.model_id,
            "seconds": round(self.seconds, 1),
            "usage": self.usage,
            "tools_called": self.tools_called,
            "stop_reason": self.stop_reason,
        }


def load_prompt(version: str, memory_context: str = "") -> str:
    return (PROMPTS / f"{version}.md").read_text().replace("{memory_context}", memory_context)


def build_model(model_id: str | None = None) -> BedrockModel:
    cfg: dict = {"model_id": model_id or os.environ.get("MODEL_ID", DEFAULT_MODEL), "max_tokens": 4096,
                 "temperature": 0.1}
    if os.environ.get("GUARDRAIL_ID"):  # Phase 5: PII filtering on everything the model sees and writes
        cfg.update(guardrail_id=os.environ["GUARDRAIL_ID"],
                   guardrail_version=os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
                   guardrail_trace="enabled")
    return BedrockModel(**cfg)


def request_text(alarm: dict, incident_id: str, service: str) -> str:
    return (
        f"Incident {incident_id}. Service: {service}. Log group: /aws/lambda/{service}. "
        f"Function: {service} (alias live).\n"
        f"Alarm event:\n{json.dumps(alarm, default=str)[:4000]}"
    )


def run_triage(alarm: dict, incident_id: str, service: str, tools: list, *, prompt_version: str | None = None,
               model_id: str | None = None, use_memory: bool = True, model=None) -> TriageRun:
    prompt_version = prompt_version or os.environ.get("PROMPT_VERSION", "triage-v1")
    model = model or build_model(model_id)
    req = request_text(alarm, incident_id, service)
    facts = memory.recall(service, req) if use_memory else []

    agent = Agent(model=model, tools=tools, system_prompt=load_prompt(prompt_version, memory.as_prompt_block(facts)),
                  callback_handler=None, trace_attributes={"incident.id": incident_id, "service": service,
                                                           "prompt.version": prompt_version})
    started = time.time()
    stop_reason, usage, tools_called = "", {}, []
    try:
        out = agent(req, structured_output_model=TriageResult, limits=LIMITS)
        stop_reason = str(out.stop_reason)
        usage = dict(out.metrics.accumulated_usage)
        tools_called = [name.split("___")[-1] for name in out.metrics.tool_metrics]
        result = out.structured_output or FALLBACK
    except Exception as exc:
        log.exception("triage failed")
        stop_reason = f"error: {type(exc).__name__}: {exc}"[:300]
        result = FALLBACK

    run = TriageRun(result=result, prompt_version=prompt_version, model_id=model.get_config().get("model_id", "custom"),
                    seconds=time.time() - started, usage=usage, tools_called=tools_called, stop_reason=stop_reason)
    if use_memory:
        memory.remember(service, incident_id, req, json.dumps(run.result.model_dump()))
    return run
