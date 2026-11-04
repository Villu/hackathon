"""Orchestration: ingest → dedupe → Phase 0 (deterministic, provisional) → Phase 1 (agent,
final) with guardrails. Bounded queue + worker pool so the stream is never blocked.

Sprint 2 TODOs for the team are marked inline. The reliability primitives already exist in
gateway.reliability; this file is where they get wired in.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass

from gateway.agent.llm import LLMClient, LLMError
from gateway.agent.mcp_client import MCPToolClient
from gateway.agent.triage_agent import Deadline, TriageAgent
from gateway.config import Settings
from gateway.logs import log_event
from gateway.models import Alert, AlertStatus, Phase, Severity, TriageDecision
from gateway.reliability.circuit_breaker import CircuitBreaker
from gateway.reliability.fallback import deterministic_triage
from gateway.reliability.guardrails import apply_guardrails
from gateway.reliability.rate_limiter import TokenBucket
from gateway.scoring.metrics import Metrics
from gateway.scoring.scoring import score_decision

logger = logging.getLogger("gateway.pipeline")


@dataclass
class SubmitResult:
    accepted: list[str]
    duplicates: list[str]
    backpressured: list[str]


class Pipeline:
    def __init__(
        self, settings: Settings, llm: LLMClient, mcp: MCPToolClient | None, metrics: Metrics | None = None
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.mcp = mcp
        self.agent = TriageAgent(llm, mcp, settings)
        self.metrics = metrics or Metrics()
        self.bucket = TokenBucket(settings.llm_rps, settings.llm_burst)
        self.breaker_llm = CircuitBreaker(
            "llm", settings.cb_failures, settings.cb_window_s, settings.cb_half_open_after_s
        )
        self.breaker_mcp = CircuitBreaker(
            "mcp", settings.cb_failures, settings.cb_window_s, settings.cb_half_open_after_s
        )
        self.decisions: dict[str, TriageDecision] = {}
        self.alerts: dict[str, Alert] = {}
        self._order: deque[str] = deque(maxlen=5000)
        self._seen: dict[str, float] = {}
        self.queue: asyncio.Queue[tuple[Alert, float]] = asyncio.Queue(maxsize=settings.queue_max)
        self._workers: list[asyncio.Task] = []

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._worker(i), name=f"triage-worker-{i}") for i in range(self.settings.workers)
        ]

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ------------------------------------------------------------------ ingress
    def submit(self, alerts: list[Alert]) -> SubmitResult:
        """Synchronous and fast (< 1 ms per alert). Called from the HTTP handler / Kafka consumer."""
        now = time.monotonic()
        result = SubmitResult([], [], [])
        self._expire_seen(now)
        for alert in alerts:
            self.metrics.inc("alerts_received")
            if alert.alert_id in self._seen:
                self.metrics.inc("alerts_deduplicated")
                result.duplicates.append(alert.alert_id)
                continue
            self._seen[alert.alert_id] = now
            self.alerts[alert.alert_id] = alert
            self._order.append(alert.alert_id)
            try:
                self.queue.put_nowait((alert, time.perf_counter()))
                result.accepted.append(alert.alert_id)
            except asyncio.QueueFull:
                # Backpressure: Phase 0 only, never drop the alert silently.
                decision = deterministic_triage(alert, phase=Phase.final)
                decision.guardrail_events.append("backpressure")
                self._store(decision, alert)
                self.metrics.inc("backpressure")
                result.backpressured.append(alert.alert_id)
        return result

    # ------------------------------------------------------------------ processing
    async def _worker(self, idx: int) -> None:
        while True:
            alert, ingested_at = await self.queue.get()
            try:
                await self._process(alert, ingested_at)
            except Exception:  # noqa: BLE001 — a worker must never die
                logger.exception("worker failed", extra={"fields": {"alert_id": alert.alert_id, "worker": idx}})
                if alert.alert_id not in self.decisions:
                    self._store(deterministic_triage(alert, phase=Phase.final), alert)
            finally:
                self.queue.task_done()

    async def _process(self, alert: Alert, ingested_at: float) -> None:
        # Phase 0 — deterministic provisional decision. Always. Fast.
        provisional = deterministic_triage(alert, phase=Phase.provisional)
        provisional.latency_ms = _since(ingested_at)
        self._store(provisional, alert)

        if alert.status is AlertStatus.resolved or alert.severity is Severity.info:
            self._store(provisional.model_copy(update={"phase": Phase.final}), alert)
            return

        await self._agent_phase(alert, provisional, ingested_at)

    async def _agent_phase(self, alert: Alert, provisional: TriageDecision, ingested_at: float) -> None:
        events: list[str] = []

        # TODO(team) Sprint 2 — gate the AI path before spending a token:
        #   if not self.bucket.try_acquire():            events.append("rate_limited"); ...fallback
        #   if not self.breaker_llm.allow():             events.append("circuit_open_llm"); ...fallback
        #   if self.mcp and not self.breaker_mcp.allow(): run the agent without tools, or fallback
        # and record self.breaker_llm.record_success()/record_failure() around the agent call.
        # Idempotency and a decision cache for identical fingerprints also belong here.

        deadline = Deadline(self.settings.enrich_deadline_ms)
        result = None
        try:
            result = await asyncio.wait_for(
                self.agent.run(alert, deadline), timeout=self.settings.enrich_deadline_ms / 1000 + 0.5
            )
        except TimeoutError:
            events.append("agent_deadline_exceeded")
        except LLMError as exc:
            events.append("llm_error")
            log_event(logger, "agent_llm_error", logging.WARNING, alert_id=alert.alert_id, error=str(exc)[:200])
        except Exception as exc:  # noqa: BLE001
            events.append("agent_exception")
            log_event(logger, "agent_exception", logging.ERROR, alert_id=alert.alert_id, error=repr(exc)[:200])

        if result is None:
            if not events:
                events.append("agent_unavailable")
            final = provisional.model_copy(
                update={
                    "phase": Phase.final,
                    "latency_ms": _since(ingested_at),
                    "guardrail_events": sorted(set(provisional.guardrail_events + events)),
                }
            )
            self._store(final, alert)
            return

        decision = TriageDecision.from_draft(
            alert,
            result.draft,
            source=result.source,
            phase=Phase.final,
            tool_calls=result.tool_calls,
            latency_ms=_since(ingested_at),
        )
        decision.action_executed = any(
            tc.tool == "execute_action" and tc.ok and tc.args.get("dry_run", True) is False for tc in result.tool_calls
        )
        decision.guardrail_events = sorted(set(events))
        decision = apply_guardrails(decision, alert, confidence_threshold=self.settings.confidence_threshold)
        self._store(decision, alert)

    # ------------------------------------------------------------------ store / read
    def _store(self, decision: TriageDecision, alert: Alert) -> None:
        first = decision.alert_id not in self.decisions
        decision.scores = score_decision(decision, alert)
        self.decisions[decision.alert_id] = decision
        self.metrics.record_decision(decision, first=first)
        log_event(
            logger,
            "decision",
            alert_id=decision.alert_id,
            phase=decision.phase.value,
            source=decision.decision_source.value,
            action=decision.recommended_action.value,
            root_cause=decision.root_cause_category.value,
            confidence=decision.confidence,
            latency_ms=decision.latency_ms,
            guardrails=decision.guardrail_events,
        )
        # TODO(team, optional): publish to DECISION_WEBHOOK_URL or Kafka topic `decisions`.

    def get(self, alert_id: str) -> TriageDecision | None:
        return self.decisions.get(alert_id)

    def recent(self, limit: int = 50) -> list[TriageDecision]:
        ids = list(self._order)[-limit:]
        return [self.decisions[i] for i in reversed(ids) if i in self.decisions]

    def health(self) -> dict:
        return {
            "queue_depth": self.queue.qsize(),
            "queue_max": self.settings.queue_max,
            "workers": len(self._workers),
            "circuit_breaker_state": {"llm": self.breaker_llm.state.value, "mcp": self.breaker_mcp.state.value},
            "rate_limiter": {"available_tokens": round(self.bucket.available, 2), "rejected": self.bucket.rejected},
            "mcp": {
                "started": bool(self.mcp and self.mcp.started),
                "tools": [t.name for t in self.mcp.tools] if self.mcp else [],
            },
            "llm": {"provider": self.llm.provider, "configured": self.llm.configured},
        }

    def _expire_seen(self, now: float) -> None:
        if len(self._seen) < 512:
            return
        cutoff = now - self.settings.dedupe_window_s
        for key in [k for k, ts in self._seen.items() if ts < cutoff]:
            del self._seen[key]


def _since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
