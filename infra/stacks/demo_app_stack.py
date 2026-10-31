"""Phase 0b: `checkout-api`, a tiny Lambda service with alarms, plus steady fake traffic.

The chaos scripts in /chaos break it on purpose (bad deploy, slow dependency) so the agent
has real incidents to triage.
"""

import json

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from infra.config import Config


class DemoAppStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        svc = cfg.service_name

        self.flags = ssm.StringParameter(
            self,
            "Flags",
            parameter_name=cfg.flags_param,
            string_value=json.dumps({"slow_dependency": False}),
            description="Feature flags for the demo app. chaos/slow_dependency.py flips one on.",
        )

        self.log_group = logs.LogGroup(
            self,
            "AppLogs",
            log_group_name=f"/aws/lambda/{svc}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        self.function = lambda_.Function(
            self,
            "CheckoutApi",
            function_name=svc,
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="app.handler",
            code=lambda_.Code.from_asset("lambdas/demo_app"),
            timeout=cdk.Duration.seconds(10),
            memory_size=256,
            log_group=self.log_group,
            environment={"FAILURE_RATE": "0.0", "FLAGS_PARAM": cfg.flags_param},
            description="Demo checkout service. Healthy version.",
        )
        self.flags.grant_read(self.function)

        # Traffic goes to the `live` alias, so a "deploy" = publish a version + move the alias
        self.alias = lambda_.Alias(self, "Live", alias_name="live", version=self.function.current_version)

        # --- Steady traffic: every minute, fire a burst of async invocations at the alias
        traffic = lambda_.Function(
            self,
            "TrafficGenerator",
            function_name=f"{svc}-traffic",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="traffic.handler",
            code=lambda_.Code.from_asset("lambdas/traffic"),
            timeout=cdk.Duration.seconds(30),
            environment={"TARGET": self.alias.function_arn, "REQUESTS_PER_MINUTE": "30"},
            log_retention=logs.RetentionDays.ONE_DAY,
        )
        self.alias.grant_invoke(traffic)
        self.traffic_rule = events.Rule(
            self, "EveryMinute", schedule=events.Schedule.rate(cdk.Duration.minutes(1)),
            targets=[targets.LambdaFunction(traffic)],
        )

        # --- Alarms. Names start with the service name; the EventBridge rule in Phase 2 matches that prefix.
        self.error_alarm = cw.Alarm(
            self,
            "ErrorsAlarm",
            alarm_name=f"{svc}-errors",
            alarm_description=f"{svc}: too many failed checkouts",
            metric=self.alias.metric_errors(period=cdk.Duration.minutes(1), statistic="Sum"),
            threshold=5,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        self.latency_alarm = cw.Alarm(
            self,
            "LatencyAlarm",
            alarm_name=f"{svc}-latency-p99",
            alarm_description=f"{svc}: p99 latency above 1.5 s",
            metric=self.alias.metric_duration(period=cdk.Duration.minutes(1), statistic="p99"),
            threshold=1500,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        cdk.CfnOutput(self, "FunctionName", value=self.function.function_name)
        cdk.CfnOutput(self, "AliasArn", value=self.alias.function_arn)
        cdk.CfnOutput(self, "LogGroup", value=self.log_group.log_group_name)
