"""Phase 3a: where incident state lives.

incidents table (on-demand):
  pk = INCIDENT#<id>    the incident: alarm, status, triage result, ticket, approval, timestamps
  pk = LOCK#<service>   one open incident per service -> duplicate alarms attach instead of re-triaging
  GSI status-index (status, opened_at) -> the approval poller finds AWAITING_APPROVAL items fast

Buckets: knowledge docs for the Knowledge Base (Phase 4) and ML data/artifacts (Phase 6).
"""

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_s3 as s3
from constructs import Construct

from infra.config import Config


class StateStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.table = ddb.TableV2(
            self,
            "Incidents",
            table_name=f"{cfg.project}-incidents",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            billing=ddb.Billing.on_demand(),
            time_to_live_attribute="expires_at",
            point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True),
            removal_policy=cdk.RemovalPolicy.DESTROY,
            global_secondary_indexes=[
                ddb.GlobalSecondaryIndexPropsV2(
                    index_name="status-index",
                    partition_key=ddb.Attribute(name="status", type=ddb.AttributeType.STRING),
                    sort_key=ddb.Attribute(name="opened_at", type=ddb.AttributeType.STRING),
                ),
                ddb.GlobalSecondaryIndexPropsV2(
                    index_name="service-index",
                    partition_key=ddb.Attribute(name="service", type=ddb.AttributeType.STRING),
                    sort_key=ddb.Attribute(name="opened_at", type=ddb.AttributeType.STRING),
                ),
            ],
        )

        bucket_props = dict(
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        self.knowledge_bucket = s3.Bucket(self, "KnowledgeDocs", versioned=True, **bucket_props)
        self.ml_bucket = s3.Bucket(self, "MlData", **bucket_props)

        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "KnowledgeBucket", value=self.knowledge_bucket.bucket_name)
        cdk.CfnOutput(self, "MlBucket", value=self.ml_bucket.bucket_name)
