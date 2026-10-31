"""Fires a burst of async invocations at checkout-api so metrics and logs always exist."""

import json
import os

import boto3

_lambda = boto3.client("lambda")


def handler(event, context):
    n = int(os.environ.get("REQUESTS_PER_MINUTE", "30"))
    for i in range(n):
        _lambda.invoke(
            FunctionName=os.environ["TARGET"],
            InvocationType="Event",
            Payload=json.dumps({"cart_items": (i % 5) + 1}).encode(),
        )
    return {"sent": n}
