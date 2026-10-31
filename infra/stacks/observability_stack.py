"""Phase 8: one CloudWatch dashboard for the app, the agent, the workflow, the evals and the model.

Agent traces (each model call and tool call, with tokens and latency) are in CloudWatch
> GenAI Observability, sent by AgentCore Observability from the runtime container.
"""

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cw
from constructs import Construct

from infra.config import Config
from infra.stacks.agent_stack import AgentStack
from infra.stacks.demo_app_stack import DemoAppStack
from infra.stacks.workflow_stack import WorkflowStack

NS = "IncidentTriage"


def m(name: str, stat: str = "Sum", period_min: int = 60, label: str | None = None, **dims) -> cw.Metric:
    return cw.Metric(namespace=NS, metric_name=name, statistic=stat, dimensions_map=dims or None,
                     period=cdk.Duration.minutes(period_min), label=label or name)


class ObservabilityStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, demo: DemoAppStack, agent: AgentStack,
                 workflow: WorkflowStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        d = cw.Dashboard(self, "Dashboard", dashboard_name=f"{cfg.project}")
        sm = workflow.state_machine
        d.add_widgets(
            cw.TextWidget(markdown=f"# Incident triage: {cfg.service_name}\nAlarms → agent → approval → fix → learn",
                          width=24, height=2),
        )
        d.add_widgets(
            cw.AlarmStatusWidget(title="Service alarms", alarms=[demo.error_alarm, demo.latency_alarm], width=8),
            cw.GraphWidget(title="checkout-api errors & p99 latency", width=16,
                           left=[demo.alias.metric_errors(period=cdk.Duration.minutes(1))],
                           right=[demo.alias.metric_duration(period=cdk.Duration.minutes(1), statistic="p99")]),
        )
        d.add_widgets(
            cw.GraphWidget(title="Triage outcomes", width=8, stacked=True, left=[
                m("Triaged", verdict="actionable", label="actionable"), m("Triaged", verdict="noise", label="noise"),
                m("DuplicateAlarm", service=cfg.service_name, label="duplicates")]),
            cw.GraphWidget(title="Human decisions on suggested fixes", width=8, left=[
                m("FixApproved", label="approved"), m("FixRejected", label="rejected")]),
            cw.GraphWidget(title="Resolved by path", width=8, left=[
                m("Resolved", path="automated", label="automated"), m("Resolved", path="manual", label="manual")]),
        )
        d.add_widgets(
            cw.GraphWidget(title="Triage time (s)", width=8, left=[m("TriageSeconds", "Average"),
                                                                  m("TriageSeconds", "Maximum")]),
            cw.GraphWidget(title="Tokens per triage", width=8, left=[m("TotalTokens", "Average")]),
            cw.GraphWidget(title="Time to resolve (s)", width=8, left=[
                m("TimeToResolve", "Average", path="automated", label="automated"),
                m("TimeToResolve", "Average", path="manual", label="manual")]),
        )
        d.add_widgets(
            cw.GraphWidget(title="Workflow executions", width=8, left=[
                sm.metric_started(), sm.metric_succeeded(), sm.metric_failed()]),
            cw.GraphWidget(title="Agent eval score (CI)", width=8, left=[m("EvalScore", "Average", period_min=1440)]),
            cw.GraphWidget(title="Anomaly model drift (PSI)", width=8, left=[
                m("AnomalyModelDriftPSI", "Maximum", period_min=1440)],
                left_annotations=[cw.HorizontalAnnotation(value=0.25, label="retrain")]),
        )
        d.add_widgets(
            cw.GraphWidget(title="Tools Lambda errors / invocations", width=12, left=[
                agent.tools_fn.metric_invocations(), agent.tools_fn.metric_errors()]),
            cw.GraphWidget(title="RunAgent Lambda duration", width=12, left=[
                workflow.agent_fn.metric_duration(statistic="Average")]),
        )
        cw.Alarm(self, "WorkflowFailures", alarm_name=f"{cfg.project}-workflow-failed",
                 metric=sm.metric_failed(period=cdk.Duration.minutes(5)), threshold=1, evaluation_periods=1,
                 treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                 alarm_description="The triage workflow itself failed - check Step Functions")
