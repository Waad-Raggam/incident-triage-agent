"""checkout-api: a fake checkout service that logs like a real one.

Failure modes the chaos scripts can switch on:
- FAILURE_RATE env var > 0 (set by a "bad deploy")      -> errors: PaymentGatewayError
- flags.slow_dependency = true (SSM, a "feature flag") -> ~2 s latency from the inventory call
"""

import json
import os
import random
import time
import uuid

import boto3

_ssm = boto3.client("ssm")
_flags_cache: dict = {"value": {}, "at": 0.0}
FLAGS_TTL_SECONDS = 30


def _flags() -> dict:
    now = time.time()
    if now - _flags_cache["at"] > FLAGS_TTL_SECONDS:
        try:
            raw = _ssm.get_parameter(Name=os.environ["FLAGS_PARAM"])["Parameter"]["Value"]
            _flags_cache["value"] = json.loads(raw)
        except Exception as exc:  # flags must never take the service down
            log("WARN", "flag_fetch_failed", error=str(exc))
        _flags_cache["at"] = now
    return _flags_cache["value"]


def log(level: str, msg: str, **fields) -> None:
    print(json.dumps({"level": level, "msg": msg, "service": "checkout-api", **fields}))


class PaymentGatewayError(Exception):
    pass


def handler(event, context):
    order_id = str(uuid.uuid4())[:8]
    started = time.time()
    version = os.environ.get("AWS_LAMBDA_FUNCTION_VERSION", "$LATEST")

    # inventory lookup
    time.sleep(random.uniform(0.02, 0.08))
    if _flags().get("slow_dependency"):
        time.sleep(random.uniform(1.6, 2.4))
        log("WARN", "inventory_slow", order_id=order_id, dependency="inventory-db", wait_ms=2000)

    # payment
    failure_rate = float(os.environ.get("FAILURE_RATE", "0"))
    if random.random() < failure_rate:
        log("ERROR", "payment_failed", order_id=order_id, version=version,
            error="PaymentGatewayError: connection pool exhausted (max=10)")
        raise PaymentGatewayError("connection pool exhausted")

    latency_ms = int((time.time() - started) * 1000)
    log("INFO", "checkout_ok", order_id=order_id, version=version, latency_ms=latency_ms)
    return {"statusCode": 200, "body": json.dumps({"order_id": order_id})}
