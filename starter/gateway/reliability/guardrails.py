"""Deterministic guardrails applied to every agent decision before it leaves the gateway.

Provided:   schema parsing of LLM text, content sanitisation (partial pattern list).
TODO(team): action allowlist enforcement, confidence gate, more patterns. Tests for the
            TODO parts are marked xfail in tests/test_guardrails.py — make them pass.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from gateway.models import (
    Alert,
    Environment,
    RecommendedAction,
    TriageDecision,
    TriageDraft,
)

# --------------------------------------------------------------------------- content
# Patterns that must never appear in text we forward downstream. Matches are redacted and a
# guardrail event is recorded. TODO(team): extend (JWTs, Azure keys, more injection phrases).
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("shell_command", re.compile(r"\b(rm\s+-rf|curl\s+[^|]*\|\s*(ba)?sh|sudo\s+\w+|kubectl\s+delete)\b", re.I)),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("injection", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("markdown", re.compile(r"(\*\*|__|```|^#{1,6}\s)", re.M)),
]

_URL_RE = re.compile(r"https?://\S+", re.I)


def sanitise_text(text: str, *, allowed_urls: set[str] | None = None) -> tuple[str, list[str]]:
    """Return (clean_text, guardrail_events). Never raises."""
    events: list[str] = []
    clean = " ".join(text.split())
    for name, pattern in FORBIDDEN_PATTERNS:
        if pattern.search(clean):
            clean = pattern.sub("[redacted]", clean)
            events.append(f"redacted_{name}")

    def _url(m: re.Match[str]) -> str:
        url = m.group(0).rstrip(".,)")
        if allowed_urls and url in allowed_urls:
            return url
        events.append("redacted_url")
        return "[url]"

    clean = _URL_RE.sub(_url, clean)
    if len(clean) > 280:
        clean = clean[:277] + "..."
        events.append("summary_truncated")
    return clean, sorted(set(events))


# --------------------------------------------------------------------------- schema
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


class DraftParseError(ValueError):
    """Raised when the LLM text is not a valid TriageDraft. Message is safe to feed back
    to the model on the retry (spec: 'retry once with the validation error in the prompt')."""


def parse_draft(text: str | None) -> TriageDraft:
    if not text or not text.strip():
        raise DraftParseError("empty response; expected a JSON object")
    candidate = _FENCE_RE.sub("", text.strip())
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        raise DraftParseError("no JSON object found in response")
    try:
        data = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"invalid JSON: {exc.msg} at pos {exc.pos}") from exc
    try:
        return TriageDraft.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        raise DraftParseError(f"schema violation: {problems}") from exc


# --------------------------------------------------------------------------- policy
# Which actions the gateway may recommend per environment. Remediation is never allowed
# in prod without a human (spec section 5).
ACTION_ALLOWLIST: dict[Environment, frozenset[RecommendedAction]] = {
    Environment.prod: frozenset(
        {RecommendedAction.no_action, RecommendedAction.acknowledge, RecommendedAction.escalate_to_oncall}
    ),
    Environment.staging: frozenset(
        {
            RecommendedAction.no_action,
            RecommendedAction.acknowledge,
            RecommendedAction.escalate_to_oncall,
            RecommendedAction.restart_revision,
            RecommendedAction.rollback_deployment,
            RecommendedAction.scale_out,
        }
    ),
    Environment.dev: frozenset(RecommendedAction),
}


def apply_action_allowlist(decision: TriageDecision, alert: Alert) -> TriageDecision:
    """Downgrade any action outside the environment's allowlist to `escalate_to_oncall`
    and append "action_downgraded" to `guardrail_events`.

    TODO(team): implement. Currently a pass-through.
    """
    return decision


def apply_confidence_gate(decision: TriageDecision, threshold: float) -> TriageDecision:
    """If `confidence < threshold` and the action is anything other than no_action /
    acknowledge / escalate_to_oncall, set the action to `escalate_to_oncall` and append
    "confidence_below_threshold". `decision_source` stays unchanged.

    TODO(team): implement. Currently a pass-through.
    """
    return decision


def apply_guardrails(decision: TriageDecision, alert: Alert, *, confidence_threshold: float) -> TriageDecision:
    """Run every deterministic guardrail on an agent decision. Order matters: sanitise text,
    then policy (allowlist, confidence). Always returns a valid TriageDecision."""
    runbook = alert.annotations.get("runbook_url")
    allowed = {runbook} if runbook else None
    summary, events = sanitise_text(decision.root_cause_summary, allowed_urls=allowed)
    evidence = []
    for ev in decision.evidence:
        text, ev_events = sanitise_text(ev.summary, allowed_urls=allowed)
        events.extend(ev_events)
        evidence.append(ev.model_copy(update={"summary": text[:300]}))
    decision = decision.model_copy(
        update={
            "root_cause_summary": summary,
            "evidence": evidence,
            "guardrail_events": sorted(set(decision.guardrail_events + events)),
        }
    )
    decision = apply_action_allowlist(decision, alert)
    decision = apply_confidence_gate(decision, confidence_threshold)
    return decision
