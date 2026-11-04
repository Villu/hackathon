"""MCP server settings. Read from env / .env; the gateway passes its environment through."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mock_azure: bool = True
    azure_subscription_id: str = "e419a266-2639-4134-9ded-7a777b020ae9"
    azure_resource_group: str = "VilluResourceGroup"
    log_analytics_workspace_id: str | None = None
    tool_timeout_ms: int = 2500


@lru_cache
def get_mcp_settings() -> MCPSettings:
    return MCPSettings()
