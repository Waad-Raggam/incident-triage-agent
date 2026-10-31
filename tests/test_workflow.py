import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lambdas/layer/python"))

import remediation  # noqa: E402
import store  # noqa: E402

import knowledge  # noqa: E402


@pytest.mark.parametrize(("versions", "current", "expected"), [
    (["$LATEST", "1", "2"], "2", "1"),
    (["$LATEST", "1", "2", "3", "4"], "4", "3"),
    (["$LATEST", "1", "3", "7"], "7", "3"),
    (["$LATEST", "1"], "1", None),
])
def test_previous_version(versions, current, expected):
    assert remediation.previous_version(versions, current) == expected


def test_only_allow_listed_actions_run():
    with pytest.raises(ValueError):
        remediation.execute("delete_database")
    with pytest.raises(ValueError):
        remediation.execute("none")


def test_ddb_round_trip_handles_floats():
    item = {"confidence": 0.85, "evidence": [1.5, "x"], "nested": {"seconds": 12.0}}
    stored = store.to_ddb(item)
    assert stored["confidence"] == Decimal("0.85")
    assert store.from_ddb(stored) == {"confidence": 0.85, "evidence": [1.5, "x"], "nested": {"seconds": 12}}


def test_incident_markdown_has_what_retrieval_needs():
    inc = {"incident_id": "2026-10-31-abc123", "service": "checkout-api", "alarm_name": "checkout-api-errors",
           "ticket_number": "INC0010010",
           "triage": {"root_cause": "version 2 broke payments", "evidence": ["alias -> 2"],
                      "remediation_action": "rollback_deploy"},
           "remediation_result": {"action": "rollback_deploy", "to_version": "1"}}
    md = knowledge.incident_markdown(inc, "Rolled back to 1")
    for needle in ("2026-10-31-abc123", "checkout-api-errors", "version 2 broke payments", "Rolled back to 1",
                   "rollback_deploy", "INC0010010"):
        assert needle in md
