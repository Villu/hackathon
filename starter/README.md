# Resilient Agentic Gateway — hackathon starter

Event-driven gateway that triages infrastructure alerts with an LLM agent (Gemini), MCP tools
against Azure, and a deterministic safety net. This repo is a **shell**: the plumbing works end
to end in mock mode, the interesting parts are marked `TODO(team)`.

Spec: `SPEC.md` (copy of `docs/04-software-spec.md`). Rubric: `RUBRIC.md`.

## Quickstart (5 minutes)

```bash
# 1. environment (pick one)
uv sync --extra dev                          # or:
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"   # Windows: py -m venv .venv; .\.venv\Scripts\Activate.ps1

# 2. config
cp .env.example .env                         # add GEMINI_API_KEY; keep MOCK_AZURE=true for now

# 3. green tests before you touch anything
pytest -q                                    # expect: passed + a handful of xfailed (your TODOs)

# 4. run it
uvicorn gateway.main:app --reload --port 8080
python -m simulator.alert_generator --scenario cpu_spike --count 1     # other terminal
curl -s localhost:8080/decisions | head -c 600
```

The untouched starter answers every alert with `decision_source: "deterministic_fallback"`
because `TriageAgent.run()` returns `None`. Make the agent path win without losing the fallback.

## What is where

```
gateway/
  main.py              FastAPI: POST /alerts, GET /decisions, GET /metrics, GET /health, POST /chaos
  pipeline.py          ingest → dedupe → Phase 0 (rules) → Phase 1 (agent) → guardrails → store   ← Sprint 2 TODOs
  models.py            Alert, TriageDraft, TriageDecision (the contracts)
  config.py            every knob from spec §7 (env / .env)
  stream/normalise.py  Prometheus / Azure Monitor / normalised shapes → Alert
  stream/kafka.py      optional Kafka consumer
  agent/
    triage_agent.py    ← SPRINT 1: the tool-calling loop (skeleton with step list)
    llm.py             Gemini + mock provider, chaos hooks, `--ping`
    mcp_client.py      spawns the MCP server, Gemini tool declarations, timed calls
    prompts.py         system prompt; annotations wrapped as untrusted data; eval stripped
  reliability/
    fallback.py        deterministic rule table (Phase 0 + last rung of the ladder)
    guardrails.py      parse_draft, sanitise_text  |  TODO: allowlist, confidence gate
    rate_limiter.py    token bucket        (implemented, not yet wired in)
    circuit_breaker.py closed/open/half-open (implemented, not yet wired in)
    chaos.py           fault-injection state used by the chaos round — keep it
  scoring/
    scoring.py         live per-decision scores  |  TODO: tool_call_accuracy
    metrics.py         rolling p50/p95, counters, Prometheus text
mcp_server/
  server.py            FastMCP tools: get_resource_state, get_deployment_history, query_logs,
                       get_alert_history, execute_action (dry-run)   `--self-test`
  backends.py          MockBackend (deterministic fixtures) and AzureBackend (az login)
simulator/             alert_generator.py + scenarios.py (cpu_spike, deployment_regression, oom,
                       dependency_down, traffic_spike, noise, resolved, injection, mixed)
evals/
  golden/*.jsonl       golden cases with expected root cause / action / tools
  run_evals.py         scorecard against a running gateway
  chaos.py             the judges' chaos runner (llm_delay, llm_garbage, llm_down, mcp_down, burst, injection)
tests/                 unit + API tests; xfail tests describe your TODOs
```

## Your TODOs (search for `TODO(team)`)

| Sprint | File | What |
|--------|------|------|
| 1 | `gateway/agent/triage_agent.py` | The loop: prompt → Gemini function calls → MCP tools → JSON draft → retry with fast model on schema error |
| 1 | `gateway/reliability/fallback.py` | Rules for the alert names in your golden set |
| 2 | `gateway/reliability/guardrails.py` | `apply_action_allowlist`, `apply_confidence_gate`, more patterns |
| 2 | `gateway/pipeline.py::_agent_phase` | Wire in `TokenBucket` and `CircuitBreaker`, record success/failure, idempotency |
| 2 | `gateway/scoring/scoring.py` | `compute_tool_call_accuracy` |
| 2 | `evals/golden/` | At least 5 new realistic cases |
| opt | `gateway/agent/llm.py` | `azure_openai` provider via the APIM endpoint |
| opt | `gateway/stream/kafka.py`, `pipeline._store` | Kafka in/out, webhook |

## Useful commands

```bash
python -m gateway.agent.llm --ping                 # is the key/model OK?
python -m mcp_server.server --self-test            # do the tools work (mock or Azure)?
python -m simulator.alert_generator --scenario mixed --rate 5 --count 50 --shape prometheus
python -m evals.run_evals                          # scorecard (needs gateway on :8080)
python -m evals.chaos --mode llm_delay --count 5   # rehearse the chaos round
curl -s -X POST localhost:8080/chaos -H 'content-type: application/json' -d '{"llm_delay_ms":3000}'
curl -s localhost:8080/metrics | python -m json.tool
```

## Live Azure

```bash
az login && az account set --subscription "GPT Initium"
pip install -e ".[azure]"
# .env: MOCK_AZURE=false, LOG_ANALYTICS_WORKSPACE_ID=<from facilitator>
python -m mcp_server.server --self-test
```

The Azure backend reads Container Apps state and revisions and queries
`ContainerAppConsoleLogs_CL` in Log Analytics. It never mutates anything: `execute_action` is a
dry run everywhere. It was written against the current SDKs but not exercised in CI, so expect
to fix a field name or two on first contact — that is a fine Sprint 1 task for the infra person.

## Rules of the day

Approved endpoints only (Gemini, Azure, PyPI/npm). Synthetic data only. Two people on every
merge. Understand what you commit. Keep `POST /chaos` working. See `AGENTS.md`.
