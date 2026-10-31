"""Chaos #1: ship a "bad deploy". About half of checkouts fail with PaymentGatewayError.

Expected: `checkout-api-errors` goes into ALARM within ~3 minutes.
Correct fix the agent should find: roll back the `live` alias to the previous version.
"""

from common import deploy

if __name__ == "__main__":
    v = deploy(0.5, "deploy: payment-client v2.3 (connection pool size change)")
    print(f"Published version {v} and moved alias 'live' to it. Watch the errors alarm.")
