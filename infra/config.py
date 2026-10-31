"""Reads project settings from cdk.json context so every stack uses the same values."""

from dataclasses import dataclass

from constructs import Construct


@dataclass(frozen=True)
class Config:
    project: str
    service_name: str
    region: str
    alert_email: str
    monthly_budget_usd: int
    github_repo: str
    create_github_oidc_provider: bool
    model_id: str
    judge_model_id: str
    embedding_model_id: str
    prompt_version: str
    anomaly_endpoint_name: str
    servicenow_secret_name: str
    slack_secret_name: str

    # SSM parameter names used to wire later phases in without stack dependencies
    @property
    def kb_id_param(self) -> str:
        return f"/{self.project}/knowledge-base-id"

    @property
    def flags_param(self) -> str:
        return f"/{self.service_name}/flags"

    @staticmethod
    def load(scope: Construct) -> "Config":
        g = scope.node.try_get_context
        return Config(
            project=g("project"),
            service_name=g("service_name"),
            region=g("region"),
            alert_email=g("alert_email"),
            monthly_budget_usd=int(g("monthly_budget_usd")),
            github_repo=g("github_repo"),
            create_github_oidc_provider=str(g("create_github_oidc_provider")).lower() == "true",
            model_id=g("model_id"),
            judge_model_id=g("judge_model_id"),
            embedding_model_id=g("embedding_model_id"),
            prompt_version=g("prompt_version"),
            anomaly_endpoint_name=g("anomaly_endpoint_name"),
            servicenow_secret_name=g("servicenow_secret_name"),
            slack_secret_name=g("slack_secret_name"),
        )
