#!/usr/bin/env python3
"""CDK entrypoint. Deploy stacks one phase at a time, e.g. `cdk deploy Triage-DemoApp`."""

import os

import aws_cdk as cdk

from infra.config import Config
from infra.stacks.agent_stack import AgentStack
from infra.stacks.demo_app_stack import DemoAppStack
from infra.stacks.foundation_stack import FoundationStack
from infra.stacks.knowledge_stack import KnowledgeStack
from infra.stacks.ml_stack import MlStack
from infra.stacks.observability_stack import ObservabilityStack
from infra.stacks.state_stack import StateStack
from infra.stacks.workflow_stack import WorkflowStack

app = cdk.App()
cfg = Config.load(app)
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", cfg.region),
)

# Phase 0: guard rails for your wallet + CI identity, and the app we will break on purpose
foundation = FoundationStack(app, "Triage-Foundation", cfg=cfg, env=env)
demo = DemoAppStack(app, "Triage-DemoApp", cfg=cfg, env=env)

# Phase 2-3: incident state (DynamoDB) + the agent on AgentCore (Runtime, Gateway, Memory)
state = StateStack(app, "Triage-State", cfg=cfg, env=env)
agent = AgentStack(app, "Triage-Agent", cfg=cfg, state=state, demo=demo, env=env)

# Phase 2 + 5: alarm -> Step Functions -> agent -> ServiceNow approval -> remediation
workflow = WorkflowStack(app, "Triage-Workflow", cfg=cfg, state=state, agent=agent, demo=demo, env=env)

# Phase 4: knowledge of past fixes (Bedrock Knowledge Base on S3 Vectors)
knowledge = KnowledgeStack(app, "Triage-Knowledge", cfg=cfg, state=state, env=env)

# Phase 6: anomaly model MLOps (SageMaker role, data bucket, drift check)
ml = MlStack(app, "Triage-Ml", cfg=cfg, state=state, demo=demo, env=env)

# Phase 8: one dashboard for the whole system
ObservabilityStack(app, "Triage-Observability", cfg=cfg, demo=demo, agent=agent, workflow=workflow, env=env)

cdk.Tags.of(app).add("project", cfg.project)
app.synth()
