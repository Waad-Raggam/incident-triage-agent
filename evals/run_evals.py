"""Phase 7: unit tests for the agent. Runs the REAL agent + model against canned tool outputs.

    python evals/run_evals.py                      # all cases, compare with baseline
    python evals/run_evals.py --case noise-single-blip
    python evals/run_evals.py --update-baseline    # accept current scores as the new bar
    python evals/run_evals.py --publish-metric     # also send EvalScore to CloudWatch (CI on main)

Per-case score (0-1) =
  0.25 verdict right + 0.25 remediation right + 0.10 required tools called
  + 0.10 ticket discipline (exactly one ticket when actionable, none when noise)
  + 0.30 LLM judge: does root_cause match the reference, backed by evidence? (1-5 -> 0-1)
A case with max_confidence also loses the remediation points if the agent was over-confident.
Exit code 1 if the average drops more than --tolerance below evals/baseline.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "agent"))

import boto3  # noqa: E402
from toolkit import fixture_tools  # noqa: E402
from triage import run_triage  # noqa: E402

JUDGE_PROMPT = """You grade an incident-triage agent. Compare the agent's root cause with the reference.
Reference root cause: {reference}
Agent root cause: {root_cause}
Agent evidence: {evidence}

Score 1-5: 5 = same cause and supported by the evidence; 3 = partly right or weakly supported;
1 = wrong cause or unsupported claims. Reply with JSON only: {{"score": <1-5>, "reason": "<one sentence>"}}"""


def judge(reference: str, result: dict, model_id: str) -> tuple[float, str]:
    brt = boto3.client("bedrock-runtime")
    msg = JUDGE_PROMPT.format(reference=reference, root_cause=result["root_cause"],
                              evidence=json.dumps(result["evidence"])[:3000])
    resp = brt.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": msg}]}],
                        inferenceConfig={"maxTokens": 200, "temperature": 0})
    text = resp["output"]["message"]["content"][0]["text"]
    try:
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return (float(data["score"]) - 1) / 4, data.get("reason", "")
    except Exception:
        return 0.0, f"unparseable judge output: {text[:100]}"


def score_case(case: dict, run: dict, calls: list[dict], judge_score: float) -> dict:
    exp, res = case["expected"], run["result"]
    called = [c["tool"] for c in calls]
    verdict_ok = res["verdict"] == exp["verdict"]
    action_ok = res["remediation_action"] == exp["remediation_action"]
    if "max_confidence" in exp and res["confidence"] > exp["max_confidence"]:
        action_ok = False
    tools_ok = sum(t in called for t in exp["must_call"]) / len(exp["must_call"])
    tickets = called.count("create_incident_ticket")
    ticket_ok = (tickets == 1) if exp["verdict"] == "actionable" else (tickets == 0)
    total = 0.25 * verdict_ok + 0.25 * action_ok + 0.10 * tools_ok + 0.10 * ticket_ok + 0.30 * judge_score
    return {"verdict_ok": verdict_ok, "action_ok": action_ok, "tools_ok": round(tools_ok, 2),
            "ticket_ok": ticket_ok, "judge": round(judge_score, 2), "score": round(total, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="")
    ap.add_argument("--prompt-version", default=os.environ.get("PROMPT_VERSION", "triage-v1"))
    ap.add_argument("--model-id", default=os.environ.get("MODEL_ID"))
    ap.add_argument("--judge-model-id", default=os.environ.get("JUDGE_MODEL_ID",
                                                               "us.anthropic.claude-haiku-4-5-20251001-v1:0"))
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--publish-metric", action="store_true")
    a = ap.parse_args()

    files = sorted((ROOT / "incidents").glob("*.json"))
    cases = [json.loads(f.read_text()) for f in files if not a.case or f.stem == a.case]
    rows = []
    for case in cases:
        calls: list[dict] = []
        alarm = {"alarmName": case["alarm_name"], "state": {"value": "ALARM"}}
        run = run_triage(alarm, f"eval-{case['id']}", "checkout-api", fixture_tools(case["fixtures"], calls),
                         prompt_version=a.prompt_version, model_id=a.model_id, use_memory=False).to_dict()
        j, reason = judge(case["expected"]["root_cause_reference"], run["result"], a.judge_model_id)
        s = score_case(case, run, calls, j)
        rows.append({"case": case["id"], **s, "judge_reason": reason, "tokens": run["usage"].get("totalTokens"),
                     "seconds": run["seconds"], "agent": run["result"]})
        print(f"{case['id']:<28} score={s['score']:.2f} verdict={s['verdict_ok']} action={s['action_ok']} "
              f"tools={s['tools_ok']} ticket={s['ticket_ok']} judge={s['judge']}")

    avg = round(statistics.mean(r["score"] for r in rows), 3)
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    report = {"prompt_version": a.prompt_version, "model_id": a.model_id, "average": avg, "cases": rows,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out_dir / "latest.json").write_text(json.dumps(report, indent=2, default=str))

    md = ["| case | score | verdict | action | tools | ticket | judge |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['case']} | {r['score']:.2f} | {r['verdict_ok']} | {r['action_ok']} | {r['tools_ok']} | "
           f"{r['ticket_ok']} | {r['judge']} |" for r in rows]
    summary = f"## Agent evals: {avg:.3f} ({a.prompt_version})\n\n" + "\n".join(md)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary)
    print(summary)

    if a.publish_metric:
        boto3.client("cloudwatch").put_metric_data(Namespace="IncidentTriage", MetricData=[
            {"MetricName": "EvalScore", "Value": avg, "Unit": "None"}])

    baseline_file = ROOT / "baseline.json"
    if a.update_baseline:
        baseline_file.write_text(json.dumps({"average": avg, "prompt_version": a.prompt_version}, indent=2))
        print("baseline updated")
        return 0
    if a.case or not baseline_file.exists():
        return 0
    baseline = json.loads(baseline_file.read_text())["average"]
    if avg < baseline - a.tolerance:
        print(f"FAIL: {avg:.3f} is below baseline {baseline:.3f} - {a.tolerance}")
        return 1
    print(f"PASS: {avg:.3f} vs baseline {baseline:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
