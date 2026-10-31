"""Phase 2-3 (+5c): the agent on Amazon Bedrock AgentCore.

- Tools Lambda behind AgentCore Gateway (IAM auth, MCP protocol)  -> the only way the agent touches anything
- AgentCore Memory with a semantic strategy                       -> long-term facts per service
- AgentCore Runtime running the Strands agent container           -> the brain
- Bedrock Guardrail with PII filters                              -> nothing sensitive leaves in tickets
"""

import aws_cdk as cdk
import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct

from infra.config import Config
from infra.stacks.demo_app_stack import DemoAppStack
from infra.stacks.state_stack import StateStack


class AgentStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, state: StateStack,
                 demo: DemoAppStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        snow_secret = sm.Secret.from_secret_name_v2(self, "SnowSecret", cfg.servicenow_secret_name)
        slack_secret = sm.Secret.from_secret_name_v2(self, "SlackSecret", cfg.slack_secret_name)

        # Shared code (ServiceNow + Slack clients) for every Lambda in the project
        self.layer = lambda_.LayerVersion(
            self, "IntegrationsLayer", code=lambda_.Code.from_asset("lambdas/layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_13],
            compatible_architectures=[lambda_.Architecture.ARM_64],
            description="ServiceNow + Slack clients",
        )

        # ---------------------------------------------------------------- tools Lambda
        self.tools_fn = lambda_.Function(
            self, "ToolsFn",
            function_name=f"{cfg.project}-tools",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambdas/tools", exclude=["schema.json"]),
            layers=[self.layer],
            timeout=cdk.Duration.seconds(60),
            memory_size=512,
            log_retention=logs.RetentionDays.ONE_MONTH,
            environment={
                "SERVICENOW_SECRET": cfg.servicenow_secret_name,
                "SLACK_SECRET": cfg.slack_secret_name,
                "KB_ID_PARAM": cfg.kb_id_param,
                "ANOMALY_ENDPOINT": cfg.anomaly_endpoint_name,
            },
        )
        fn = self.tools_fn
        snow_secret.grant_read(fn)
        slack_secret.grant_read(fn)
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory", "cloudwatch:GetMetricData"],
            resources=["*"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["logs:StartQuery"], resources=[demo.log_group.log_group_arn]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["logs:GetQueryResults", "logs:StopQuery"], resources=["*"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["lambda:GetAlias", "lambda:ListVersionsByFunction"],
            resources=[demo.function.function_arn, f"{demo.function.function_arn}:*"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[demo.flags.parameter_arn,
                       f"arn:aws:ssm:{self.region}:{self.account}:parameter{cfg.kb_id_param}"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["sagemaker:InvokeEndpoint"],
            resources=[f"arn:aws:sagemaker:{self.region}:{self.account}:endpoint/{cfg.anomaly_endpoint_name}"]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve"],
            resources=[f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"]))

        # ---------------------------------------------------------------- Gateway (MCP, IAM auth)
        self.gateway = agentcore.Gateway(
            self, "Gateway",
            gateway_name=f"{cfg.project}-gateway",
            description="Incident triage tools",
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
        )
        self.gateway.add_lambda_target(
            "TriageTools",
            gateway_target_name="triage-tools",
            lambda_function=fn,
            tool_schema=agentcore.ToolSchema.from_local_asset("lambdas/tools/schema.json"),
        )

        # ---------------------------------------------------------------- Memory
        self.memory = agentcore.Memory(
            self, "Memory",
            memory_name="incident_triage_memory",
            description="Short-term events per incident, long-term facts per service",
            expiration_duration=cdk.Duration.days(90),
            memory_strategies=[
                agentcore.MemoryStrategy.using_semantic(name="serviceFacts",
                                                        namespaces=["/services/{actorId}/facts"]),
            ],
        )

        # ---------------------------------------------------------------- Guardrail (Phase 5c)
        pii = ["EMAIL", "PHONE", "CREDIT_DEBIT_CARD_NUMBER", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "PASSWORD"]
        guardrail = bedrock.CfnGuardrail(
            self, "Guardrail",
            name=f"{cfg.project}-pii",
            blocked_input_messaging="Input blocked by guardrail.",
            blocked_outputs_messaging="Output blocked by guardrail.",
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[bedrock.CfnGuardrail.PiiEntityConfigProperty(type=p, action="ANONYMIZE")
                                     for p in pii]),
        )
        guardrail_version = bedrock.CfnGuardrailVersion(self, "GuardrailVersion",
                                                        guardrail_identifier=guardrail.attr_guardrail_id)

        # ---------------------------------------------------------------- Runtime
        self.runtime = agentcore.Runtime(
            self, "Runtime",
            runtime_name="incident_triage_agent",
            description="Strands incident triage agent",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                "agent", platform=ecr_assets.Platform.LINUX_ARM64),
            environment_variables={
                "GATEWAY_URL": self.gateway.gateway_url,
                "MEMORY_ID": self.memory.memory_id,
                "MODEL_ID": cfg.model_id,
                "PROMPT_VERSION": cfg.prompt_version,
                "GUARDRAIL_ID": guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": guardrail_version.attr_version,
            },
        )
        self.gateway.grant_invoke(self.runtime)
        self.memory.grant_read(self.runtime)
        self.memory.grant_write(self.runtime)
        self.runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse",
                     "bedrock:ConverseStream"],
            resources=["arn:aws:bedrock:*::foundation-model/*",
                       f"arn:aws:bedrock:*:{self.account}:inference-profile/*"]))
        self.runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn]))

        cdk.CfnOutput(self, "RuntimeArn", value=self.runtime.agent_runtime_arn)
        cdk.CfnOutput(self, "GatewayUrl", value=self.gateway.gateway_url)
        cdk.CfnOutput(self, "MemoryId", value=self.memory.memory_id)
        cdk.CfnOutput(self, "ToolsFunction", value=fn.function_name)
