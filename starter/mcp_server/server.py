"""MCP server (MCPServer / FastMCP) with the five triage tools (spec 4.3). Transport: stdio.

    python -m mcp_server.server              # run as MCP server (the gateway does this for you)
    python -m mcp_server.server --self-test  # call every tool once and print the results

Tool names and argument names are part of the eval contract — do not rename them.
Adding tools is fine as long as they stay within the approved endpoints (rule of the day).
Logging goes to stderr; stdout belongs to the MCP transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from mcp_server.backends import AzureBackend, Backend, MockBackend
from mcp_server.config import get_mcp_settings

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mcp_server")

mcp = MCPServer("azure-triage-tools")
_backend: Backend | None = None


def backend() -> Backend:
    global _backend
    if _backend is None:
        cfg = get_mcp_settings()
        if cfg.mock_azure:
            _backend = MockBackend()
            logger.info("backend=mock")
        else:
            _backend = AzureBackend(cfg.azure_subscription_id, cfg.log_analytics_workspace_id)
            logger.info("backend=azure subscription=%s", cfg.azure_subscription_id)
    return _backend


@mcp.tool()
async def get_resource_state(resource_group: str, resource_name: str) -> dict[str, Any]:
    """Current state of a Container App: provisioning/running status, replicas, CPU/memory,
    latest revision and last restart time."""
    return await asyncio.to_thread(backend().get_resource_state, resource_group, resource_name)


@mcp.tool()
async def get_deployment_history(resource_group: str, resource_name: str, limit: int = 5) -> dict[str, Any]:
    """Recent revisions/deployments of a Container App, newest first: image tag, created time,
    minutes ago, traffic weight, health and who deployed."""
    return await asyncio.to_thread(
        backend().get_deployment_history, resource_group, resource_name, max(1, min(limit, 20))
    )


@mcp.tool()
async def query_logs(
    resource_name: str, since_minutes: int = 15, pattern: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """Recent log lines for a resource from Log Analytics (or fixtures), newest first, with an
    error count. `pattern` filters lines containing the text (case-insensitive)."""
    return await asyncio.to_thread(
        backend().query_logs, resource_name, max(1, min(since_minutes, 1440)), pattern, max(1, min(limit, 200))
    )


@mcp.tool()
async def get_alert_history(resource_name: str, hours: int = 24) -> dict[str, Any]:
    """Alerts fired on the resource in the last N hours (is this a repeat offender?)."""
    return await asyncio.to_thread(backend().get_alert_history, resource_name, max(1, min(hours, 168)))


@mcp.tool()
async def execute_action(action: str, resource_group: str, resource_name: str, dry_run: bool = True) -> dict[str, Any]:
    """Request a remediation (restart_revision, rollback_deployment, scale_out, silence_alert,
    acknowledge). Always a dry run in prod. The starter never mutates Azure."""
    return await asyncio.to_thread(backend().execute_action, action, resource_group, resource_name, dry_run)


async def _self_test() -> None:
    b = backend()
    rg = get_mcp_settings().azure_resource_group
    checks = {
        "get_resource_state": lambda: b.get_resource_state(rg, "orders-api"),
        "get_deployment_history": lambda: b.get_deployment_history(rg, "orders-api", 5),
        "query_logs": lambda: b.query_logs("orders-api", 15, None, 10),
        "get_alert_history": lambda: b.get_alert_history("orders-api", 24),
        "execute_action": lambda: b.execute_action("restart_revision", rg, "orders-api", True),
    }
    for name, fn in checks.items():
        try:
            result = await asyncio.to_thread(fn)
            status = "ERR " if isinstance(result, dict) and "error" in result else "ok  "
        except Exception as exc:  # noqa: BLE001
            result, status = {"error": repr(exc)}, "FAIL"
        print(f"{status} {name}: {json.dumps(result, default=str)[:300]}")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        asyncio.run(_self_test())
    else:
        mcp.run(transport="stdio")
