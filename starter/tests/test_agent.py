"""Behaviour the finished agent loop must have (Sprint 1). All xfail until TriageAgent.run is done."""

from __future__ import annotations

import pytest
from google.genai import types as gtypes

from gateway.agent.llm import LLMClient
from gateway.agent.mcp_client import ToolResult
from gateway.agent.triage_agent import Deadline, TriageAgent
from gateway.config import Settings
from gateway.models import DecisionSource, RootCauseCategory
from tests.conftest import make_alert


class FakeMCP:
    """Stands in for MCPToolClient: two tools, records calls."""

    started = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def gemini_tools(self):
        decls = [
            gtypes.FunctionDeclaration(
                name="get_deployment_history",
                description="d",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_group": {"type": "string"},
                        "resource_name": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
            ),
            gtypes.FunctionDeclaration(
                name="query_logs",
                description="d",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_name": {"type": "string"},
                        "since_minutes": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                },
            ),
        ]
        return [gtypes.Tool(function_declarations=decls)]

    async def call(self, name: str, args: dict, *, timeout_ms: int) -> ToolResult:
        self.calls.append((name, args))
        return ToolResult(name, True, content={"ok": True, "tool": name}, latency_ms=3, args=args)


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_provider="mock", mcp_enabled=False, _env_file=None)


@pytest.mark.xfail(reason="TODO(team): implement TriageAgent.run", strict=False)
async def test_agent_returns_valid_draft_without_tools(settings):
    agent = TriageAgent(LLMClient(settings), mcp=None, settings=settings)
    result = await agent.run(make_alert(), Deadline(5000))
    assert result is not None
    assert result.draft.root_cause_category is RootCauseCategory.deployment_regression
    assert result.source is DecisionSource.agent


@pytest.mark.xfail(reason="TODO(team): implement TriageAgent.run", strict=False)
async def test_agent_calls_tools_and_records_them(settings):
    mcp = FakeMCP()
    agent = TriageAgent(LLMClient(settings), mcp=mcp, settings=settings)
    result = await agent.run(make_alert(), Deadline(5000))
    assert result is not None
    called = {name for name, _ in mcp.calls}
    assert {"get_deployment_history", "query_logs"} <= called
    assert {tc.tool for tc in result.tool_calls} == called
    assert all(tc.ok for tc in result.tool_calls)


async def test_agent_respects_expired_deadline(settings):
    agent = TriageAgent(LLMClient(settings), mcp=FakeMCP(), settings=settings)
    result = await agent.run(make_alert(), Deadline(0))
    assert result is None
