# Post 2: From laptop to AgentCore

Same agent code, now in the cloud:

- Amazon Bedrock AgentCore **Runtime** runs the agent container (ARM64)
- AgentCore **Gateway** puts every tool behind one MCP endpoint, with IAM auth. The agent has no direct AWS
  permissions besides calling the gateway, Bedrock and its memory
- **EventBridge** catches any `checkout-api-*` alarm and starts a **Step Functions** workflow, which invokes
  the agent

The trick that kept this simple: the tools are plain Python functions. Locally the agent calls them in-process.
In the cloud, the same functions run in a Lambda behind the gateway. In evals, they return canned data.
One agent, three tool modes.

Now I break the app and do nothing. A ticket appears.

[screenshot: Step Functions graph paused at the approval step]

#AWS #AgentCore #StepFunctions #MCP
