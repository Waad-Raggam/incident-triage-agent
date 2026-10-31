"""The ONLY changes this system can make, and only after a human approved them in ServiceNow.
An allow-list, not "let the LLM run commands".
"""

from __future__ import annotations

import json
import os

import boto3

ALLOWED_ACTIONS = ("rollback_deploy", "clear_feature_flag")


def previous_version(versions: list[str], current: str) -> str | None:
    older = sorted((int(v) for v in versions if v.isdigit() and int(v) < int(current)), reverse=True)
    return str(older[0]) if older else None


def rollback_deploy(function_name: str, alias: str = "live") -> dict:
    lam = boto3.client("lambda")
    current = lam.get_alias(FunctionName=function_name, Name=alias)["FunctionVersion"]
    versions = []
    for page in lam.get_paginator("list_versions_by_function").paginate(FunctionName=function_name):
        versions += [v["Version"] for v in page["Versions"]]
    target = previous_version(versions, current)
    if not target:
        raise RuntimeError(f"no version older than {current} to roll back to")
    lam.update_alias(FunctionName=function_name, Name=alias, FunctionVersion=target,
                     Description=f"rollback from {current} by incident-triage")
    return {"action": "rollback_deploy", "from_version": current, "to_version": target}


def clear_feature_flags(param_name: str) -> dict:
    ssm = boto3.client("ssm")
    flags = json.loads(ssm.get_parameter(Name=param_name)["Parameter"]["Value"])
    turned_off = [k for k, v in flags.items() if v is True]
    ssm.put_parameter(Name=param_name, Value=json.dumps({k: False for k in flags}), Type="String", Overwrite=True)
    return {"action": "clear_feature_flag", "turned_off": turned_off}


def execute(action: str) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action {action!r} is not allowed")
    service = os.environ["SERVICE_NAME"]
    if action == "rollback_deploy":
        return rollback_deploy(service)
    return clear_feature_flags(os.environ["FLAGS_PARAM"])
