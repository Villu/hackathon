"""End-to-end through the HTTP API with the mock LLM and no MCP subprocess."""

from __future__ import annotations

import time

from simulator.scenarios import cpu_spike, deployment_regression, injection, noise, to_azure, to_prometheus


def _wait_final(client, alert_id: str, timeout_s: float = 5.0) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = client.get(f"/decisions/{alert_id}")
        if r.status_code == 200:
            last = r.json()
            if last["phase"] == "final":
                return last
        time.sleep(0.02)
    raise AssertionError(f"no final decision for {alert_id}: {last}")


def test_alert_is_accepted_and_falls_back_to_deterministic(client):
    client.post("/chaos", json={"llm_down": True})  # force the fallback path, agent or not
    alert = cpu_spike()
    r = client.post("/alerts", json=alert)
    assert r.status_code == 202
    assert r.json()["accepted"] == [alert["alert_id"]]
    d = _wait_final(client, alert["alert_id"])
    assert d["decision_source"] == "deterministic_fallback"
    assert d["recommended_action"] == "escalate_to_oncall"
    assert d["root_cause_category"] == "resource_exhaustion"
    assert d["scores"]["safety_ok"] is True
    assert d["latency_ms"] < 1000


def test_duplicate_alert_is_deduplicated(client):
    alert = deployment_regression()
    client.post("/alerts", json=alert)
    r = client.post("/alerts", json=alert)
    assert r.json()["duplicates"] == [alert["alert_id"]]


def test_prometheus_and_azure_shapes_are_accepted(client):
    r1 = client.post("/alerts", json=to_prometheus(deployment_regression()))
    r2 = client.post("/alerts", json=to_azure(cpu_spike()))
    assert r1.status_code == 202 and len(r1.json()["accepted"]) == 1
    assert r2.status_code == 202 and len(r2.json()["accepted"]) == 1


def test_bad_payload_is_400(client):
    assert client.post("/alerts", json={"nonsense": True}).status_code == 400


def test_info_alert_is_final_immediately(client):
    alert = noise()
    client.post("/alerts", json=alert)
    d = _wait_final(client, alert["alert_id"], timeout_s=2)
    assert d["recommended_action"] == "no_action"


def test_injection_alert_never_yields_unsafe_prod_action(client):
    alert = injection("prod")
    client.post("/alerts", json=alert)
    d = _wait_final(client, alert["alert_id"])
    assert d["recommended_action"] in {"no_action", "acknowledge", "escalate_to_oncall"}
    assert not any(tc["tool"] == "execute_action" for tc in d["tool_calls"])


def test_metrics_health_and_chaos_endpoints(client):
    alert = cpu_spike()
    client.post("/alerts", json=alert)
    _wait_final(client, alert["alert_id"])
    m = client.get("/metrics").json()
    assert m["counters"]["alerts_received"] >= 1
    assert m["latency_ms"]["p95"] is not None
    assert m["schema_pass_rate"] == 1.0
    prom = client.get("/metrics", params={"format": "prom"}).text
    assert "gateway_alerts_received" in prom

    h = client.get("/health").json()
    assert h["status"] == "ok" and h["circuit_breaker_state"]["llm"] == "closed"

    assert client.post("/chaos", json={"llm_down": True}).json()["llm_down"] is True
    assert client.get("/chaos").json()["llm_down"] is True
    assert client.post("/chaos", json={}).json()["llm_down"] is False


def test_burst_is_acked_fast_and_all_decided(client):
    alerts = [cpu_spike() for _ in range(50)]
    t0 = time.perf_counter()
    r = client.post("/alerts", json=alerts)
    ack_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 202 and len(r.json()["accepted"]) == 50
    assert ack_ms < 500, f"ack took {ack_ms:.0f} ms for 50 alerts"
    for a in alerts:
        _wait_final(client, a["alert_id"], timeout_s=10)
