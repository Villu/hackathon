"""MCP backend fixtures, schema cleaning, and one real stdio round-trip to the server."""

from __future__ import annotations

from gateway.agent.mcp_client import MCPToolClient, _clean_schema
from mcp_server.backends import MockBackend


def test_mock_backend_is_deterministic():
    b = MockBackend()
    a = b.query_logs("orders-api", 15, None, 20)
    c = b.query_logs("orders-api", 15, None, 20)
    assert a["lines"] == c["lines"]
    assert a["error_count"] > 0
    revs = b.get_deployment_history("VilluResourceGroup", "orders-api", 5)["revisions"]
    assert revs[0]["minutes_ago"] == 4 and revs[0]["traffic_weight"] == 100


def test_mock_backend_pattern_filter_and_unknown_resource():
    b = MockBackend()
    logs = b.query_logs("payments-worker", 30, "refused", 50)
    assert all("refused" in line["message"].lower() for line in logs["lines"])
    assert b.get_resource_state("VilluResourceGroup", "does-not-exist")["running_status"] == "Running"


def test_execute_action_never_executes():
    res = MockBackend().execute_action("restart_revision", "VilluResourceGroup", "orders-api", dry_run=False)
    assert res["ok"] and res["executed"] is False
    assert MockBackend().execute_action("delete_resource_group", "rg", "x", True)["ok"] is False


def test_clean_schema_for_gemini():
    schema = {
        "type": "object",
        "title": "Args",
        "additionalProperties": False,
        "properties": {
            "resource_name": {"type": "string", "title": "Resource Name"},
            "limit": {"type": "integer", "default": 5},
            "pattern": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "description": "filter"},
        },
        "required": ["resource_name"],
    }
    out = _clean_schema(schema)
    assert "title" not in out and "additionalProperties" not in out
    assert out["properties"]["pattern"] == {"type": "string", "nullable": True, "description": "filter"}
    assert "default" not in out["properties"]["limit"]


async def test_stdio_round_trip_to_real_server():
    client = MCPToolClient(env={"MOCK_AZURE": "true"})
    await client.start()
    try:
        names = {t.name for t in client.tools}
        assert names == {
            "get_resource_state",
            "get_deployment_history",
            "query_logs",
            "get_alert_history",
            "execute_action",
        }
        assert client.gemini_tools()[0].function_declarations
        result = await client.call(
            "query_logs", {"resource_name": "orders-api", "since_minutes": 15, "limit": 5}, timeout_ms=5000
        )
        assert result.ok, result.error
        assert result.content["resource_name"] == "orders-api"
        unknown = await client.call("nope", {}, timeout_ms=1000)
        assert not unknown.ok
    finally:
        await client.stop()
