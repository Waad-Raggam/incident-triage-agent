# Post 0: I built an app designed to fail

I'm starting a build-in-public series: an AI agent that triages production incidents on AWS.

Why incidents? At 3 a.m. the hard part isn't fixing the problem. It's finding it: which alarm, which log line,
what changed. That's exactly the kind of evidence-gathering an agent should be good at.

But an incident agent needs incidents. So step one was building something to break:

- `checkout-api`, a small Lambda service with a `live` alias, CloudWatch alarms on errors and p99 latency,
  and a traffic generator so metrics always exist
- Two chaos scripts: a bad deploy (half of checkouts fail) and a slow dependency behind a feature flag
- Guard rails from day one: an AWS budget alert, and GitHub Actions that deploy through OIDC with no stored keys

Everything is AWS CDK in Python.

Next post: the agent's first diagnosis, running on my laptop.

[screenshot: the errors alarm going red after `python chaos/bad_deploy.py`]

#AWS #AgenticAI #SRE #BuildInPublic
