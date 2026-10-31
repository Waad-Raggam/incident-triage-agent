# Runbook: checkout-api errors alarm (`checkout-api-errors`)

Owner: payments team. Severity: high (customers cannot pay).

## Likely causes, most common first
1. **Bad deploy.** A new version of `checkout-api` was published and the `live` alias moved to it.
   Signature: `payment_failed` log lines with `PaymentGatewayError`, all from the newest `version`.
   Fix: roll back the `live` alias to the previous version (`rollback_deploy`).
2. **Payment provider outage.** Errors across all versions, no recent deploy.
   Fix: none automated. Page payments on-call and check the provider status page.
3. **Throttling.** `Throttles` metric rising with errors. Fix: raise reserved concurrency (manual).

## Checks
- Did the alias change in the 15 minutes before the alarm? (`get_recent_deploys`)
- Do the error log lines all carry the same `version`?
