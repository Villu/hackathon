"""Deterministic escalation script — Phase 0 and the last rung of the fallback ladder.

Must always succeed and run in well under 20 ms. No I/O, no LLM.
TODO(team): extend the rule table with the alert names your golden set uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gateway.models import (
    Alert,
    DecisionSource,
    Environment,
    Phase,
    RecommendedAction,
    RootCauseCategory,
    Severity,
    SeverityAssessment,
    TriageDecision,
)


@dataclass(frozen=True)
class Rule:
    name_pattern: re.Pattern[str]
    severities: frozenset[Severity]
    category: RootCauseCategory
    assessment: SeverityAssessment
    action: RecommendedAction
    summary: str
    confidence: float = 0.5


_ANY = frozenset(Severity)
_HOT = frozenset({Severity.critical, Severity.warning})

RULES: list[Rule] = [
    Rule(
        re.compile(r"(cpu|memory|oom|throttl|disk|quota)", re.I),
        _HOT,
        RootCauseCategory.resource_exhaustion,
        SeverityAssessment.high,
        RecommendedAction.escalate_to_oncall,
        "Rule: resource exhaustion pattern in alert name; escalate for capacity review.",
    ),
    Rule(
        re.compile(r"(deploy|rollout|revision|crashloop|imagepull|errorrate|http5xx)", re.I),
        _HOT,
        RootCauseCategory.deployment_regression,
        SeverityAssessment.high,
        RecommendedAction.escalate_to_oncall,
        "Rule: deployment-related alert; check the latest revision before remediation.",
    ),
    Rule(
        re.compile(r"(upstream|dependency|connection|timeout|dns|database|db)", re.I),
        _HOT,
        RootCauseCategory.dependency_failure,
        SeverityAssessment.high,
        RecommendedAction.escalate_to_oncall,
        "Rule: dependency failure pattern; escalate to on-call for the upstream service.",
    ),
    Rule(
        re.compile(r"(requestrate|traffic|rps|latency)", re.I),
        frozenset({Severity.warning}),
        RootCauseCategory.traffic_spike,
        SeverityAssessment.medium,
        RecommendedAction.acknowledge,
        "Rule: traffic-related warning; acknowledge and watch.",
    ),
]


def deterministic_triage(alert: Alert, *, phase: Phase = Phase.provisional) -> TriageDecision:
    if alert.status.value == "resolved":
        return _decision(
            alert,
            phase,
            RootCauseCategory.unknown,
            SeverityAssessment.noise,
            RecommendedAction.no_action,
            "Rule: alert resolved; no action.",
            0.9,
        )
    if alert.severity is Severity.info:
        return _decision(
            alert,
            phase,
            RootCauseCategory.unknown,
            SeverityAssessment.low,
            RecommendedAction.no_action,
            "Rule: informational alert; no action.",
            0.8,
        )

    for rule in RULES:
        if alert.severity in rule.severities and rule.name_pattern.search(alert.name):
            action = rule.action
            if alert.resource.environment is Environment.prod and action not in {
                RecommendedAction.no_action,
                RecommendedAction.acknowledge,
                RecommendedAction.escalate_to_oncall,
            }:
                action = RecommendedAction.escalate_to_oncall
            return _decision(alert, phase, rule.category, rule.assessment, action, rule.summary, rule.confidence)

    # Default: critical → escalate, warning → acknowledge
    if alert.severity is Severity.critical:
        return _decision(
            alert,
            phase,
            RootCauseCategory.unknown,
            SeverityAssessment.critical,
            RecommendedAction.escalate_to_oncall,
            "Rule: unclassified critical alert; escalate to on-call.",
            0.4,
        )
    return _decision(
        alert,
        phase,
        RootCauseCategory.unknown,
        SeverityAssessment.medium,
        RecommendedAction.acknowledge,
        "Rule: unclassified warning; acknowledge.",
        0.4,
    )


def _decision(
    alert: Alert,
    phase: Phase,
    category: RootCauseCategory,
    assessment: SeverityAssessment,
    action: RecommendedAction,
    summary: str,
    confidence: float,
) -> TriageDecision:
    return TriageDecision(
        alert_id=alert.alert_id,
        decision_source=DecisionSource.deterministic_fallback,
        phase=phase,
        severity_assessment=assessment,
        root_cause_category=category,
        root_cause_summary=summary,
        confidence=confidence,
        recommended_action=action,
    )
