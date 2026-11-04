"""The tool-calling triage agent — Deliverable 1. THIS IS THE MAIN TODO FOR SPRINT 1.

Everything around the loop is provided: `LLMClient.complete()` (Gemini + chaos), the MCP
client (tool discovery, Gemini declarations, timed calls), prompts, `parse_draft()` and the
`Deadline` helper. Your job is `TriageAgent.run()`.

Contract: return an `AgentResult` (valid draft + tool call records) or `None` when the agent
could not produce a valid decision within its deadline. Never raise; the pipeline treats
`None` and exceptions the same way (fallback), but a clean `None` keeps the metrics honest.

The untouched starter returns None → every alert ends as `deterministic_fallback`.
tests/test_agent.py contains xfail tests describing the expected behaviour with the mock LLM.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from google.genai import types as gtypes

from gateway.agent.llm import LLMClient
from gateway.agent.mcp_client import MCPToolClient
from gateway.agent.prompts import SYSTEM_PROMPT, build_retry_prompt, build_user_prompt  # noqa: F401
from gateway.config import Settings
from gateway.models import Alert, DecisionSource, ToolCallRecord, TriageDraft
from gateway.reliability.guardrails import DraftParseError, parse_draft  # noqa: F401

logger = logging.getLogger("gateway.agent")


class Deadline:
    """Wall-clock budget for one alert. `remaining_ms()` never goes below 0."""

    def __init__(self, budget_ms: int) -> None:
        self._end = time.perf_counter() + budget_ms / 1000

    def remaining_ms(self) -> int:
        return max(0, int((self._end - time.perf_counter()) * 1000))

    def expired(self) -> bool:
        return self.remaining_ms() <= 0


@dataclass
class AgentResult:
    draft: TriageDraft
    source: DecisionSource
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    model: str = ""


class TriageAgent:
    def __init__(self, llm: LLMClient, mcp: MCPToolClient | None, settings: Settings) -> None:
        self.llm = llm
        self.mcp = mcp
        self.settings = settings

    async def run(self, alert: Alert, deadline: Deadline) -> AgentResult | None:
        """Investigate one alert with tools and return a validated draft.

        TODO(team) — suggested steps (each is a few lines):

        1. Build the conversation:
               contents = [gtypes.Content(role="user", parts=[gtypes.Part.from_text(text=build_user_prompt(alert))])]
           and the tool declarations: `tools = self.mcp.gemini_tools() if self.mcp and self.mcp.started else []`.

        2. Tool loop, at most `self.settings.max_tool_rounds` rounds and while not `deadline.expired()`:
               budget = min(self.settings.llm_primary_budget_ms, deadline.remaining_ms())
               res = await self.llm.complete(model=self.settings.gemini_primary_model, system=SYSTEM_PROMPT,
                                             contents=contents, tools=tools, timeout_ms=budget)
           If `res.function_calls` is empty → break (the model answered).
           Otherwise append `res.content` to `contents`, execute every call through
           `self.mcp.call(name, args, timeout_ms=self.settings.tool_timeout_ms)`, keep `result.record()`
           in a list, and append ONE user Content whose parts are
               gtypes.Part.from_function_response(name=call.name, response=result.for_model())
           for each call.

        3. Parse: `draft = parse_draft(res.text)`. On `DraftParseError` retry ONCE with the fast model:
           append a user part with `build_retry_prompt(str(err))`, call `complete()` with
           `model=self.settings.gemini_fast_model`, `tools=None`, `response_schema=TriageDraft`,
           `timeout_ms=self.settings.llm_fast_budget_ms`; parse again. Source becomes `agent_fast_model`.

        4. Return `AgentResult(draft=draft, source=..., tool_calls=records, model=res.model)`.
           Catch `LLMError`/`LLMTimeout` and return None (log the reason with alert_id).

        Sprint 2 ideas that belong in the pipeline, not here: rate limiting, circuit breaker,
        allowlist, confidence gate, idempotency.
        """
        _ = (alert, deadline, gtypes)  # keep linters quiet until implemented
        return None
