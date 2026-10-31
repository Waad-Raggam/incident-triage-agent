# Runbook: checkout-api latency alarm (`checkout-api-latency-p99`)

Owner: payments team. Severity: medium (checkouts are slow but succeed).

## Likely causes, most common first
1. **Slow dependency behind a feature flag.** `inventory_slow` WARN lines with `dependency=inventory-db`
   and `wait_ms` around 2000, starting right after a flag changed.
   Fix: turn the flag off (`clear_feature_flag`).
2. **Cold starts after a deploy.** Short p99 spike that clears by itself in a few minutes. Usually noise.
3. **Large carts.** Latency correlates with cart size; no fix needed, consider raising the threshold.

## Checks
- When did the feature flags last change? (`get_feature_flags`)
- Is the latency spread over many minutes (real) or one datapoint (noise)? (`score_anomaly`)
