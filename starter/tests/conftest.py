"""Test configuration: mock LLM, no MCP subprocess (except the explicit integration test)."""

from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("MCP_ENABLED", "false")
os.environ.setdefault("MOCK_AZURE", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("GEMINI_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gateway.config import Settings  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.models import Alert, Environment, ResourceRef, Severity  # noqa: E402
from gateway.reliability.chaos import chaos  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_provider="mock", mcp_enabled=False, mock_azure=True, _env_file=None)


@pytest.fixture
def client(settings: Settings):
    chaos.update({})
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    chaos.update({})


def make_alert(
    name: str = "HighErrorRate",
    severity: Severity = Severity.critical,
    env: Environment = Environment.prod,
    resource: str = "orders-api",
    alert_id: str = "a-test-0001",
    **kw,
) -> Alert:
    return Alert(
        alert_id=alert_id,
        name=name,
        severity=severity,
        resource=ResourceRef(name=resource, environment=env),
        annotations={"summary": f"{name} on {resource}"},
        **kw,
    )
