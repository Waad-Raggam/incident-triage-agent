# Build guide, phase by phase

Each phase ends with something you can demo and a post. Commands assume the repo root, an activated venv
(`source .venv/bin/activate`), and AWS credentials for your account in the shell.

> The repo already contains the finished code for every phase. Each section lists the files that phase
> introduces, so you can explain them in that phase's post.

---

## Phase 0: Setup and a broken app

**0a. Account and CI identity**
1. Edit `cdk.json`: `alert_email`, `github_repo` (`user/repo`), `region`, `monthly_budget_usd`.
   If your account already has a GitHub OIDC provider, set `create_github_oidc_provider` to `false`.
2. `pip install -r requirements-dev.txt && pytest -q`
3. `cdk bootstrap`
4. `cdk deploy Triage-Foundation` and confirm the budget email subscription.
5. In GitHub > Settings > Secrets and variables > Actions > **Variables**, add `AWS_ROLE_ARN`
   (output `GitHubActionsRoleArn`) and `AWS_REGION`.

**0b-c. The demo app and chaos**
1. `cdk deploy Triage-DemoApp`
2. Wait ~5 minutes for traffic, then open CloudWatch > Alarms: both `checkout-api-*` alarms are OK.
3. `cd chaos && python bad_deploy.py` → `checkout-api-errors` goes to ALARM in ~3 min.
4. `python reset.py` → back to OK.

Files: `infra/stacks/foundation_stack.py`, `infra/stacks/demo_app_stack.py`, `lambdas/demo_app/`, `lambdas/traffic/`, `chaos/`, `.github/workflows/ci.yml`

---

## Phase 1: The agent, running locally

1. Bedrock console > Model catalog > pick the Claude model in `cdk.json` > **Submit use case details** (once).
2. Store integration secrets: `bash scripts/setup_secrets.sh` (ServiceNow PDI URL/user/password, Slack webhook).
3. Break the app: `python chaos/bad_deploy.py`, wait for ALARM.
4. Run the agent on your laptop, no tickets first:
   `python agent/run_local.py --alarm checkout-api-errors --no-tickets`
5. Then for real: `python agent/run_local.py --alarm checkout-api-errors` → a ServiceNow incident and a Slack message.
6. `python chaos/reset.py`

Look for: evidence quoting the `payment_failed` log lines and version numbers, `remediation_action: rollback_deploy`.

Files: `agent/triage.py`, `agent/toolkit.py`, `agent/prompts/triage-v1.md`, `agent/schemas.py`, `lambdas/tools/`, `lambdas/layer/`

---

## Phase 2: The agent on AWS

1. Start Docker (the agent image is built for ARM64).
2. `cdk deploy Triage-State Triage-Agent Triage-Workflow`
3. `python chaos/bad_deploy.py` and do nothing else.
4. Watch: Step Functions > `incident-triage-workflow` > the running execution.
   The graph pauses at **RequestApprovalInServiceNow**; ServiceNow has an incident and a change request.

Files: `agent/main.py`, `agent/Dockerfile`, `infra/stacks/agent_stack.py`, `infra/stacks/workflow_stack.py`, `lambdas/workflow/steps.py`

---

## Phase 3: Databases for the agent: state

Already deployed in Phase 2; this phase is about understanding and showing it.
1. Fire both chaos scripts close together → the second alarm **attaches** to the open incident
   (`AttachedToOpenIncident` in Step Functions, `related_alarms` on the item).
2. `python scripts/incidents.py` and `python scripts/incidents.py <id>`: the full incident record.
3. AgentCore Memory: after 2-3 incidents, the semantic strategy extracts per-service facts; they appear in
   the agent's system prompt under "What you remember about this service".

Files: `infra/stacks/state_stack.py`, `lambdas/workflow/store.py`, `agent/memory.py`

---

## Phase 4: Databases for the agent: knowledge

1. `cdk deploy Triage-Knowledge`
2. `python scripts/sync_knowledge.py` → ingestion COMPLETE and the seed incident ranked first.
3. Run a bad deploy again: the ticket now cites `2026-09-12-seed01` under similar incidents.
4. After the incident closes, `incidents/checkout-api/<id>.md` appears in the knowledge bucket: the feedback loop.

