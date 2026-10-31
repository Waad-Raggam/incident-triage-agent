"""Phase 6: everything the anomaly model's MLOps loop needs that isn't the pipeline itself.

- SageMaker execution role (training, processing, endpoint)
- Model Registry group `incident-anomaly`
- Daily drift check Lambda -> CloudWatch metric -> retrain when PSI > 0.25
The pipeline definition is code (ml/pipeline.py) and is upserted from CI.
"""

import aws_cdk as cdk
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sagemaker as sagemaker
from constructs import Construct

from infra.config import Config
from infra.stacks.demo_app_stack import DemoAppStack
from infra.stacks.state_stack import StateStack

PIPELINE_NAME = "incident-anomaly-pipeline"


class MlStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, state: StateStack, demo: DemoAppStack,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        role = iam.Role(
            self, "SageMakerRole", role_name=f"{cfg.project}-sagemaker",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFullAccess")],
        )
        state.ml_bucket.grant_read_write(role)

        sagemaker.CfnModelPackageGroup(
            self, "ModelGroup", model_package_group_name="incident-anomaly",
            model_package_group_description="Anomaly scores for incident triage metrics",
        )

        drift = lambda_.Function(
            self, "DriftCheck",
            function_name=f"{cfg.project}-drift-check",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="drift.handler",
            code=lambda_.Code.from_asset("ml/train", exclude=["train.py", "evaluate.py", "inference.py"]),
            timeout=cdk.Duration.minutes(2),
            environment={"ML_BUCKET": state.ml_bucket.bucket_name, "SERVICE_NAME": cfg.service_name,
                         "PIPELINE_NAME": PIPELINE_NAME},
            log_retention=logs.RetentionDays.ONE_MONTH,
        )
        state.ml_bucket.grant_read_write(drift)
        drift.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:GetMetricData", "cloudwatch:PutMetricData"], resources=["*"]))
        drift.add_to_role_policy(iam.PolicyStatement(
            actions=["sagemaker:StartPipelineExecution", "sagemaker:ListPipelineExecutions"],
            resources=[f"arn:aws:sagemaker:{self.region}:{self.account}:pipeline/{PIPELINE_NAME}"]))
        events.Rule(self, "Daily", schedule=events.Schedule.cron(minute="0", hour="3"),
                    targets=[targets.LambdaFunction(drift)])

        cdk.CfnOutput(self, "SageMakerRoleArn", value=role.role_arn)
        cdk.CfnOutput(self, "MlBucket", value=state.ml_bucket.bucket_name)
