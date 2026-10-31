# Incident Triage Agent on AWS

When a CloudWatch alarm fires, an AI agent gathers logs, metrics and deploy history, checks past incidents,
opens a **ServiceNow** incident with evidence and a likely root cause, and proposes **one** safe fix.
On-call approves the fix **in ServiceNow**, Step Functions runs it, verifies the alarm clears, and the
incident becomes knowledge for next time.

Built with **Strands Agents** on **Amazon Bedrock AgentCore** (Runtime, Gateway, Memory, Observability),
**DynamoDB**, a **Bedrock Knowledge Base on S3 Vectors**, **Step Functions**, **SageMaker Pipelines**,
**GitHub Actions** (OIDC) and **AWS CDK (Python)**.

```
CloudWatch alarm ─► EventBridge ─► Step Functions ─► AgentCore Runtime (Strands agent)
                                        │                   │ MCP + SigV4
                                        │                   ▼
                                        │            AgentCore Gateway ─► tools Lambda ─► CloudWatch, Lambda,
                                        │                                                 SSM, Knowledge Base,
                                        │                                                 SageMaker, ServiceNow, Slack
                                        ├─► ServiceNow change request ─► on-call approves ─► remediation (allow-list)
                                        └─► verify alarm cleared ─► resolve ticket ─► write to Knowledge Base
```

## Repo map

| Path | What | Phase |
| --- | --- | --- |
| `infra/` | CDK app: one stack per layer | all |
| `lambdas/demo_app`, `chaos/` | `checkout-api` demo service and scripts that break it | 0 |
| `agent/` | Strands agent, prompts, memory, AgentCore entrypoint, local runner | 1-3 |
| `lambdas/tools/` | The agent's tools (Gateway Lambda target) + `schema.json` | 1-2 |
| `lambdas/workflow/` | Step Functions steps: dedupe, run agent, approval, remediate, verify, close, poller | 2-5 |
| `knowledge/` | Seed runbooks + a seed incident for the Knowledge Base | 4 |
| `ml/` | Anomaly model: data, training, evaluation, pipeline, deploy, drift check | 6 |
| `evals/` | Synthetic incidents + eval runner with an LLM judge | 7 |
| `.github/workflows/` | CI (lint, tests, synth), evals gate, deploy, ML pipeline | 0, 6, 7 |
| `docs/PHASES.md` | Step-by-step build guide, one section per phase | all |
| `docs/posts/` | Draft posts for the series | all |

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q && cdk synth --quiet           # works offline
# edit cdk.json: alert_email, github_repo, region, model_id
cdk bootstrap
cdk deploy Triage-Foundation Triage-DemoApp
```

Then follow **[docs/PHASES.md](docs/PHASES.md)**.

## Safety model

- The agent can **read** CloudWatch, Lambda versions, flags and the Knowledge Base. It can **write** only a
  ServiceNow incident and a Slack message. It cannot change infrastructure.
- Infrastructure changes are an **allow-list** of two actions (`rollback_deploy`, `clear_feature_flag`)
  executed by Step Functions **only after a ServiceNow change is approved**.
- Bedrock Guardrails anonymise PII; token and turn limits stop runaway runs; failures fall back to humans.

## Cost

Everything is serverless or on-demand, so idle cost is small: the traffic generator (~1.3M Lambda
invocations a month), a few CloudWatch alarms and logs, plus storage. Bedrock tokens per triage and SageMaker
training runs are the main variable costs. The Foundation stack sets a budget alert. Disable the
`Triage-DemoApp` EveryMinute rule when you're not demoing, and `cdk destroy --all` removes everything.
