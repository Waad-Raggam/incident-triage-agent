# Post 1: My first incident agent, from alarm to ServiceNow ticket

Phase 1: the agent runs on my laptop against my real AWS account.

It's a Strands agent on Amazon Bedrock with tools that read CloudWatch alarms, metrics and Logs Insights,
Lambda deploy history and feature flags. One tool writes a ServiceNow incident and one posts to Slack.

The rule I care most about, written into the prompt: every claim in the root cause must quote evidence.
A log line, a metric value with its time, a version number. No evidence, no claim.

The result is structured, not free text: verdict, root cause, evidence, suggested fix, one remediation from
an allow-list, and a confidence score. Downstream code can act on that.

On my bad-deploy test it found [what it found] in [N] seconds and opened [INC number].

[screenshot: the ServiceNow incident with the evidence section]

#AWS #Bedrock #Strands #ServiceNow
