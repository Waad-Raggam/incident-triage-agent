# Phase 1b result: the agent opens a real ServiceNow incident

Date: 2026-11-02 · Branch: `phase-1b/servicenow-tickets` · Agent ran locally (`agent/run_local.py`)

## What happened

1. Bad deploy shipped (version 8), `checkout-api-errors` alarm fired.
2. The agent investigated, then opened **INC0010001** in ServiceNow by itself:
   *"checkout-api: payment failures due to connection pool exhaustion in version 8"*
   - Urgency **1 - High**, Priority **1 - Critical**, chosen by the agent
   - Description: summary, evidence, similar incidents, suggested fix, confidence
   - Opened by: **Triage Agent** (service account)
3. Reset to a healthy version (9) at 12:57:04.

| | Phase 0 (human) | Phase 1a (agent) | Phase 1b (agent + ticket) |
| --- | --- | --- | --- |
| Find the cause | 11 min 58 s | 32.5 s | ~50 s end to end |
| Ticket in ServiceNow | by hand | none | **automatic, with evidence** |

## Security: a dedicated integration user, not admin

The first attempt used the `admin` account and ServiceNow rejected API calls (HTTP 401): newer releases
lock down admin for scripted access. Instead the agent uses its own account:

- User `triage-agent`, Identity type **Machine**, **Internal Integration User** (API only, no UI login)
- Role **`itil`** only: can create and read incidents and change requests, nothing else
- Credentials stored in **AWS Secrets Manager** (`incident-triage/servicenow`), never in code

## Fix in this branch

INC0010001 had an empty **Caller**, a required field in the ServiceNow UI, so a human editing the ticket
would be blocked. `ServiceNow.create_incident()` now looks up the integration user's `sys_id` once (cached)
and sets it as the caller. Covered by `tests/test_integrations.py`.
