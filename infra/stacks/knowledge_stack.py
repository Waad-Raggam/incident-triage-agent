"""Phase 4: a Bedrock Knowledge Base of runbooks + past incidents, stored in S3 Vectors.

Why S3 Vectors and not OpenSearch Serverless: pay per use, nothing idles at a fixed hourly cost.
Docs live in the State stack's knowledge bucket:
  runbooks/...            seeded from /knowledge/runbooks by this stack
  incidents/<service>/... written by the workflow every time an incident closes (the feedback loop)
"""

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_s3vectors as s3vectors
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from infra.config import Config
from infra.stacks.state_stack import StateStack

EMBEDDING_DIMENSIONS = 1024  # Titan Text Embeddings V2 default


class KnowledgeStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, cfg: Config, state: StateStack, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        bucket = state.knowledge_bucket

        vector_bucket = s3vectors.CfnVectorBucket(self, "VectorBucket",
                                                  vector_bucket_name=f"{cfg.project}-vectors-{self.account}")
        index = s3vectors.CfnIndex(
            self, "Index",
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            index_name="past-incidents",
            data_type="float32",
            dimension=EMBEDDING_DIMENSIONS,
            distance_metric="cosine",
            # Bedrock stores chunk text + metadata here; keep them non-filterable to stay under filter limits
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]),
        )

        embedding_arn = f"arn:aws:bedrock:{self.region}::foundation-model/{cfg.embedding_model_id}"
        role = iam.Role(self, "KbRole", assumed_by=iam.ServicePrincipal(
            "bedrock.amazonaws.com", conditions={"StringEquals": {"aws:SourceAccount": self.account}}))
        role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[embedding_arn]))
        bucket.grant_read(role)
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
                     "s3vectors:QueryVectors", "s3vectors:GetIndex", "s3vectors:ListVectors"],
            resources=[index.attr_index_arn]))

        kb = bedrock.CfnKnowledgeBase(
            self, "KnowledgeBase",
            name=f"{cfg.project}-past-incidents",
            description="Runbooks and resolved incidents for the triage agent",
            role_arn=role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_arn),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=index.attr_index_arn),
            ),
        )
        kb.node.add_dependency(role)

        data_source = bedrock.CfnDataSource(
            self, "DataSource",
            knowledge_base_id=kb.attr_knowledge_base_id,
            name="incidents-and-runbooks",
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=bucket.bucket_arn),  # whole bucket: runbooks/ + incidents/
            ),
        )

        # Seed: runbooks + a few historical incidents so retrieval has something on day one
        s3deploy.BucketDeployment(self, "SeedDocs", destination_bucket=bucket,
                                  sources=[s3deploy.Source.asset("knowledge")], prune=False)

        ssm.StringParameter(self, "KbIdParam", parameter_name=cfg.kb_id_param,
                            string_value=kb.attr_knowledge_base_id)
        ssm.StringParameter(self, "KbDsParam", parameter_name=f"/{cfg.project}/knowledge-data-source-id",
                            string_value=data_source.attr_data_source_id)

        cdk.CfnOutput(self, "KnowledgeBaseId", value=kb.attr_knowledge_base_id)
        cdk.CfnOutput(self, "DataSourceId", value=data_source.attr_data_source_id)
