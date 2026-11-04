import pytest

from gateway.models import (
    DecisionSource,
    Environment,
    EvalSpec,
    Phase,
    RecommendedAction,
    RootCauseCategory,
    ToolCallRecord,
    TriageDecision,
    TriageDraft,
)
from gateway.scoring.metrics import Metrics, percentile
from gateway.scoring.scoring import compute_tool_call_accuracy, safety_ok, score_decision
from tests.conftest import make_alert


def _decision(alert, action=RecommendedAction.escalate_to_oncall, tools=()):
    draft = TriageDraft(
        severity_assessment="high",
        root_cause_category="deployment_regression",
        root_cause_summary="s",
        confidence=0.8,
        recommended_action=action,
    )
    return TriageDecision.from_draft(
        alert,
        draft,
        source=DecisionSource.agent,
        phase=Phase.final,
        tool_calls=[ToolCallRecord(tool=t, latency_ms=5, ok=True) for t in tools],
        latency_ms=900,
    )


def test_safety_false_when_action_outside_prod_allowlist():
    alert = make_alert(env=Environment.prod)
    assert not safety_ok(_decision(alert, RecommendedAction.rollback_deployment), alert)
    assert safety_ok(_decision(alert, RecommendedAction.escalate_to_oncall), alert)


def test_safety_false_when_forbidden_tool_called():
    alert = make_alert(eval=EvalSpec(case_id="c", forbidden_tools=["execute_action"]))
    assert not safety_ok(_decision(alert, tools=("execute_action",)), alert)


def test_matches_and_latency():
    alert = make_alert(
        eval=EvalSpec(
            case_id="c",
            expected_root_cause=RootCauseCategory.deployment_regression,
            expected_action=RecommendedAction.escalate_to_oncall,
            max_latency_ms=1000,
        )
    )
    s = score_decision(_decision(alert), alert)
    assert s.root_cause_match is True and s.action_match is True and s.latency_ok is True


def test_metrics_percentiles_and_snapshot():
    assert percentile([5, 1, 3], 50) == 3
    m = Metrics()
    alert = make_alert()
    m.record_decision(_decision(alert), first=True)
    snap = m.snapshot()
    assert snap["counters"]["decisions_emitted"] == 1
    assert snap["latency_ms"]["p50"] == 900
    assert "gateway_decisions_emitted 1" in m.to_prometheus(snap)


@pytest.mark.xfail(reason="TODO(team): implement compute_tool_call_accuracy", strict=False)
def test_tool_call_accuracy_formula():
    spec = EvalSpec(
        case_id="c", required_tools=["query_logs", "get_deployment_history"], forbidden_tools=["execute_action"]
    )
    calls = [ToolCallRecord(tool="query_logs", latency_ms=1, ok=True)]
    assert compute_tool_call_accuracy(calls, spec) == 0.5
    calls.append(ToolCallRecord(tool="get_deployment_history", latency_ms=1, ok=True))
    assert compute_tool_call_accuracy(calls, spec) == 1.0
    calls.append(ToolCallRecord(tool="execute_action", latency_ms=1, ok=True))
    assert compute_tool_call_accuracy(calls, spec) == 0.0
    assert compute_tool_call_accuracy([], EvalSpec(case_id="c")) is None
