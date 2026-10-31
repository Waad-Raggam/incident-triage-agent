"""Show recent incidents from DynamoDB:  python scripts/incidents.py [incident_id]"""

import json
import sys

import boto3

table = boto3.resource("dynamodb").Table("incident-triage-incidents")
if len(sys.argv) > 1:
    item = table.get_item(Key={"pk": f"INCIDENT#{sys.argv[1]}"}).get("Item", {})
    item.pop("task_token", None)
    print(json.dumps(item, indent=2, default=str))
else:
    items = [i for i in table.scan()["Items"] if i["pk"].startswith("INCIDENT#")]
    for i in sorted(items, key=lambda x: x.get("opened_at", ""), reverse=True)[:15]:
        t = i.get("triage", {})
        print(f"{i.get('opened_at')}  {i['incident_id']}  {i.get('status'):<18} {i.get('ticket_number', ''):<11} "
              f"{t.get('remediation_action', ''):<18} {t.get('root_cause', '')[:70]}")
