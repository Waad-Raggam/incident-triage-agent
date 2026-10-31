import json
import os

import boto3

SERVICE = os.environ.get("SERVICE_NAME", "checkout-api")
FLAGS_PARAM = f"/{SERVICE}/flags"
ALIAS = "live"

lam = boto3.client("lambda")
ssm = boto3.client("ssm")


def deploy(failure_rate: float, description: str) -> str:
    """Simulates a deploy: change config, publish a new version, point `live` at it."""
    cfg = lam.get_function_configuration(FunctionName=SERVICE)
    env = cfg.get("Environment", {}).get("Variables", {})
    env["FAILURE_RATE"] = str(failure_rate)
    lam.update_function_configuration(FunctionName=SERVICE, Environment={"Variables": env})
    lam.get_waiter("function_updated_v2").wait(FunctionName=SERVICE)
    version = lam.publish_version(FunctionName=SERVICE, Description=description)["Version"]
    lam.update_alias(FunctionName=SERVICE, Name=ALIAS, FunctionVersion=version, Description=description)
    return version


def set_flags(**flags) -> None:
    current = json.loads(ssm.get_parameter(Name=FLAGS_PARAM)["Parameter"]["Value"])
    current.update(flags)
    ssm.put_parameter(Name=FLAGS_PARAM, Value=json.dumps(current), Type="String", Overwrite=True)