Files: `infra/stacks/knowledge_stack.py`, `knowledge/`, `lambdas/workflow/knowledge.py`

---

## Phase 5: Human in the loop

1. With an execution waiting on approval, open the change request in ServiceNow and set
   **Approval** to *Approved* (on a PDI, as admin, edit the field and save).
2. Within a minute the poller resumes the workflow → `Remediate` (alias rolls back) → `Verify` → `CloseAndLearn`.
3. Try *Rejected* on another run → `HandOffRejected`; resolve the ServiceNow incident manually with close notes
   → the poller closes it and still writes it to the knowledge base.

Files: `lambdas/workflow/poller.py`, `lambdas/workflow/remediation.py`, guardrail in `infra/stacks/agent_stack.py`

---

## Phase 6: MLOps for the anomaly model

1. `cdk deploy Triage-Ml` (outputs `SageMakerRoleArn`, `MlBucket`)
2. Data: `python ml/make_training_data.py --s3 s3://<MlBucket>/data`
3. Local first: `python ml/make_training_data.py && python ml/train/train.py && python ml/train/evaluate.py --model ml/data/model --test ml/data/test --out ml/data/eval`
4. Pipeline (Python 3.11 venv with `pip install -r ml/requirements.txt`):
   `python ml/pipeline.py --role-arn <SageMakerRoleArn> --bucket <MlBucket> --start`
5. SageMaker Studio > Pipelines: Train → Evaluate → F1GoodEnough → Register. Approve the model version.
6. `python ml/deploy.py --role-arn <SageMakerRoleArn> --bucket <MlBucket>` → serverless endpoint `incident-anomaly`.
   The `score_anomaly` tool now says `"model": "sagemaker:incident-anomaly"`.
7. CI: add GitHub variables `SAGEMAKER_ROLE_ARN` and `ML_BUCKET`; pushes to `ml/**` run `ml-pipeline.yml`.
8. Drift: invoke `incident-triage-drift-check` manually once; check metric `IncidentTriage/AnomalyModelDriftPSI`.

Note: the bootstrap data is synthetic. The drift check adds real windows to the training set before retraining.

Files: `ml/`, `infra/stacks/ml_stack.py`, `.github/workflows/ml-pipeline.yml`

---

## Phase 7: LLMOps: testing the agent

1. `python evals/run_evals.py --case bad-deploy-errors` (one case, calls Bedrock)
2. `python evals/run_evals.py --update-baseline` and commit `evals/baseline.json`
3. Open a PR that weakens the prompt (e.g. delete the TIMING rule) → `agent-evals` fails with the score table.

Files: `evals/`, `agent/toolkit.py` (fixture mode), `.github/workflows/evals.yml`, `tests/test_agent_wiring.py`

---

## Phase 8: Observability, cost and wrap-up

1. `cdk deploy Triage-Observability` → CloudWatch dashboard `incident-triage`.
2. CloudWatch > GenAI Observability > Bedrock AgentCore: traces of every model and tool call.
3. Cost per incident = tokens (dashboard) × model price + Lambda/Step Functions (pennies).
4. Record the demo video: break → ticket + Slack → approve → rollback → resolved → knowledge doc.
5. `cdk destroy --all` when done (delete the secrets and the SageMaker endpoint separately).

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Model use case details have not been submitted` | Phase 1 step 1, wait 15 min |
| `AccessDeniedException` invoking a model | Check `model_id` in `cdk.json` exists in your region (inference profile IDs start with `us.`) |
| Docker build fails on deploy | Docker running? On x86 machines enable ARM64 emulation (Docker Desktop has it by default) |
| `RunAgent` times out | Check the AgentCore Runtime logs in CloudWatch; try a smaller model |
| Poller never resumes | Approval field must be exactly *Approved*; check `incident-triage-approvalpoller` logs |
| ServiceNow 401 | PDIs hibernate after inactivity: wake it at developer.servicenow.com, re-check the password |
| `invoke_agent_runtime` unknown in Lambda | Lambda's bundled boto3 is too old: add a layer with a recent boto3 |
