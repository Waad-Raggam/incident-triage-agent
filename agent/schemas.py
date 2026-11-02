from typing import Literal

from pydantic import BaseModel, Field

RemediationAction = Literal["rollback_deploy", "clear_feature_flag", "none"]


class TriageResult(BaseModel):
    """What the agent hands back to the workflow. Stored on the incident item in DynamoDB."""

    verdict: Literal["actionable", "noise"] = Field(description="noise = not a real anomaly, no ticket")
    root_cause: str = Field(description="One or two sentences, only claims backed by evidence")
    evidence: list[str] = Field(description="Quoted facts from tool outputs: log lines, metric values, versions")
    similar_incidents: list[str] = Field(default_factory=list, description="Past incident IDs that matched")
    suggested_fix: str = Field(description="What a human should do, in one sentence")
    remediation_action: RemediationAction
    rollback_to_version: str = Field(
        default="", description="For rollback_deploy: the last known HEALTHY version number, e.g. '3'")
    confidence: float = Field(ge=0, le=1)
    ticket_number: str = Field(default="", description="ServiceNow incident number, e.g. INC0010001")
    ticket_sys_id: str = Field(default="", description="ServiceNow sys_id of the incident")


FALLBACK = TriageResult(
    verdict="actionable",
    root_cause="Automated triage did not finish; needs human triage.",
    evidence=[],
    suggested_fix="Investigate manually.",
    remediation_action="none",
    confidence=0.0,
)
