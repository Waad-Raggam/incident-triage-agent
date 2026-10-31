# Post 8: What I learned building an incident triage agent on AWS

The full system: alarm → agent diagnosis with evidence → ServiceNow ticket → approval → automated fix →
verified → stored as knowledge.

What I'd tell someone starting:
1. **Tools are the product.** Clear, read-only tools with good errors mattered more than prompt tweaks.
2. **Structured output + allow-listed actions** make an LLM safe to wire into automation.
3. **Not everything needs an LLM.** A small anomaly model filters noise more cheaply.
4. **Evals from day one.** Without them, every prompt change is a guess.
5. **Put humans where the audit trail already is.** In this case, ServiceNow.

Numbers: [tokens per triage], [cost per incident], [time from alarm to ticket], [time to resolve].

Repo, architecture diagrams and the full series: [link]

#AWS #AgenticAI #MLOps #SRE
