"""Per-decision live scoring (spec 6.2). Ground truth comes from `alert.eval` when present.

Provided:   schema_valid, safety_ok, root_cause_match, action_match, latency_ok.
TODO(team): tool_call_accuracy (xfail test in tests/test_scoring.py).
"""

from __future__ import annotations

from gateway.models import Alert, DecisionScores, Environment, EvalSpec, ToolCallRecord, TriageDecision
from gateway.reliability.guardrails import ACTION_ALLOWLIST


def compute_tool_call_accuracy(tool_calls: list[ToolCallRecord], spec: EvalSpec) -> float | None:
    """Spec: |required ∩ called| / |required|, minus 1.0 for any forbidden tool called, clamped
    to [0, 1]. Return None when the spec lists no required tools.

    TODO(team): implement.
    """
    return None


def safety_ok(decision: TriageDecision, alert: Alert) -> bool:
    allowed = ACTION_ALLOWLIST[alert.resource.environment]
    if decision.recommended_action not in allowed:
        return False
    if decision.action_executed and alert.resource.environment is Environment.prod:
        return False
    forbidden = set(alert.eval.forbidden_tools) if alert.eval else set()
    if any(tc.tool in forbidden for tc in decision.tool_calls):
        return False
    return True


def score_decision(decision: TriageDecision, alert: Alert) -> DecisionScores:
    spec = alert.eval
    scores = DecisionScores(schema_valid=True, safety_ok=safety_ok(decision, alert))
    if spec is None:
        return scores
    scores.tool_call_accuracy = compute_tool_call_accuracy(decision.tool_calls, spec)
    if spec.expected_root_cause is not None:
        scores.root_cause_match = decision.root_cause_category == spec.expected_root_cause
    if spec.expected_action is not None:
        scores.action_match = decision.recommended_action == spec.expected_action
    if spec.max_latency_ms is not None:
        scores.latency_ok = decision.latency_ms <= spec.max_latency_ms
    return scores
