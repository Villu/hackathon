# Hackathon Plan: Resilient Agentic Gateways for Enterprise Event Streams

One-day, on-site hackathon. Teams of 3–4 build an event-driven AI gateway that triages
infrastructure alerts with an LLM agent, MCP tools against Azure, and a deterministic
safety net. Hosted by Webstep. Everything is built *with* OpenCode + oh-my-openagent, the AI-assisted
workflow Webstep consultants meet at clients, so the day doubles as a hands-on workshop in
responsible AI-assisted development.

- **Use case:** Automated Infrastructure Incident Triage & Remediation
- **Stack:** Python 3.12+, FastAPI, Pydantic, `mcp` (FastMCP), `google-genai` (Gemini),
  Azure (Monitor / Log Analytics / Container Apps), optional Kafka (Redpanda) via Docker
- **Tooling:** OpenCode (TUI) + oh-my-openagent (Sisyphus and friends), Gemini API keys, Azure CLI
- **Documents:** `02-ai-usage-briefing.md`, `03-setup-guide.md`, `04-software-spec.md`,
  `05-judging-rubric.md`, slides in `../slides/`, starter code in `../starter/`

---

## 1. Objectives

| # | Objective | How we measure it |
|---|-----------|-------------------|
| 1 | Every participant has a working OpenCode + oh-my-openagent setup connected to Gemini | Setup checklist passed by 10:00 |
| 2 | Everyone knows the Webstep rules for AI-assisted development (with a client team's practice as the intro example) and applies them during the day | Retro + "AI hygiene" score in rubric |
| 3 | Each team ships a gateway that passes the eval harness in mock mode, and ideally against live Azure data | Benchmark scoreboard at 16:00 |
| 4 | Teams experience *why* deterministic guardrails matter: chaos round with injected LLM latency, malformed output and alert bursts | Resilience score |
| 5 | Reusable output: starter kit, spec and eval harness that Webstep can reuse in client work | Repo handed over at end of day |

---

## 2. Schedule (09:00–17:30)

| Time | Block | Owner | Content / deliverable |
|------|-------|-------|-----------------------|
| 08:30–09:00 | Arrival | — | Coffee, Wi-Fi, laptops on, clone starter repo |
| 09:00–09:15 | Welcome & agenda | Facilitator | Why this topic, what a "resilient agentic gateway" is, team formation (3–4 people, mix Python and infra) |
| 09:15–10:00 | **Setup workshop** | Facilitator + helpers | Install OpenCode, install oh-my-openagent, connect Gemini, clone starter, `pytest` green, `az login`. Checklist in `03-setup-guide.md` |
| 10:00–10:30 | **AI-assisted development: how we work** | Facilitator | Intro: a client team's AI rules (Statnett OIS example), five principles that travel, responsible AI use as a consultant, Webstep rules for today. Speaker notes in `02-ai-usage-briefing.md` |
| 10:30–10:45 | Challenge briefing | Facilitator | Theme, use case, architecture, the three deliverables, rubric, live demo of the eval harness against the untouched starter: rules alone already reach ~33/47 harness points with zero agent decisions, so the agent must add accuracy and evidence without losing safety or latency points |
| 10:45–12:30 | **Build Sprint 1 — Tool-calling agent** | Teams | Alert ingestion (REST, optionally Kafka) → agent loop → MCP tools (`query_logs`, `get_deployment_history`, `get_resource_state`) → validated `TriageDecision`. Goal: one alert triaged end-to-end with real tool calls |
| 12:30–13:15 | Lunch + checkpoint | Teams | Before lunch each team shows one alert flowing through. Facilitator notes blockers |
| 13:15–15:30 | **Build Sprint 2 — Reliability layer + eval harness** | Teams | Schema/regex guardrails, action allowlist, token bucket, circuit breaker, deadline-based fallback to deterministic escalation, confidence threshold. Live scoring on `/metrics` and golden-set runner |
| 15:30–16:00 | **Chaos round** | Facilitator | Organizer runs `evals/chaos.py` against every team: LLM latency spikes, garbage output, alert burst, MCP server down. Scores recorded live |
| 16:00–16:45 | Demos | Teams | 5 min per team: architecture in one picture, one live alert, one failure mode survived, what OpenCode did well and badly |
| 16:45–17:15 | Judging & retro | Judges + all | Rubric tally. Retro on the AI-assisted workflow: small changes? understood generated code? removed AI noise? two people before merge? |
| 17:15–17:30 | Awards & wrap-up | Facilitator | Winners, what goes back to Webstep, repo handover |

Timing rules: hard code freeze at 15:30 (the chaos round runs against what is committed).
Demos are timed. Judges deliberate during the retro.

---

## 3. Roles

| Role | People | Responsibilities |
|------|--------|------------------|
| Facilitator / Head Judge | 1 | Runs the day, presents, owns rubric and final scores |
| Setup helpers | 2 | Roam during 09:15–10:00, unblock installs (Windows/macOS/Linux) |
| Infra owner | 1 | Owns Azure subscription `GPT Initium`, resource group `VilluResourceGroup`, Gemini keys, budget alerts (NOK 25/50/100/250 already configured), kills runaway spend |
| Judges | 2–3 | Score demos and chaos round; at least one from outside the teams |
| Teams | 3–4 per team, 4–6 teams | Build |

---

## 4. Pre-event checklist (T-7 days → T-0)

- [ ] Starter repo (`starter/`) tagged and pushed to the internal Git; `pytest` green in mock mode on Windows, macOS and Linux.
- [ ] Gemini API keys: one key per team, distributed via password manager, quota checked. Never in the repo.
- [ ] Azure: participants can `az login` to the tenant and have Reader, Log Analytics Reader and Monitoring Reader on `VilluResourceGroup`. Run `starter/scripts/azure_bootstrap.sh` to create the Log Analytics workspace and a noisy sample Container App that produces logs and revisions.
- [ ] Budget alerts on the resource group verified (live: NOK 500/month, alerts at 25/50/100/250).
- [ ] OpenCode 1.4+ and oh-my-openagent tested on a fresh Windows laptop (WSL recommended) and a fresh Mac. Exact versions noted in the setup guide.
- [ ] Optional: Docker Desktop for teams who want Kafka (Redpanda compose file in starter).
- [ ] Slides (`slides/hackathon-slides.pptx`) reviewed. AI-usage briefing reviewed; client example kept to team rules only, no client-internal document references.
- [ ] Eval harness (`starter/evals/`) run against a reference solution; chaos scenarios produce differentiated scores.
- [ ] Rubric printed for judges (`05-judging-rubric.md`).
- [ ] Room: big screen, power, Wi-Fi with outbound HTTPS to `generativelanguage.googleapis.com`, `*.azure.com`, `registry.npmjs.org`, `pypi.org`, `opencode.ai`.

---

## 5. Team deliverables (what is judged)

1. **Tool-calling agent** — intercepts alerts, calls MCP tools to query Azure (logs, deployment history, resource state) and produces a validated `TriageDecision`.
2. **Reliability layer** — deterministic guardrails so the agent never breaks downstream systems: schema + regex validation, action allowlist, token-bucket rate limiter, circuit breaker, deadline-based fallback (fast model → deterministic escalation script), confidence threshold.
3. **Real-time eval harness** — live scoring of output safety and tool-call accuracy on `/metrics`, plus a golden-set runner producing a scorecard.

Full specification: `04-software-spec.md`. Rubric: `05-judging-rubric.md`.

---

## 6. Scoring summary

| Criterion | Points |
|-----------|--------|
| Tool-calling accuracy (right tools, right arguments, correct root cause on golden set) | 25 |
| Resilience under chaos (fallbacks engage, no crashes, no unsafe actions, deadlines held) | 25 |
| Safety & guardrails (schema pass rate, blocked forbidden actions, confidence gating, injection resistance) | 20 |
| Eval harness quality (live metrics, golden set, clarity of scorecard) | 15 |
| Latency (p95 first decision ≤ 1 s including fallback; p50 as tie-breaker) | 10 |
| Demo & AI-workflow hygiene (understood code, small commits, removed AI noise, two-person review) | 5 |

---

## 7. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Installs eat the morning | Two helpers, pre-tested setup guide; mock mode needs only Python. WSL for Windows |
| Gemini quota or key leak | One key per team, rate limiter in starter, keys via `.env` only, budget alerts |
| Azure access issues | Everything works with `MOCK_AZURE=true`; live Azure gives bonus points, it is not a prerequisite |
| Teams over-build with AI and don't understand it | Rules of the day enforced in rubric; each demo must include "explain one generated function" |
| Chaos round crashes gateways | That is the point; scoring rewards graceful degradation |
| Spend | Flash-class models only, token budget per request, NOK budget alerts |

---

## 8. After the event

- Collect all team repos, run the final eval, publish the scoreboard internally.
- Write a short post-event note: failure modes seen, best guardrail patterns, what OpenCode/oh-my-openagent did well and where humans had to step in.
- Fold the best reliability patterns back into the starter kit so Webstep can reuse it in client work.
