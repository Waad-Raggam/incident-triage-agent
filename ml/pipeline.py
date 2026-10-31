"""Phase 6b: SageMaker Pipeline  train -> evaluate -> (f1 >= threshold ?) register : fail.

    python ml/pipeline.py --role-arn <SageMakerRoleArn> --bucket <MlBucket>            # upsert only
    python ml/pipeline.py --role-arn <SageMakerRoleArn> --bucket <MlBucket> --start    # upsert + run
    python ml/pipeline.py --role-arn ... --bucket ... --print                           # show JSON, no AWS writes

Uses the SageMaker Python SDK v2 (pinned <3 in ml/requirements.txt).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
import sagemaker
from sagemaker.model_metrics import MetricsSource, ModelMetrics
from sagemaker.processing import ProcessingInput, ProcessingOutput
from sagemaker.sklearn.estimator import SKLearn
from sagemaker.sklearn.model import SKLearnModel
from sagemaker.sklearn.processing import SKLearnProcessor
from sagemaker.workflow.condition_step import ConditionStep
from sagemaker.workflow.conditions import ConditionGreaterThanOrEqualTo
from sagemaker.workflow.fail_step import FailStep
from sagemaker.workflow.functions import Join, JsonGet
from sagemaker.workflow.model_step import ModelStep
from sagemaker.workflow.parameters import ParameterFloat, ParameterString
from sagemaker.workflow.pipeline import Pipeline
from sagemaker.workflow.pipeline_context import PipelineSession
from sagemaker.workflow.properties import PropertyFile
from sagemaker.workflow.steps import ProcessingStep, TrainingStep

PIPELINE_NAME = "incident-anomaly-pipeline"
MODEL_GROUP = "incident-anomaly"
SKLEARN_VERSION = "1.2-1"
SRC = str(Path(__file__).parent / "train")


def build(role_arn: str, bucket: str, region: str) -> Pipeline:
    session = PipelineSession(boto_session=boto3.Session(region_name=region), default_bucket=bucket)

    train_data = ParameterString("TrainData", default_value=f"s3://{bucket}/data/train")
    test_data = ParameterString("TestData", default_value=f"s3://{bucket}/data/test")
    min_f1 = ParameterFloat("MinF1", default_value=0.8)
    approval = ParameterString("ApprovalStatus", default_value="PendingManualApproval")

    # 1. Train
    estimator = SKLearn(
        entry_point="train.py", source_dir=SRC, framework_version=SKLEARN_VERSION, py_version="py3",
        instance_type="ml.m5.large", instance_count=1, role=role_arn, sagemaker_session=session,
        output_path=f"s3://{bucket}/models", base_job_name="anomaly-train",
    )
    train = TrainingStep(name="Train", step_args=estimator.fit({"train": train_data}))

    # 2. Evaluate on the labelled test set
    processor = SKLearnProcessor(
        framework_version=SKLEARN_VERSION, role=role_arn, instance_type="ml.m5.large", instance_count=1,
        sagemaker_session=session, base_job_name="anomaly-eval",
    )
    eval_report = PropertyFile(name="EvaluationReport", output_name="evaluation", path="evaluation.json")
    evaluate = ProcessingStep(
        name="Evaluate",
        step_args=processor.run(
            code=f"{SRC}/evaluate.py",
            inputs=[
                ProcessingInput(source=train.properties.ModelArtifacts.S3ModelArtifacts,
                                destination="/opt/ml/processing/model"),
                ProcessingInput(source=test_data, destination="/opt/ml/processing/test"),
                ProcessingInput(source=f"{SRC}/features.py", destination="/opt/ml/processing/lib"),
            ],
            outputs=[ProcessingOutput(output_name="evaluation", source="/opt/ml/processing/evaluation")],
        ),
        property_files=[eval_report],
    )

    # 3. Register in the Model Registry (a human approves before deploy)
    model = SKLearnModel(
        model_data=train.properties.ModelArtifacts.S3ModelArtifacts, entry_point="inference.py", source_dir=SRC,
        framework_version=SKLEARN_VERSION, py_version="py3", role=role_arn, sagemaker_session=session,
    )
    metrics = ModelMetrics(model_statistics=MetricsSource(
        content_type="application/json",
        s3_uri=Join(on="/", values=[
            evaluate.properties.ProcessingOutputConfig.Outputs["evaluation"].S3Output.S3Uri, "evaluation.json"]),
    ))
    register = ModelStep(
        name="Register",
        step_args=model.register(
            content_types=["application/json"], response_types=["application/json"],
            inference_instances=["ml.m5.large"], transform_instances=["ml.m5.large"],
            model_package_group_name=MODEL_GROUP, approval_status=approval, model_metrics=metrics,
        ),
    )

    gate = ConditionStep(
        name="F1GoodEnough",
        conditions=[ConditionGreaterThanOrEqualTo(
            left=JsonGet(step_name=evaluate.name, property_file=eval_report, json_path="anomaly_detection.f1"),
            right=min_f1)],
        if_steps=[register],
        else_steps=[FailStep(name="F1TooLow", error_message="Model f1 below MinF1; not registered")],
    )

    return Pipeline(name=PIPELINE_NAME, parameters=[train_data, test_data, min_f1, approval],
                    steps=[train, evaluate, gate], sagemaker_session=session)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--role-arn", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--region", default=boto3.Session().region_name or "us-east-1")
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--print", action="store_true", dest="print_only")
    a = ap.parse_args()

    p = build(a.role_arn, a.bucket, a.region)
    if a.print_only:
        print(json.dumps(json.loads(p.definition()), indent=2)[:4000])
    else:
        p.upsert(role_arn=a.role_arn)
        print(f"pipeline {PIPELINE_NAME} upserted")
        if a.start:
            print(f"started: {p.start().arn}")
    _ = sagemaker  # keep import for version pin visibility
