#!/usr/bin/env bash
# Stores ServiceNow + Slack credentials in AWS Secrets Manager. Values are typed, never echoed or committed.
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"

read -rp  "ServiceNow instance URL (https://devXXXXX.service-now.com): " SN_URL
read -rp  "ServiceNow username [admin]: " SN_USER; SN_USER="${SN_USER:-admin}"
read -rsp "ServiceNow password: " SN_PASS; echo
read -rsp "Slack incoming webhook URL: " SLACK_URL; echo

put() {  # create or update
  if aws secretsmanager describe-secret --secret-id "$1" --region "$REGION" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --secret-id "$1" --secret-string "$2" --region "$REGION" >/dev/null
  else
    aws secretsmanager create-secret --name "$1" --secret-string "$2" --region "$REGION" >/dev/null
  fi
  echo "saved $1"
}

put incident-triage/servicenow "$(python3 -c 'import json,sys; print(json.dumps({"instance_url": sys.argv[1], "username": sys.argv[2], "password": sys.argv[3]}))' "$SN_URL" "$SN_USER" "$SN_PASS")"
put incident-triage/slack "$(python3 -c 'import json,sys; print(json.dumps({"webhook_url": sys.argv[1]}))' "$SLACK_URL")"
