"""Runtime configuration. Every knob in docs/04-software-spec.md section 7 lives here.

Values come from environment variables or a `.env` file in the working directory.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM -------------------------------------------------------------
    llm_provider: Literal["gemini", "azure_openai", "mock"] = "gemini"
    gemini_api_key: str | None = None
    gemini_primary_model: str = "gemini-2.5-flash"
    gemini_fast_model: str = "gemini-3.1-flash-lite"
    gemini_thinking_budget: int = 0  # 0 = no thinking (fast); -1 = model default
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_key: str | None = None

    # --- Azure (MCP tools) -----------------------------------------------
    mock_azure: bool = True
    azure_subscription_id: str = "e419a266-2639-4134-9ded-7a777b020ae9"  # GPT Initium
    azure_resource_group: str = "VilluResourceGroup"
    log_analytics_workspace_id: str | None = None

    # --- Stream ----------------------------------------------------------
    stream_source: Literal["rest", "kafka"] = "rest"
    kafka_bootstrap: str = "localhost:19092"
    kafka_alerts_topic: str = "alerts"
    kafka_decisions_topic: str = "decisions"
    decision_webhook_url: str | None = None

    # --- Reliability -----------------------------------------------------
    llm_primary_budget_ms: int = 3000
    llm_fast_budget_ms: int = 2000
    enrich_deadline_ms: int = 15_000
    confidence_threshold: float = 0.7
    llm_rps: float = 5.0
    llm_burst: int = 10
    cb_failures: int = 5
    cb_window_s: float = 30.0
    cb_half_open_after_s: float = 10.0
    max_tool_rounds: int = 4
    tool_timeout_ms: int = 2500
    dedupe_window_s: int = 60
    queue_max: int = 1000
    workers: int = 8

    # --- Process ---------------------------------------------------------
    mcp_enabled: bool = True
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
