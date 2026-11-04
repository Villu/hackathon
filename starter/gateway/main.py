"""FastAPI entry point. Run: `uvicorn gateway.main:app --reload --port 8080`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from gateway.agent.llm import LLMClient
from gateway.agent.mcp_client import MCPToolClient
from gateway.config import Settings, get_settings
from gateway.logs import configure_logging, log_event
from gateway.pipeline import Pipeline
from gateway.reliability.chaos import chaos
from gateway.stream.normalise import NormalisationError, normalise

logger = logging.getLogger("gateway.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        llm = LLMClient(settings)
        mcp: MCPToolClient | None = None
        if settings.mcp_enabled:
            mcp = MCPToolClient()
            try:
                await mcp.start()
            except Exception as exc:  # noqa: BLE001 — the gateway must come up without tools
                log_event(logger, "mcp_start_failed", logging.ERROR, error=repr(exc)[:300])
        pipeline = Pipeline(settings, llm, mcp)
        await pipeline.start()
        kafka = None
        if settings.stream_source == "kafka":
            from gateway.stream.kafka import KafkaAlertSource

            kafka = KafkaAlertSource(pipeline, settings)
            await kafka.start()
        app.state.pipeline = pipeline
        app.state.settings = settings
        log_event(
            logger,
            "gateway_started",
            provider=llm.provider,
            mock_azure=settings.mock_azure,
            mcp=bool(mcp and mcp.started),
        )
        try:
            yield
        finally:
            if kafka:
                await kafka.stop()
            await pipeline.stop()
            if mcp:
                await mcp.stop()

    app = FastAPI(title="Resilient Agentic Gateway", version="0.1.0", lifespan=lifespan)

    # ------------------------------------------------------------------ ingress
    @app.post("/alerts", status_code=202)
    async def post_alerts(request: Request) -> JSONResponse:
        payload: Any = await request.json()
        try:
            alerts = normalise(payload)
        except (NormalisationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = request.app.state.pipeline.submit(alerts)
        return JSONResponse(
            status_code=202,
            content={
                "accepted": result.accepted,
                "duplicates": result.duplicates,
                "backpressured": result.backpressured,
            },
        )

    # ------------------------------------------------------------------ decisions
    @app.get("/decisions/{alert_id}")
    async def get_decision(alert_id: str, request: Request) -> Any:
        decision = request.app.state.pipeline.get(alert_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="unknown alert_id (or not yet decided)")
        return decision.model_dump(mode="json")

    @app.get("/decisions")
    async def list_decisions(request: Request, limit: int = Query(50, ge=1, le=500)) -> Any:
        return [d.model_dump(mode="json") for d in request.app.state.pipeline.recent(limit)]

    # ------------------------------------------------------------------ metrics / health
    @app.get("/metrics")
    async def metrics(request: Request, format: str | None = None) -> Any:
        pipeline: Pipeline = request.app.state.pipeline
        snap = pipeline.metrics.snapshot(
            circuit_breaker_state=pipeline.health()["circuit_breaker_state"],
            rate_limited=pipeline.bucket.rejected,
            queue_depth=pipeline.queue.qsize(),
            chaos=chaos.to_dict(),
        )
        if format == "prom":
            return PlainTextResponse(pipeline.metrics.to_prometheus(snap))
        return snap

    @app.get("/health")
    async def health(request: Request) -> Any:
        return {"status": "ok", **request.app.state.pipeline.health(), "chaos": chaos.to_dict()}

    # ------------------------------------------------------------------ chaos (keep it!)
    @app.post("/chaos")
    async def set_chaos(payload: dict[str, Any]) -> Any:
        chaos.update(payload or {})
        log_event(logger, "chaos_updated", **chaos.to_dict())
        return chaos.to_dict()

    @app.get("/chaos")
    async def get_chaos() -> Any:
        return chaos.to_dict()

    return app


app = create_app()
