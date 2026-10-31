# Post 5: Why my agent asks before it acts

The agent never changes infrastructure. I designed it that way on purpose.

- It **proposes** one action from an allow-list: roll back the deploy, or clear a feature flag
- Step Functions opens a **ServiceNow change request** and waits on a task token
- On-call approves in ServiceNow, which is where companies already keep an audit trail of who approved what
- A poller sees the approval, resumes the workflow, runs the action, waits, and checks the alarm cleared
- Rejected? The incident goes to a human. When they resolve it, their fix still goes into the knowledge base

Plus Bedrock Guardrails to anonymise PII before anything reaches a ticket, and turn and token limits that fall
back to "needs human triage".

Time from alarm to fixed, with a 1-click approval: [N minutes].

[demo GIF: approve → rollback → alarm OK → ticket resolved]

#HumanInTheLoop #ServiceNow #AIsafety
