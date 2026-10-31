"""Phase 0a: a budget alert (so a forgotten endpoint never surprises you) and a GitHub Actions OIDC role."""

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from constructs import Construct

from infra.config import Config


class FoundationStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Budget: email at 50%, 80% and 100% (forecasted) of the monthly limit
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"{cfg.project}-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=cfg.monthly_budget_usd, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type=kind,
                        threshold=pct,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(address=cfg.alert_email, subscription_type="EMAIL")],
                )
                for kind, pct in (("ACTUAL", 50), ("ACTUAL", 80), ("FORECASTED", 100))
            ],
        )

        # --- GitHub Actions OIDC: no long-lived AWS keys in GitHub
        provider_url = "https://token.actions.githubusercontent.com"
        if cfg.create_github_oidc_provider:
            provider = iam.OpenIdConnectProvider(
                self, "GitHubOidc", url=provider_url, client_ids=["sts.amazonaws.com"]
            )
            provider_arn = provider.open_id_connect_provider_arn
        else:  # the account already has one (only one per URL is allowed)
            provider_arn = f"arn:aws:iam::{self.account}:oidc-provider/token.actions.githubusercontent.com"

        role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name=f"{cfg.project}-github-actions",
            max_session_duration=cdk.Duration.hours(2),
            assumed_by=iam.FederatedPrincipal(
                provider_arn,
                conditions={
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{cfg.github_repo}:*"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        # cdk deploy works by assuming the bootstrap roles
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-*"],
            )
        )
        # Agent evals call Bedrock and publish the eval score as a metric
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse",
                         "bedrock:ConverseStream", "cloudwatch:PutMetricData"],
                resources=["*"],
            )
        )
        # ML pipeline workflow (Phase 6): upsert + start the SageMaker pipeline
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sagemaker:*Pipeline*", "sagemaker:Describe*", "sagemaker:List*",
                         "sagemaker:AddTags", "s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=[f"arn:aws:iam::{self.account}:role/{cfg.project}-sagemaker"],
            )
        )

        cdk.CfnOutput(self, "GitHubActionsRoleArn", value=role.role_arn)
