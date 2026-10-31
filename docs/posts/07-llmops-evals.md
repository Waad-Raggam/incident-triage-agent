# Post 7: Unit tests for an AI agent

How do you know a prompt change didn't make your agent worse? You test it, same as code.

- 6 synthetic incidents: bad deploy, slow dependency, a noise blip, a provider outage, failing tools,
  and a bad deploy with no history
- The real agent runs against canned tool outputs, so there are no AWS calls besides the model
- Scoring: right verdict, right remediation, required tools called, exactly one ticket, plus an LLM judge
  comparing the root cause with a reference
- A GitHub Actions gate: if the average drops below the baseline, the PR can't merge

Favourite case: "tools failing". The agent must lower its confidence and pick no action instead of guessing.

Then I deleted one line from the prompt (the timing rule) and opened a PR: [score before → after].

#LLMOps #Evals #GitHubActions
