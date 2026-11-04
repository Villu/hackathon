"""LLM client with a tiny provider abstraction (Gemini, mock) and chaos hooks.

The agent loop talks to `LLMClient.complete()` only. Chaos faults (delay, garbage, down) are
applied here so that every team's gateway experiences the same failures in the chaos round.

Run `python -m gateway.agent.llm --ping` to check your key and model.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from google.genai import types as gtypes

from gateway.config import Settings, get_settings
from gateway.logs import log_event
from gateway.reliability.chaos import chaos

logger = logging.getLogger("gateway.llm")


class LLMError(RuntimeError):
    pass


class LLMTimeout(LLMError):
    pass


@dataclass
class FunctionCall:
    name: str
    args: dict[str, Any]


@dataclass
class LLMResult:
    text: str | None
    function_calls: list[FunctionCall] = field(default_factory=list)
    content: gtypes.Content | None = None  # append this to the history before tool responses
    latency_ms: int = 0
    model: str = ""


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.llm_provider
        self._client = None
        if self.provider == "gemini" and self.settings.gemini_api_key:
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        elif self.provider == "azure_openai":
            # TODO(team, optional): OpenAI-compatible call against the APIM endpoint in
            # VilluResourceGroup. Keep the LLMResult contract identical.
            raise LLMError("azure_openai provider not implemented in the starter")

    @property
    def configured(self) -> bool:
        return self.provider == "mock" or self._client is not None

    # ------------------------------------------------------------------ public
    async def complete(
        self,
        *,
        model: str,
        system: str,
        contents: list[gtypes.Content],
        tools: list[gtypes.Tool] | None = None,
        response_schema: type | None = None,
        timeout_ms: int,
        temperature: float = 0.1,
    ) -> LLMResult:
        """One model call. Raises LLMTimeout / LLMError. Honors chaos faults."""
        t0 = time.perf_counter()
        if chaos.llm_down:
            raise LLMError("chaos: llm_down")
        if chaos.llm_delay_ms:
            await asyncio.sleep(min(chaos.llm_delay_ms, timeout_ms + 50) / 1000)
            if chaos.llm_delay_ms >= timeout_ms:
                raise LLMTimeout(f"chaos: delayed {chaos.llm_delay_ms} ms > budget {timeout_ms} ms")
        if chaos.llm_garbage:
            return LLMResult(text=_GARBAGE, latency_ms=_ms(t0), model=model)

        if self.provider == "mock":
            return await self._mock(model, contents, tools, t0)
        if self._client is None:
            raise LLMError("GEMINI_API_KEY is not set (or use LLM_PROVIDER=mock)")

        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            tools=tools or None,
            automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(disable=True) if tools else None,
            response_mime_type="application/json" if response_schema else None,
            response_schema=response_schema,
            thinking_config=gtypes.ThinkingConfig(thinking_budget=self.settings.gemini_thinking_budget)
            if self.settings.gemini_thinking_budget >= 0
            else None,
        )
        try:
            resp = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=model, contents=contents, config=config),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError as exc:
            raise LLMTimeout(f"{model} exceeded {timeout_ms} ms") from exc
        except Exception as exc:  # network, quota, safety block ...
            raise LLMError(f"{model}: {exc}") from exc

        calls = [FunctionCall(fc.name, dict(fc.args or {})) for fc in (resp.function_calls or [])]
        content = resp.candidates[0].content if resp.candidates else None
        text = resp.text if not calls else None
        result = LLMResult(text=text, function_calls=calls, content=content, latency_ms=_ms(t0), model=model)
        log_event(logger, "llm_call", model=model, latency_ms=result.latency_ms, function_calls=[c.name for c in calls])
        return result

    # ------------------------------------------------------------------ mock
    async def _mock(self, model: str, contents: list[gtypes.Content], tools, t0: float) -> LLMResult:
        """Deterministic stand-in used by tests and `LLM_PROVIDER=mock`.

        First turn with tools available → asks for `get_deployment_history` and `query_logs`.
        After tool responses (or without tools) → returns a plausible TriageDraft JSON.
        """
        await asyncio.sleep(0.02)
        has_tool_response = any(part.function_response is not None for c in contents for part in (c.parts or []))
        if tools and not has_tool_response:
            resource = _extract_resource_name(contents)
            parts = [
                gtypes.Part.from_function_call(
                    name="get_deployment_history",
                    args={"resource_group": "VilluResourceGroup", "resource_name": resource, "limit": 5},
                ),
                gtypes.Part.from_function_call(
                    name="query_logs",
                    args={"resource_name": resource, "since_minutes": 15, "limit": 50},
                ),
            ]
            content = gtypes.Content(role="model", parts=parts)
            return LLMResult(
                text=None,
                function_calls=[FunctionCall(p.function_call.name, dict(p.function_call.args)) for p in parts],
                content=content,
                latency_ms=_ms(t0),
                model=model,
            )
        draft = {
            "severity_assessment": "high",
            "root_cause_category": "deployment_regression",
            "root_cause_summary": "Mock: error rate rose right after the latest revision; logs show 5xx from the new image.",  # noqa: E501
            "confidence": 0.82,
            "recommended_action": "rollback_deployment",
            "evidence": [
                {
                    "tool": "get_deployment_history",
                    "summary": "Revision deployed 4 minutes before alert.",
                    "ref": "rev-0007",
                },
                {"tool": "query_logs", "summary": "37 HTTP 500 lines in the last 15 minutes.", "ref": "query_logs"},
            ],
        }
        text = json.dumps(draft)
        return LLMResult(
            text=text,
            content=gtypes.Content(role="model", parts=[gtypes.Part.from_text(text=text)]),
            latency_ms=_ms(t0),
            model=model,
        )


# ---------------------------------------------------------------------- helpers
_GARBAGE = (
    '```json\n{"severity_assessment": "catastrophic", "root_cause_category": "gremlins", '
    '"root_cause_summary": "' + "A" * 4000 + '", "confidence": 1.7, "recommended_action": "delete_everything"'
)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _extract_resource_name(contents: list[gtypes.Content]) -> str:
    for c in contents:
        for part in c.parts or []:
            if part.text and '"name"' in part.text:
                try:
                    start = part.text.index("{")
                    data = json.loads(part.text[start : part.text.rindex("}") + 1])
                    return data.get("resource", {}).get("name", "orders-api")
                except (ValueError, json.JSONDecodeError):
                    continue
    return "orders-api"


async def _ping() -> None:
    settings = get_settings()
    client = LLMClient(settings)
    res = await client.complete(
        model=settings.gemini_primary_model,
        system="Reply with exactly one word.",
        contents=[gtypes.Content(role="user", parts=[gtypes.Part.from_text(text="Say: pong")])],
        timeout_ms=10_000,
    )
    print(f"provider={client.provider} model={res.model} latency_ms={res.latency_ms} text={res.text!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ping", action="store_true")
    if ap.parse_args().ping:
        asyncio.run(_ping())
