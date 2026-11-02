# Phase 1a result: the agent diagnoses its first real incident

Date: 2026-11-02 · Branch: `phase-1a/agent-local` · Agent ran locally (`agent/run_local.py --no-tickets`)

## The incident

A bad deploy (`payment-client v2.3 (connection pool size change)`) was shipped twice in a row, as
versions 4 and 5, so a naive "roll back one version" would land on another broken version.
The last healthy version was 3.

| Time (UTC+3) | Event |
| --- | --- |
| 11:55:49 | Bad deploy, version 4 |
| 11:56:16 | Bad deploy again, version 5 |
| 11:58:20 | `checkout-api-errors` alarm fires (+2 min 31 s) |
| ~11:59 | Agent started |
| +32.5 s | Agent returns diagnosis |
| 12:02:56 | Healthy version deployed (reset) |

## What the agent concluded

- **Root cause:** version 5 (`payment-client v2.3`) exhausts the payment gateway connection pool (max=10).
  It also noticed the same change shipped on 2026-10-31 as version 2 and was rolled back.
- **Evidence it quoted:** `PaymentGatewayError: connection pool exhausted (max=10)` on version 5;
  errors 0 → 15 → 19 → 22 → 25 per minute; the deploy time and description; anomaly score 22.
- **Suggested fix:** roll back from version 5 to **version 3, the last known healthy version**.
- **Confidence:** 0.95
- **Tools used:** get_alarm, get_metric_series, score_anomaly, query_logs, get_recent_deploys,
  get_feature_flags, search_past_incidents

## Numbers

| | Phase 0 (human) | Phase 1a (agent) |
| --- | --- | --- |
| Finding the cause | 11 min 58 s | **32.5 s** (~22× faster) |
| Tokens | n/a | 21,985 in / 1,730 out |
| Approx. model cost | n/a | ~$0.09 (Claude Sonnet 4.5 on-demand pricing) |

## Bug found by this run

`lambdas/workflow/remediation.py` rolled back to the *previous* version (5 → 4), which here was also broken.
The agent's suggestion (5 → 3) was right. Fix in this branch:

- `TriageResult` gets a `rollback_to_version` field and the prompt asks for the last **healthy** version.
- `choose_rollback_target()` uses the agent's suggestion only if it is a real, older version;
  otherwise it falls back to the previous version. The change request in ServiceNow shows the target.
- 5 new tests cover the Phase 1a scenario and invalid suggestions.

## Raw output

```json
{
  "verdict": "actionable",
  "root_cause": "Version 5 deployed at 08:56:13 with \"payment-client v2.3 (connection pool size change)\" is causing payment gateway connection pool exhaustion (max=10). This same change was previously deployed as version 2 on 2026-10-31, rolled back to version 3 \"reset to healthy\", and is now causing identical failures.",
  "suggested_fix": "Rollback live alias from version 5 to version 3 (last known healthy version)",
  "remediation_action": "rollback_deploy",
  "confidence": 0.95,
  "seconds": 32.5,
  "usage": {"inputTokens": 21985, "outputTokens": 1730, "totalTokens": 23715}
}
```

Note: the agent mixed UTC and local time in one sentence ("08:56:13" is 11:56:13 UTC+3). Worth tightening
in the prompt later.
