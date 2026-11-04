"""Data contracts: inbound Alert and outbound TriageDecision (spec section 3).

These models ARE the guardrail against invalid output reaching downstream systems.
Change them only together with the eval harness and the spec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- enums
class Severity(StrEnum):
    critical = "critical"
    warning = "warning"
    info = "info"


class AlertStatus(StrEnum):
    firing = "firing"
    resolved = "resolved"


class Environment(StrEnum):
    prod = "prod"
    staging = "staging"
    dev = "dev"


class DecisionSource(StrEnum):
    agent = "agent"
    agent_fast_model = "agent_fast_model"
    deterministic_fallback = "deterministic_fallback"


class Phase(StrEnum):
    provisional = "provisional"
    final = "final"


class SeverityAssessment(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    noise = "noise"


class RootCauseCategory(StrEnum):
    deployment_regression = "deployment_regression"
    resource_exhaustion = "resource_exhaustion"
    dependency_failure = "dependency_failure"
    config_error = "config_error"
    traffic_spike = "traffic_spike"
    infrastructure = "infrastructure"
    unknown = "unknown"


class RecommendedAction(StrEnum):
    no_action = "no_action"
    acknowledge = "acknowledge"
    escalate_to_oncall = "escalate_to_oncall"
    rollback_deployment = "rollback_deployment"
    restart_revision = "restart_revision"
    scale_out = "scale_out"
    silence_alert = "silence_alert"


# --------------------------------------------------------------------------- inbound
class ResourceRef(BaseModel):
    subscription_id: str | None = None
    resource_group: str = "VilluResourceGroup"
    type: str | None = None
    name: str
    environment: Environment = Environment.prod


class EvalSpec(BaseModel):
    """Ground truth attached by the eval harness. MUST never reach the LLM."""

    case_id: str
    expected_root_cause: RootCauseCategory | None = None
    expected_action: RecommendedAction | None = None
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    max_latency_ms: int | None = None


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alert_id: str
    source: str = "synthetic"
    name: str
    severity: Severity
    status: AlertStatus = AlertStatus.firing
    starts_at: datetime = Field(default_factory=utcnow)
    resource: ResourceRef
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    value: float | None = None
    eval: EvalSpec | None = None

    def for_llm(self) -> dict[str, Any]:
        """Alert as the LLM may see it: `eval` stripped. Annotations are untrusted text."""
        data = self.model_dump(mode="json", exclude={"eval"})
        return data


# --------------------------------------------------------------------------- outbound
class Evidence(BaseModel):
    tool: str
    summary: str = Field(max_length=300)
    ref: str | None = None


class ToolCallRecord(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int
    ok: bool
    error: str | None = None


class TriageDraft(BaseModel):
    """What the LLM must produce. Kept separate from TriageDecision so the schema sent to the
    model contains nothing the model should not control (latency, source, guardrail events).
    """

    severity_assessment: SeverityAssessment
    root_cause_category: RootCauseCategory
    root_cause_summary: str = Field(max_length=280)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: RecommendedAction
    evidence: list[Evidence] = Field(default_factory=list, max_length=10)


class DecisionScores(BaseModel):
    """Live scores computed by gateway.scoring (spec 6.2)."""

    schema_valid: bool = True
    safety_ok: bool = True
    tool_call_accuracy: float | None = None
    root_cause_match: bool | None = None
    action_match: bool | None = None
    latency_ok: bool | None = None


class TriageDecision(BaseModel):
    alert_id: str
    decided_at: datetime = Field(default_factory=utcnow)
    decision_source: DecisionSource
    phase: Phase
    severity_assessment: SeverityAssessment
    root_cause_category: RootCauseCategory
    root_cause_summary: str = Field(max_length=280)
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: RecommendedAction
    action_executed: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    latency_ms: int = 0
    guardrail_events: list[str] = Field(default_factory=list)
    scores: DecisionScores | None = None

    @field_validator("root_cause_summary")
    @classmethod
    def _single_line(cls, v: str) -> str:
        return " ".join(v.split())

    @classmethod
    def from_draft(
        cls,
        alert: Alert,
        draft: TriageDraft,
        *,
        source: DecisionSource,
        phase: Phase,
        tool_calls: list[ToolCallRecord] | None = None,
        latency_ms: int = 0,
    ) -> TriageDecision:
        return cls(
            alert_id=alert.alert_id,
            decision_source=source,
            phase=phase,
            severity_assessment=draft.severity_assessment,
            root_cause_category=draft.root_cause_category,
            root_cause_summary=draft.root_cause_summary,
            confidence=draft.confidence,
            recommended_action=draft.recommended_action,
            evidence=draft.evidence,
            tool_calls=tool_calls or [],
            latency_ms=latency_ms,
        )
