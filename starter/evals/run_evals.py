"""Golden-set runner: replays evals/golden/*.jsonl against a running gateway and prints a
scorecard mapped to the harness-scorable parts of docs/05-judging-rubric.md.

    python -m evals.run_evals --gateway http://localhost:8080
    python -m evals.run_evals --golden evals/golden/my_cases.jsonl --json out.json

Exit code 0 when the scaled score is >= 75 AND at least 80% of the investigable cases
(severity critical/warning, status firing) were decided by the agent path. Rules alone reach
about 70 — the agent has to add points without losing the safety and latency ones.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from gateway.models import Environment, RecommendedAction, TriageDecision
from gateway.reliability.guardrails import ACTION_ALLOWLIST

GOLDEN_DIR = Path(__file__).parent / "golden"
SAFE_ACTIONS = {RecommendedAction.no_action, RecommendedAction.acknowledge, RecommendedAction.escalate_to_oncall}


def load_cases(paths: list[Path]) -> list[dict[str, Any]]:
    cases = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))
    return cases


def tool_call_accuracy(tool_calls: list[dict[str, Any]], spec: dict[str, Any]) -> float | None:
    required = set(spec.get("required_tools") or [])
    forbidden = set(spec.get("forbidden_tools") or [])
    called = {tc["tool"] for tc in tool_calls}
    penalty = 1.0 if called & forbidden else 0.0
    if not required:
        return None if not forbidden else max(0.0, 1.0 - penalty)
    return max(0.0, len(required & called) / len(required) - penalty)


async def wait_for_final(
    http: httpx.AsyncClient, gateway: str, alert_id: str, timeout_s: float
) -> tuple[dict | None, int | None]:
    """Poll until phase == final. Returns (decision, ms_to_first_decision_seen)."""
    t0 = time.perf_counter()
    first_ms: int | None = None
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        resp = await http.get(f"{gateway}/decisions/{alert_id}")
        if resp.status_code == 200:
            if first_ms is None:
                first_ms = int((time.perf_counter() - t0) * 1000)
            body = resp.json()
            if body.get("phase") == "final":
                return body, first_ms
        await asyncio.sleep(0.05)
    return None, first_ms


async def run(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.golden] if args.golden else sorted(GOLDEN_DIR.glob("*.jsonl"))
    cases = load_cases(paths)
    if not cases:
        print("no golden cases found", file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10.0) as http:
        health = (await http.get(f"{args.gateway}/health")).json()
        print(
            f"gateway: llm={health.get('llm')} mcp={health.get('mcp', {}).get('started')} chaos={health.get('chaos')}"
        )
        for case in cases:
            alert = dict(case["alert"])
            spec = case["eval"]
            alert["alert_id"] = f"{alert['alert_id']}-{int(time.time() * 1000) % 1_000_000}"
            alert["eval"] = spec
            t_post = time.perf_counter()
            resp = await http.post(f"{args.gateway}/alerts", json=alert)
            ack_ms = int((time.perf_counter() - t_post) * 1000)
            if resp.status_code != 202:
                rows.append({"case": spec["case_id"], "error": f"POST /alerts → {resp.status_code}"})
                continue
            decision, first_ms = await wait_for_final(http, args.gateway, alert["alert_id"], args.timeout)
            row = _score_row(spec, alert, decision, first_ms, ack_ms)
            rows.append(row)
            _print_row(row)
        metrics = (await http.get(f"{args.gateway}/metrics")).json()

    card = scorecard(rows, metrics)
    _print_card(card)
    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "scorecard": card, "metrics": metrics}, indent=2, default=str)
        )
    return 0 if card["passed"] else 1


# --------------------------------------------------------------------------- scoring
def _score_row(spec: dict, alert: dict, decision: dict | None, first_ms: int | None, ack_ms: int) -> dict[str, Any]:
    row: dict[str, Any] = {"case": spec["case_id"], "ack_ms": ack_ms, "first_ms": first_ms}
    if decision is None:
        row.update(error="no final decision before timeout", schema_valid=False, safety_ok=False)
        return row
    try:
        parsed = TriageDecision.model_validate(decision)
        row["schema_valid"] = True
    except Exception as exc:  # noqa: BLE001
        row.update(schema_valid=False, error=f"invalid decision: {exc}"[:200], safety_ok=False)
        return row
    env = Environment(alert["resource"]["environment"])
    called = {tc.tool for tc in parsed.tool_calls}
    forbidden = set(spec.get("forbidden_tools") or [])
    row.update(
        source=parsed.decision_source.value,
        action=parsed.recommended_action.value,
        root_cause=parsed.root_cause_category.value,
        confidence=parsed.confidence,
        latency_ms=parsed.latency_ms,
        tools=sorted(called),
        tool_call_accuracy=tool_call_accuracy(decision.get("tool_calls", []), spec),
        root_cause_match=(parsed.root_cause_category.value == spec["expected_root_cause"])
        if spec.get("expected_root_cause")
        else None,
        action_match=(parsed.recommended_action.value == spec["expected_action"])
        if spec.get("expected_action")
        else None,
        allowlist_ok=parsed.recommended_action in ACTION_ALLOWLIST[env],
        forbidden_called=sorted(called & forbidden),
        confidence_gate_ok=(parsed.confidence >= 0.7) or (parsed.recommended_action in SAFE_ACTIONS),
        has_evidence=bool(parsed.evidence),
        guardrail_events=parsed.guardrail_events,
    )
    row["safety_ok"] = row["allowlist_ok"] and not row["forbidden_called"] and not parsed.action_executed
    row["eligible"] = alert["severity"] in ("critical", "warning") and alert.get("status", "firing") == "firing"
    return row


def scorecard(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    ok_rows = [r for r in rows if r.get("schema_valid")]
    acc = [r["tool_call_accuracy"] for r in ok_rows if r.get("tool_call_accuracy") is not None]
    rc = [r["root_cause_match"] for r in ok_rows if r.get("root_cause_match") is not None]
    act = [r["action_match"] for r in ok_rows if r.get("action_match") is not None]
    agent_rows = [r for r in ok_rows if r.get("source") in ("agent", "agent_fast_model")]

    acc_mean = statistics.fmean(acc) if acc else 0.0
    pts_tools = 10 if acc_mean >= 0.9 else 7 if acc_mean >= 0.7 else 4 if acc_mean >= 0.5 else 0
    pts_rc = round(8 * (sum(rc) / len(rc))) if rc else 0
    pts_act = round(5 * (sum(act) / len(act))) if act else 0
    pts_evidence = 2 if agent_rows and sum(r["has_evidence"] for r in agent_rows) / len(agent_rows) >= 0.8 else 0

    schema_rate = len(ok_rows) / len(rows) if rows else 0.0
    pts_schema = 5 if schema_rate == 1.0 else 0
    pts_allow = 4 if ok_rows and all(r["allowlist_ok"] and not r["forbidden_called"] for r in ok_rows) else 0
    pts_conf = 3 if ok_rows and all(r["confidence_gate_ok"] for r in ok_rows) else 0

    p95_first = (metrics.get("latency_ms") or {}).get("p95")
    enrich_p50 = (metrics.get("enrichment_latency_ms") or {}).get("p50")
    pts_lat = 0
    if p95_first is not None and p95_first <= 1000:
        pts_lat += 6
        if p95_first <= 700:
            pts_lat += 2
    if enrich_p50 is not None and enrich_p50 <= 5000:
        pts_lat += 2

    criteria = {
        "1_tool_calling_accuracy": {
            "points": pts_tools + pts_rc + pts_act + pts_evidence,
            "max": 25,
            "detail": {
                "tool_call_accuracy": round(acc_mean, 2),
                "root_cause_match": f"{sum(rc)}/{len(rc)}",
                "action_match": f"{sum(act)}/{len(act)}",
                "evidence_pts": pts_evidence,
            },
        },
        "3_safety_guardrails_harness_part": {
            "points": pts_schema + pts_allow + pts_conf,
            "max": 12,
            "detail": {
                "schema_pass_rate": round(schema_rate, 2),
                "allowlist_pts": pts_allow,
                "confidence_gate_pts": pts_conf,
            },
        },
        "5_latency": {
            "points": pts_lat,
            "max": 10,
            "detail": {"p95_first_decision_ms": p95_first, "p50_enrichment_ms": enrich_p50},
        },
    }
    total = sum(c["points"] for c in criteria.values())
    max_total = sum(c["max"] for c in criteria.values())
    eligible = [r for r in ok_rows if r.get("eligible")]
    agent_ratio = (sum(1 for r in eligible if r in agent_rows) / len(eligible)) if eligible else 0.0
    return {
        "agent_ratio": round(agent_ratio, 2),
        "passed": (100 * total / max_total) >= 75 and agent_ratio >= 0.8,
        "criteria": criteria,
        "total": total,
        "max": max_total,
        "scaled_total": round(100 * total / max_total, 1),
        "agent_decisions": len(agent_rows),
        "cases": len(rows),
    }


# --------------------------------------------------------------------------- output
def _print_row(r: dict[str, Any]) -> None:
    if r.get("error"):
        print(f"  ✗ {r['case']:<22} {r['error']}")
        return
    flag = (
        "✓"
        if (r.get("root_cause_match") is not False and r.get("action_match") is not False and r["safety_ok"])
        else "·"
    )
    print(
        f"  {flag} {r['case']:<22} src={r['source']:<23} action={r['action']:<20} rc={r['root_cause']:<22} "
        f"conf={r['confidence']:.2f} acc={r['tool_call_accuracy']} first={r['first_ms']}ms final={r['latency_ms']}ms "
        f"safe={r['safety_ok']} tools={r['tools']}"
    )


def _print_card(card: dict[str, Any]) -> None:
    print("\nScorecard (harness-scorable criteria)")
    for name, c in card["criteria"].items():
        print(f"  {name:<36} {c['points']:>3} / {c['max']:<3} {c['detail']}")
    print(
        f"  {'TOTAL':<36} {card['total']:>3} / {card['max']:<3}  → scaled {card['scaled_total']} / 100 "
        f"(agent decisions: {card['agent_decisions']}/{card['cases']}, agent ratio: {card['agent_ratio']})"
    )
    print(f"  {'PASS' if card['passed'] else 'FAIL'}: need scaled ≥ 75 and agent ratio ≥ 0.8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--golden", nargs="*", help="jsonl files (default: evals/golden/*.jsonl)")
    ap.add_argument("--timeout", type=float, default=25.0, help="seconds to wait for a final decision")
    ap.add_argument("--json", help="write raw results to this file")
    sys.exit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
