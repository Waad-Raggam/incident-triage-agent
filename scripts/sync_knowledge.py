"""Start a Knowledge Base ingestion job and wait for it (run after deploying Triage-Knowledge)."""

import time

import boto3

ssm, agent = boto3.client("ssm"), boto3.client("bedrock-agent")
kb = ssm.get_parameter(Name="/incident-triage/knowledge-base-id")["Parameter"]["Value"]
ds = ssm.get_parameter(Name="/incident-triage/knowledge-data-source-id")["Parameter"]["Value"]
job = agent.start_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds)["ingestionJob"]["ingestionJobId"]
while True:
    j = agent.get_ingestion_job(knowledgeBaseId=kb, dataSourceId=ds, ingestionJobId=job)["ingestionJob"]
    print(j["status"], j.get("statistics", {}))
    if j["status"] in ("COMPLETE", "FAILED", "STOPPED"):
        break
    time.sleep(5)

hits = boto3.client("bedrock-agent-runtime").retrieve(
    knowledgeBaseId=kb, retrievalQuery={"text": "PaymentGatewayError connection pool exhausted after deploy"})
for r in hits["retrievalResults"][:3]:
    print(round(r["score"], 3), r["location"]["s3Location"]["uri"])
