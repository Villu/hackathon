# AGENTS.md — rules for AI coding agents working in this repo

You are helping a hackathon team build a resilient agentic gateway for incident triage.
The spec is `../docs/04-software-spec.md` (copy in this repo: `SPEC.md`). Read it before
changing contracts.

## Project rules (Webstep hackathon — these are not optional)
- Do not add calls to external endpoints beyond: Gemini API, Azure management/monitor APIs,
  PyPI/npm. Anything else: stop and ask the human.
- Small changes. One TODO at a time. Run `pytest -q` and `ruff check .` before declaring done.
- Do not generate large test files or long docstrings. Keep text short.
- Never write secrets into files. `.env` is git-ignored; use `.env.example` for new variables.
- The humans must understand every line you produce. Prefer plain code over clever code.

## Contracts you must not break
- `gateway/models.py` — `Alert`, `TriageDraft`, `TriageDecision`. Tool names in `mcp_server/server.py`.
- HTTP API paths in `gateway/main.py`, including `POST /chaos` (fault injection used by judges).
- `alert.eval` must never be included in anything sent to the LLM (`Alert.for_llm()` strips it).

## Where the work is
- Sprint 1: `gateway/agent/triage_agent.py` → `TriageAgent.run()` (tests: `tests/test_agent.py`, xfail).
- Sprint 2: `gateway/reliability/guardrails.py` (allowlist, confidence gate), `gateway/pipeline.py`
  (`_agent_phase`: rate limiter, circuit breaker), `gateway/scoring/scoring.py`
  (`compute_tool_call_accuracy`). Tests marked `xfail` describe the expected behaviour.
- Extend `evals/golden/*.jsonl` with new realistic cases; extend `gateway/reliability/fallback.py` rules.

## Commands
```
pytest -q                                   # unit + API tests (mock LLM)
ruff check . && ruff format .
uvicorn gateway.main:app --reload --port 8080
python -m simulator.alert_generator --scenario mixed --count 10 --rate 2
python -m evals.run_evals                   # scorecard against a running gateway
python -m evals.chaos --mode all            # what the judges run
python -m mcp_server.server --self-test     # check tool backends (mock or Azure)
python -m gateway.agent.llm --ping          # check the Gemini key
```
