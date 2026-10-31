"""Phase 6c: deploy the newest APPROVED model from the registry to a serverless endpoint.

    python ml/deploy.py --role-arn <SageMakerRoleArn> --bucket <MlBucket>

Approve a model first: SageMaker Studio > Models > incident-anomaly > version > Approve
(or: aws sagemaker update-model-package --model-package-arn ... --model-approval-status Approved).
Serverless = pay per request; the first call after idle is a cold start of a few seconds.
"""

from __future__ import annotations

import argparse
import io
import tarfile
import time

import boto3

MODEL_GROUP = "incident-anomaly"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role-arn", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--endpoint", default="incident-anomaly")
    a = ap.parse_args()
    sm, s3 = boto3.client("sagemaker"), boto3.client("s3")

    pkgs = sm.list_model_packages(ModelPackageGroupName=MODEL_GROUP, ModelApprovalStatus="Approved",
                                  SortBy="CreationTime", SortOrder="Descending", MaxResults=1)["ModelPackageSummaryList"]
    if not pkgs:
        raise SystemExit("No approved model in the registry yet. Approve one first.")
    pkg_arn = pkgs[0]["ModelPackageArn"]
    stamp = time.strftime("%Y%m%d-%H%M%S")

    model_name = f"incident-anomaly-{stamp}"
    sm.create_model(ModelName=model_name, ExecutionRoleArn=a.role_arn,
                    PrimaryContainer={"ModelPackageName": pkg_arn})
    config_name = f"incident-anomaly-serverless-{stamp}"
    sm.create_endpoint_config(EndpointConfigName=config_name, ProductionVariants=[{
        "VariantName": "AllTraffic", "ModelName": model_name,
        "ServerlessConfig": {"MemorySizeInMB": 2048, "MaxConcurrency": 2},
    }])
    try:
        sm.describe_endpoint(EndpointName=a.endpoint)
        sm.update_endpoint(EndpointName=a.endpoint, EndpointConfigName=config_name)
        print(f"updating endpoint {a.endpoint} -> {pkg_arn}")
    except sm.exceptions.ClientError:
        sm.create_endpoint(EndpointName=a.endpoint, EndpointConfigName=config_name)
        print(f"creating endpoint {a.endpoint} -> {pkg_arn}")
    sm.get_waiter("endpoint_in_service").wait(EndpointName=a.endpoint)

    # Baseline stats for the drift check come from the same artifact we just deployed
    data_url = sm.describe_model_package(ModelPackageName=pkg_arn)["InferenceSpecification"]["Containers"][0][
        "ModelDataUrl"]
    src_bucket, _, key = data_url[5:].partition("/")
    tar_bytes = s3.get_object(Bucket=src_bucket, Key=key)["Body"].read()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        stats = t.extractfile("baseline_stats.json").read()
    s3.put_object(Bucket=a.bucket, Key="monitoring/baseline_stats.json", Body=stats)
    print("endpoint in service; drift baseline updated")


if __name__ == "__main__":
    main()
