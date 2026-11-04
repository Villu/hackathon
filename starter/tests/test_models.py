import pytest
from pydantic import ValidationError

from gateway.models import EvalSpec, TriageDraft
from tests.conftest import make_alert


def test_draft_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        TriageDraft(
            severity_assessment="high",
            root_cause_category="unknown",
            root_cause_summary="x",
            confidence=1.7,
            recommended_action="acknowledge",
        )


def test_draft_rejects_unknown_action_and_long_summary():
    with pytest.raises(ValidationError):
        TriageDraft(
            severity_assessment="high",
            root_cause_category="unknown",
            root_cause_summary="x",
            confidence=0.5,
            recommended_action="delete_everything",
        )
    with pytest.raises(ValidationError):
        TriageDraft(
            severity_assessment="high",
            root_cause_category="unknown",
            root_cause_summary="A" * 281,
            confidence=0.5,
            recommended_action="acknowledge",
        )


def test_alert_for_llm_strips_eval():
    alert = make_alert(eval=EvalSpec(case_id="c1", required_tools=["query_logs"]))
    data = alert.for_llm()
    assert "eval" not in data
    assert data["resource"]["name"] == "orders-api"
