"""Rolling metrics served on GET /metrics (spec 6.1). In-memory, 5-minute window + totals."""

from __future__ import annotations

import time
from collections import Counter, deque
from typing import Any

from gateway.models import DecisionScores, TriageDecision


def percentile(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return ordered[idx]


class Metrics:
    def __init__(self, window_s: int = 300, clock=time.monotonic) -> None:
        self.window_s = window_s
        self._clock = clock
        self.started_at = time.time()
        self.counters: Counter[str] = Counter()
        self._first: deque[tuple[float, int]] = deque()
        self._enrich: deque[tuple[float, int]] = deque()
        self._scores: deque[tuple[float, DecisionScores]] = deque()

    # ------------------------------------------------------------------ record
    def inc(self, name: str, n: int = 1, **labels: Any) -> None:
        self.counters[_key(name, labels)] += n

    def record_decision(self, decision: TriageDecision, *, first: bool) -> None:
        now = self._clock()
        self.inc("decisions_emitted")
        self.inc("decisions_by_source", source=decision.decision_source.value, phase=decision.phase.value)
        for event in decision.guardrail_events:
            self.inc("guardrail_events", type=event)
        for tc in decision.tool_calls:
            self.inc("tool_calls", tool=tc.tool, ok=str(tc.ok).lower())
        if first:
            self._first.append((now, decision.latency_ms))
        else:
            self._enrich.append((now, decision.latency_ms))
        if decision.scores:
            self._scores.append((now, decision.scores))
            if not decision.scores.safety_ok:
                self.inc("safety_violations")
        self._trim(now)

    # ------------------------------------------------------------------ read
    def snapshot(self, **extra: Any) -> dict[str, Any]:
        now = self._clock()
        self._trim(now)
        first = [ms for _, ms in self._first]
        enrich = [ms for _, ms in self._enrich]
        scores = [s for _, s in self._scores]
        acc = [s.tool_call_accuracy for s in scores if s.tool_call_accuracy is not None]
        rc = [s.root_cause_match for s in scores if s.root_cause_match is not None]
        act = [s.action_match for s in scores if s.action_match is not None]
        return {
            "uptime_s": int(time.time() - self.started_at),
            "window_s": self.window_s,
            "counters": dict(sorted(self.counters.items())),
            "latency_ms": {
                "p50": percentile(first, 50),
                "p95": percentile(first, 95),
                "p99": percentile(first, 99),
                "n": len(first),
            },
            "enrichment_latency_ms": {"p50": percentile(enrich, 50), "p95": percentile(enrich, 95), "n": len(enrich)},
            "schema_pass_rate": _ratio([s.schema_valid for s in scores]),
            "safety_ok_rate": _ratio([s.safety_ok for s in scores]),
            "tool_call_accuracy": (sum(acc) / len(acc)) if acc else None,
            "root_cause_match_rate": _ratio(rc),
            "action_match_rate": _ratio(act),
            **extra,
        }

    def to_prometheus(self, snap: dict[str, Any]) -> str:
        lines: list[str] = []
        for key, value in snap["counters"].items():
            name, labels = _split_key(key)
            lines.append(f"gateway_{name}{labels} {value}")
        for group in ("latency_ms", "enrichment_latency_ms"):
            for q, v in snap[group].items():
                if q != "n" and v is not None:
                    lines.append(f'gateway_{group}{{quantile="{q}"}} {v}')
        for scalar in (
            "schema_pass_rate",
            "safety_ok_rate",
            "tool_call_accuracy",
            "root_cause_match_rate",
            "action_match_rate",
        ):
            if snap.get(scalar) is not None:
                lines.append(f"gateway_{scalar} {snap[scalar]}")
        for name, state in (snap.get("circuit_breaker_state") or {}).items():
            lines.append(f'gateway_circuit_breaker_open{{name="{name}"}} {1 if state == "open" else 0}')
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ internal
    def _trim(self, now: float) -> None:
        for dq in (self._first, self._enrich, self._scores):
            while dq and now - dq[0][0] > self.window_s:
                dq.popleft()


def _key(name: str, labels: dict[str, Any]) -> str:
    if not labels:
        return name
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{inner}}}"


def _split_key(key: str) -> tuple[str, str]:
    if "{" in key:
        name, rest = key.split("{", 1)
        return name, "{" + rest
    return key, ""


def _ratio(values: list[bool]) -> float | None:
    return (sum(1 for v in values if v) / len(values)) if values else None
