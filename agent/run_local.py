"""Phase 1: run the triage agent on your laptop against your real AWS account.

    python agent/run_local.py --alarm checkout-api-errors
    python agent/run_local.py --alarm checkout-api-errors --no-tickets   # skip ServiceNow/Slack calls

Needs AWS credentials in your shell; for tickets, the ServiceNow + Slack secrets in Secrets Manager.
"""

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from toolkit import local_tools  # noqa: E402
from triage import run_triage  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--alarm", default="checkout-api-errors")
    p.add_argument("--service", default="checkout-api")
    p.add_argument("--no-tickets", action="store_true", help="replace ServiceNow/Slack tools with stubs")
    p.add_argument("--memory", action="store_true", help="use AgentCore Memory (set MEMORY_ID)")
    args = p.parse_args()

    tools = local_tools()
    if args.no_tickets:
        tools = [t for t in tools if t.tool_name not in ("create_incident_ticket", "notify_oncall")]

    incident_id = f"{datetime.now(UTC):%Y-%m-%d}-{uuid.uuid4().hex[:6]}"
    alarm = {"alarmName": args.alarm, "state": {"value": "ALARM"}, "source": "local-run"}
    run = run_triage(alarm, incident_id, args.service, tools, use_memory=args.memory)
    print(json.dumps(run.to_dict(), indent=2))


if __name__ == "__main__":
    main()
