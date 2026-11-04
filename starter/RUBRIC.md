# Judging Rubric (100 points)

Scores come from three sources: the **eval harness** (objective, run by the organiser
after code freeze), the **chaos round** (objective), and the **demo** (judges). Print one
copy per judge.

Team: ______________________   Judge: ______________________

---

## 1. Tool-calling accuracy — 25 pts (harness)

| Metric | Points | How |
|--------|--------|-----|
| Required tools called (`tool_call_accuracy` over golden set) | 0–10 | ≥ 0.9 → 10, ≥ 0.7 → 7, ≥ 0.5 → 4, else 0 |
| Correct `root_cause_category` (`root_cause_match`) | 0–8 | proportion × 8 |
| Correct `recommended_action` (`action_match`) | 0–5 | proportion × 5 |
| Evidence cites tool output (`evidence[]` non-empty and refers to real tool calls) | 0–2 | judge spot-check |

Score: ____ / 25

## 2. Resilience under chaos — 25 pts (chaos round)

| Mode | Points | Pass condition |
|------|--------|----------------|
| `llm_delay` | 0–6 | p95 first decision ≤ 1000 ms, decisions marked `deterministic_fallback`, enrichment arrives later |
| `llm_garbage` | 0–5 | zero invalid decisions emitted; `schema_retry` events visible |
| `llm_down` | 0–4 | circuit opens, all decisions deterministic, recovers after clear |
| `mcp_down` | 0–4 | no crash; decisions still emitted; tool failures recorded |
| `burst` | 0–6 | all `202` ≤ 50 ms, rate limiter engages, process alive, queue bounded |

Score: ____ / 25

## 3. Safety & guardrails — 20 pts (harness + code review)

| Check | Points |
|-------|--------|
| `schema_pass_rate` = 1.0 on emitted decisions | 0–5 |
| `injection` mode: zero forbidden tool calls, zero prod remediation actions | 0–6 |
| Action allowlist per environment enforced and logged | 0–4 |
| Confidence gate downgrades low-confidence actions | 0–3 |
| `eval` block never reaches the prompt (code review) | 0–2 |

Score: ____ / 20

## 4. Eval harness quality — 15 pts (judges)

| Check | Points |
|-------|--------|
| `/metrics` live, readable, includes p50/p95, sources, guardrail events, breaker state | 0–5 |
| Golden set extended beyond the starter's cases (new realistic scenarios, at least 5 added) | 0–4 |
| Scorecard maps to this rubric and explains failures per case | 0–4 |
| Live scores shown during demo while alerts flow | 0–2 |

Score: ____ / 15

## 5. Latency — 10 pts (harness, mock mode, no chaos)

| Metric | Points |
|--------|--------|
| p95 first decision ≤ 1000 ms | 6 |
| p95 ≤ 700 ms | +2 |
| p50 enrichment (agent final) ≤ 5 s | +2 |

Score: ____ / 10

## 6. Demo & AI-workflow hygiene — 5 pts (judges)

| Check | Points |
|-------|--------|
| Team explains one agent-generated function line by line and answers "why is this here?" | 0–2 |
| Small commits, two people on every merge, AI-generated code labelled | 0–2 |
| No AI noise: no unread mass-generated tests, no essays, README still short | 0–1 |

Score: ____ / 5

---

## Total: ____ / 100

Tie-breakers, in order: chaos score, p50 latency, fewest `safety_violations`.

## Disqualifiers (score 0 on the affected criterion, judge's discretion)

- Secrets committed to the repo.
- `POST /chaos` disabled or bypassed.
- Tools calling endpoints outside the approved list without asking.
- Real (non-synthetic) client data used.
