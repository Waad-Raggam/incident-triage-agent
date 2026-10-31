"""Phase 2c + 3a + 5: alarm -> dedupe -> agent -> ServiceNow approval -> remediation -> verify -> learn.

Mirrors the triage-flow diagram in the design doc.
"""

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from infra.config import Config
from infra.stacks.agent_stack import AgentStack
from infra.stacks.demo_app_stack import DemoAppStack
from infra.stacks.state_stack import StateStack


class WorkflowStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, state: StateStack, agent: AgentStack,
                 demo: DemoAppStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        snow_secret = sm.Secret.from_secret_name_v2(self, "SnowSecret", cfg.servicenow_secret_name)
        slack_secret = sm.Secret.from_secret_name_v2(self, "SlackSecret", cfg.slack_secret_name)
        layer = lambda_.LayerVersion(
            self, "IntegrationsLayer", code=lambda_.Code.from_asset("lambdas/layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
            compatible_architectures=[lambda_.Architecture.ARM_64],
        )
        env = {
            "TABLE": state.table.table_name,
            "SERVICE_NAME": cfg.service_name,
            "FLAGS_PARAM": cfg.flags_param,
            "RUNTIME_ARN": agent.runtime.agent_runtime_arn,
            "SERVICENOW_SECRET": cfg.servicenow_secret_name,
            "SLACK_SECRET": cfg.slack_secret_name,
            "KNOWLEDGE_BUCKET": state.knowledge_bucket.bucket_name,
            "KB_ID_PARAM": cfg.kb_id_param,
            "KB_DS_PARAM": f"/{cfg.project}/knowledge-data-source-id",
        }

        def fn(name: str, handler: str, timeout: int = 60) -> lambda_.Function:
            f = lambda_.Function(
                self, f"{name}Fn",
                function_name=f"{cfg.project}-{name.lower()}",
                runtime=lambda_.Runtime.PYTHON_3_13,
                architecture=lambda_.Architecture.ARM_64,
                handler=handler,
                code=lambda_.Code.from_asset("lambdas/workflow"),
                layers=[layer],
                timeout=cdk.Duration.seconds(timeout),
                memory_size=256,
                environment=env,
                log_retention=logs.RetentionDays.ONE_MONTH,
            )
            state.table.grant_read_write_data(f)
            snow_secret.grant_read(f)
            slack_secret.grant_read(f)
            f.add_to_role_policy(iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"]))
            return f

        dedupe_fn = fn("Dedupe", "steps.dedupe")
        agent_fn = fn("RunAgent", "steps.run_agent", timeout=900)
        agent.runtime.grant_invoke_runtime(agent_fn)
        approval_fn = fn("RequestApproval", "steps.request_approval")
        remediate_fn = fn("Remediate", "steps.remediate")
        remediate_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["lambda:GetAlias", "lambda:UpdateAlias", "lambda:ListVersionsByFunction"],
            resources=[demo.function.function_arn, f"{demo.function.function_arn}:*"]))
        demo.flags.grant_read(remediate_fn)
        demo.flags.grant_write(remediate_fn)
        verify_fn = fn("Verify", "steps.verify")
        verify_fn.add_to_role_policy(iam.PolicyStatement(actions=["cloudwatch:DescribeAlarms"], resources=["*"]))
        close_fn = fn("Close", "steps.close_resolved", timeout=120)
        noise_fn = fn("CloseNoise", "steps.close_noise")
        handoff_fn = fn("HandOff", "steps.hand_off")
        poller_fn = fn("ApprovalPoller", "poller.handler", timeout=120)
        for f in (close_fn, poller_fn):  # both can "close and learn"
            state.knowledge_bucket.grant_put(f)
            f.add_to_role_policy(iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{self.region}:{self.account}:parameter/{cfg.project}/*"]))
            f.add_to_role_policy(iam.PolicyStatement(
                actions=["bedrock:StartIngestionJob"],
                resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"]))

        # ---------------------------------------------------------------- state machine
        def invoke(id_: str, f, result_path: str | None, payload: dict | None = None):
            return tasks.LambdaInvoke(
                self, id_, lambda_function=f, payload_response_only=True, result_path=result_path,
                payload=sfn.TaskInput.from_object(payload) if payload else None,
                retry_on_service_exceptions=True,
            )

        inc_id = {"incident_id.$": "$.incident_id"}

        def handoff(id_: str, reason: str):
            return invoke(id_, handoff_fn, "$.handoff", {**inc_id, "reason": reason}).next(
                sfn.Succeed(self, f"{id_}Done", comment="Human takes over; poller closes the loop"))

        dedupe = invoke("Dedupe", dedupe_fn, "$")  # replaces the raw event with {incident_id, duplicate}
        run_agent = invoke("RunAgent", agent_fn, "$.triage", inc_id)
        run_agent.add_catch(handoff("HandOffAgentFailed", "agent failed: needs human triage"),
                            result_path="$.error")

        request_approval = tasks.LambdaInvoke(
            self, "RequestApprovalInServiceNow",
            lambda_function=approval_fn,
            integration_pattern=sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
            payload=sfn.TaskInput.from_object({**inc_id, "task_token": sfn.JsonPath.task_token}),
            result_path="$.approval",
            task_timeout=sfn.Timeout.duration(cdk.Duration.hours(24)),
        )
        request_approval.add_catch(handoff("HandOffRejected", "fix rejected in ServiceNow"),
                                   errors=["Rejected"], result_path="$.error")
        request_approval.add_catch(handoff("HandOffNoApproval", "no approval within 24h"),
                                   result_path="$.error")

        remediate = invoke("Remediate", remediate_fn, "$.remediation", inc_id)
        remediate.add_catch(handoff("HandOffRemediationFailed", "remediation failed"), result_path="$.error")
        wait = sfn.Wait(self, "LetMetricsSettle", time=sfn.WaitTime.duration(cdk.Duration.minutes(4)))
        verify = invoke("Verify", verify_fn, "$.verify", inc_id)
        close = invoke("CloseAndLearn", close_fn, "$.close", inc_id).next(sfn.Succeed(self, "Resolved"))

        definition = dedupe.next(
            sfn.Choice(self, "AlreadyOpen?")
            .when(sfn.Condition.boolean_equals("$.duplicate", True),
                  sfn.Succeed(self, "AttachedToOpenIncident"))
            .otherwise(
                run_agent.next(
                    sfn.Choice(self, "Verdict?")
                    .when(sfn.Condition.string_equals("$.triage.verdict", "noise"),
                          invoke("CloseAsNoise", noise_fn, "$.close", inc_id).next(sfn.Succeed(self, "Noise")))
                    .when(sfn.Condition.string_equals("$.triage.remediation_action", "none"),
                          handoff("HandOffNoSafeFix", "no safe automated fix"))
                    .otherwise(
                        request_approval.next(remediate).next(wait).next(verify).next(
                            sfn.Choice(self, "Recovered?")
                            .when(sfn.Condition.boolean_equals("$.verify.recovered", True), close)
                            .otherwise(handoff("HandOffNotRecovered", "alarm still firing after remediation"))
                        )
                    )
                )
            )
        )

        self.state_machine = sfn.StateMachine(
            self, "TriageWorkflow",
            state_machine_name=f"{cfg.project}-workflow",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=cdk.Duration.hours(26),
            tracing_enabled=True,
            logs=sfn.LogOptions(
                destination=logs.LogGroup(self, "WorkflowLogs", retention=logs.RetentionDays.ONE_MONTH,
                                          removal_policy=cdk.RemovalPolicy.DESTROY),
                level=sfn.LogLevel.ERROR),
        )
        self.state_machine.grant_task_response(poller_fn)

        # ---------------------------------------------------------------- triggers
        events.Rule(
            self, "AlarmToWorkflow",
            description=f"Any {cfg.service_name}-* alarm entering ALARM starts a triage",
            event_pattern=events.EventPattern(
                source=["aws.cloudwatch"],
                detail_type=["CloudWatch Alarm State Change"],
                detail={"alarmName": [{"prefix": f"{cfg.service_name}-"}], "state": {"value": ["ALARM"]}},
            ),
            targets=[targets.SfnStateMachine(self.state_machine)],
        )
        events.Rule(
            self, "PollApprovals", schedule=events.Schedule.rate(cdk.Duration.minutes(1)),
            targets=[targets.LambdaFunction(poller_fn)],
        )

        self.agent_fn = agent_fn
        self.failed_metric: cw.IMetric = self.state_machine.metric_failed()
        cdk.CfnOutput(self, "StateMachineArn", value=self.state_machine.state_machine_arn)
