# Post 3: Agents need state (and a memory)

Two database problems showed up as soon as the agent ran in the cloud.

**1. Alarm storms.** One bad deploy fires the errors alarm and the latency alarm. Without state, that's two
triages, two tickets, double the tokens. Fix: a DynamoDB lock per service with a conditional write. The second
alarm attaches to the open incident instead of starting a new one.

**2. Forgetting.** Every run started from zero. Fix: AgentCore Memory, with the service as the actor and the
incident as the session. A semantic strategy pulls out long-term facts per service, which go into the prompt
as hints to verify, never as truth.

The incident table design is a single-table pattern: `INCIDENT#id` items, `LOCK#service` items, and a GSI on
status so the approval poller finds waiting incidents quickly.

[screenshot: DynamoDB item with triage result, ticket, related_alarms]

#DynamoDB #AgentCore #AgenticAI
