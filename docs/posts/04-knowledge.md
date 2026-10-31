# Post 4: My agent now learns from every incident

The best incident responders aren't the ones who know everything. They're the ones who remember
"we saw this in September".

Phase 4 gives the agent that memory of past fixes:

- A Bedrock Knowledge Base over runbooks and resolved incidents
- Stored in **S3 Vectors**, so there's no cluster idling at an hourly cost
- Metadata filters by service

Then the feedback loop: when an incident closes, automatically or by a human, the workflow writes a short
summary (root cause, evidence, fix) to S3 and re-syncs the Knowledge Base. The next similar alarm retrieves it,
and the ticket cites it.

The second time I ran the bad deploy, the ticket said: [quote the similar-incident line].

#RAG #Bedrock #S3Vectors
