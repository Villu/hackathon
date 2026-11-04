"""MCP client: spawns the tool server (`python -m mcp_server.server`) over stdio, lists its
tools, converts them to Gemini function declarations and executes calls with a timeout.

Honors chaos `mcp_down`. Never raises from `call()` — it returns ToolResult(ok=False).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from google.genai import types as gtypes
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from gateway.logs import log_event
from gateway.models import ToolCallRecord
from gateway.reliability.chaos import chaos

logger = logging.getLogger("gateway.mcp")


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolResult:
    tool: str
    ok: bool
    content: Any = None
    error: str | None = None
    latency_ms: int = 0
    args: dict[str, Any] = field(default_factory=dict)

    def record(self) -> ToolCallRecord:
        return ToolCallRecord(tool=self.tool, args=self.args, latency_ms=self.latency_ms, ok=self.ok, error=self.error)

    def for_model(self) -> dict[str, Any]:
        """What the LLM gets back. Errors are structured, never exceptions."""
        if self.ok:
            return {"result": self.content}
        return {"error": self.error or "tool failed"}


class MCPToolClient:
    def __init__(self, server_args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        self._server_args = server_args or ["-m", "mcp_server.server"]
        self._env = env
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: list[ToolSpec] = []
        self.started = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=self._server_args,
            env={**os.environ, **(self._env or {})},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listed = await self._session.list_tools()
        self._tools = [ToolSpec(t.name, t.description or "", _input_schema(t)) for t in listed.tools]
        self.started = True
        log_event(logger, "mcp_started", tools=[t.name for t in self._tools])

    async def stop(self) -> None:
        if self._stack:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001 — shutdown must not fail the app
                logger.debug("mcp stop raised", exc_info=True)
        self.started = False

    # ------------------------------------------------------------------ tools
    @property
    def tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def gemini_tools(self) -> list[gtypes.Tool]:
        decls = [
            gtypes.FunctionDeclaration(
                name=t.name, description=t.description[:1000], parameters=_clean_schema(t.input_schema)
            )
            for t in self._tools
        ]
        return [gtypes.Tool(function_declarations=decls)] if decls else []

    async def call(self, name: str, args: dict[str, Any], *, timeout_ms: int) -> ToolResult:
        t0 = time.perf_counter()
        if chaos.mcp_down:
            return ToolResult(name, False, error="chaos: mcp_down", latency_ms=_ms(t0), args=args)
        if not self._session:
            return ToolResult(name, False, error="mcp not started", latency_ms=_ms(t0), args=args)
        if name not in {t.name for t in self._tools}:
            return ToolResult(name, False, error=f"unknown tool {name!r}", latency_ms=_ms(t0), args=args)
        try:
            res = await asyncio.wait_for(self._session.call_tool(name, args), timeout=timeout_ms / 1000)
        except TimeoutError:
            return ToolResult(name, False, error=f"timeout after {timeout_ms} ms", latency_ms=_ms(t0), args=args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(name, False, error=str(exc)[:300], latency_ms=_ms(t0), args=args)
        content = _extract_content(res)
        ok = not (getattr(res, "is_error", None) or getattr(res, "isError", False))
        result = ToolResult(
            name, ok, content=content, error=None if ok else str(content)[:300], latency_ms=_ms(t0), args=args
        )
        log_event(logger, "tool_call", tool=name, ok=ok, latency_ms=result.latency_ms)
        return result


# ---------------------------------------------------------------------- helpers
_ALLOWED_SCHEMA_KEYS = {"type", "properties", "required", "description", "enum", "items", "nullable", "format"}


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Gemini accepts an OpenAPI subset: drop `title`, `default`, `additionalProperties`, `$defs`;
    fold `anyOf: [X, null]` into `nullable`."""
    if not schema:
        return None

    def clean(node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            merged = clean(options[0]) if options else {"type": "string"}
            if len(options) != len(node["anyOf"]):
                merged["nullable"] = True
            if "description" in node:
                merged["description"] = node["description"]
            return merged
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key not in _ALLOWED_SCHEMA_KEYS:
                continue
            if key == "properties":
                out[key] = {k: clean(v) for k, v in value.items()}
            elif key == "items":
                out[key] = clean(value)
            else:
                out[key] = value
        if out.get("type") == "object" and "properties" not in out:
            out["properties"] = {}
        return out

    cleaned = clean(schema)
    return cleaned if cleaned.get("properties") else None


def _input_schema(tool: Any) -> dict[str, Any]:
    """mcp 2.x uses snake_case (`input_schema`), 1.x camelCase (`inputSchema`)."""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}


def _extract_content(res: Any) -> Any:
    structured = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    if structured:
        return structured
    texts = []
    for block in getattr(res, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None:
            continue
        try:
            texts.append(json.loads(text))
        except json.JSONDecodeError:
            texts.append(text)
    if len(texts) == 1:
        return texts[0]
    return texts


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
