# Instructor Guide

For the facilitator, helpers, infra owner and judges. Everything needed to prepare, run and
score the day in one place. Participant-facing material is in `01`–`05` and `starter/`.

---

## 1. At a glance

| What | Where | Who sees it |
|------|-------|-------------|
| Plan, briefing, setup guide, spec, rubric, slides | `github.com/Villu/hackathon` → `docs/`, `slides/` | everyone (public) |
| Starter kit teams clone | same repo → `starter/` (push it as its own repo for teams) | everyone |
| Azure infra script | `starter/scripts/azure_bootstrap.sh` (+ `noisy_app.py`) | everyone; only the infra owner runs it |
| Reference solution (answer key) | `github.com/Villu/hackathon-private` → `reference/` | organisers only |
| Hidden golden cases (8) | `hackathon-private/reference/evals/golden/triage_v2_reference.jsonl` | organisers only |
| Scoring script | `hackathon-private/scoring/score_team.sh` | organisers only |
| Source material (brief, client AI guidelines, Azure transcripts) | `hackathon-private/sources/` | organisers only, never publish |
| Organiser box | `sepman.net` (ssh port 10022, user `hest`): `~/hackathon` + `~/hackathon/private`, uv + Python 3.12, `az` logged in, Gemini key in `private/reference/.env` (mode 600) | infra owner |

Local working copy: `C:\Users\villu\projects\hackathon` (public repo) with `private/` (private
repo, git-ignored in the public one).

---

## 2. What participants build

Teams get a working shell: in mock mode the gateway already ingests alerts, answers every one
with the deterministic rules, serves `/metrics` and survives chaos by falling back. Their job is
to make the agent path win without losing that safety net.

| Sprint | TODO (`grep -rn "TODO(team)"`) | Reference size | Estimate for a team |
|--------|-------------------------------|----------------|---------------------|
| 1 | `gateway/agent/triage_agent.py` — tool loop: Gemini function calls → MCP tools → JSON draft → one retry on the fast model | ~75 lines | 60–90 min |
| 1 | `gateway/reliability/fallback.py` — rules for new alert names | ~15 lines | 15 min |
| 2 | `gateway/reliability/guardrails.py` — action allowlist, confidence gate, more patterns | ~40 lines | 30 min |
| 2 | `gateway/pipeline.py::_agent_phase` — token bucket, LLM + MCP circuit breakers, `schema_retry` event | ~50 lines | 45 min |
| 2 | `gateway/scoring/scoring.py` — `compute_tool_call_accuracy` | ~10 lines | 10 min |
| 2 | `evals/golden/` — at least 5 new cases | 5–8 lines of JSONL | 30 min |
| opt | `azure_openai` provider, Kafka in/out, decision webhook, decision cache, live-Azure track | — | stretch |

The whole reference is about 180 added lines. Split across 3–4 people, the core fits in
about 2.5 of the 4 hours of sprint time, leaving room for live Azure, the demo and getting stuck.
**The estimates are not measured with OpenCode.** The reference was written by an AI agent that
already knew the code base. A helper should time one TODO in OpenCode before the event and
adjust.

**Core vs stretch.** Core is everything above "opt". The `schema_retry` guardrail event is
core: the chaos round needs it for `llm_garbage` mechanism points. Tell teams in the briefing.

**Teams that finish early** get [`starter/EXTRAS.md`](../starter/EXTRAS.md): red-teaming another
team, poisoned tool output, a model shoot-out, a cost meter, storm grouping, live Azure, a
dashboard, Kafka, a toolbox skill. Extras earn no separate points. They show up in the demo and
in rubric 4 (eval harness quality) and 6 (demo). The red-team extra needs two teams. Pair early
finishers and pass the `.jsonl` files between them. Extra 2 adds a field to the chaos state; the
scorer still works as long as `POST /chaos` with `{}` clears all faults.

---

## 3. Infrastructure

```
 participants' laptops                         Google                      Azure: GPT Initium / VilluResourceGroup (norwayeast)
 ┌──────────────────────────────┐   HTTPS   ┌──────────────┐              ┌─────────────────────────────────────────────┐
 │ OpenCode + oh-my-openagent ──┼──────────▶│ Gemini API   │              │ Container Apps env  hackathon-env           │
 │ gateway (FastAPI) :8080      │──────────▶│ (team key)   │              │  orders-api        bad deploy → HTTP 500s    │
 │   └─ MCP server (stdio) ─────┼── az login (read only) ───────────────▶ │  payments-worker   DB connection refused     │
 │ simulator / run_evals        │                                         │  checkout-frontend OOM kills                 │
 └──────────────────────────────┘                                         │  search-indexer    busy but healthy          │
                                                                          │ Log Analytics      hackathon-logs ◀── logs   │
 organiser: sepman.net ── score_team.sh (team repo @ freeze) ───────────▶ └─────────────────────────────────────────────┘
```

### 3.1 Two modes, same code

| Mode | Needs | Use |
|------|-------|-----|
| `LLM_PROVIDER=mock`, `MOCK_AZURE=true` | Python only | tests, first hour, chaos scoring |
| `LLM_PROVIDER=gemini`, `MOCK_AZURE=true` | team Gemini key | normal development, golden-set scoring |
| `LLM_PROVIDER=gemini`, `MOCK_AZURE=false` | key + `az login` + Reader roles | live-Azure track (bonus in demo, not required) |

The mock fixtures and the Azure apps tell the same four stories under the same names, so a team
switching to live Azure sees the same incidents with real data.

### 3.2 Azure resources (`starter/scripts/azure_bootstrap.sh`)

Run on sepman.net (or Cloud Shell) from `~/hackathon/starter`:

| Command | What it does |
|---------|--------------|
| `bash scripts/azure_bootstrap.sh up` | Creates the Log Analytics workspace `hackathon-logs`, the Container Apps env `hackathon-env` and the four apps. orders-api gets revision history 2.13.1 → 2.13.2 → 2.14.0 (bad). Idempotent. Prints `LOG_ANALYTICS_WORKSPACE_ID` |
| `... status` | Apps, orders-api revisions, log lines per app in the last 30 min |
| `... pause` / `resume` | Scale all apps to 0 / 1. Paused costs ~nothing. Each call creates a new revision (harmless) |
| `... redeploy-bad` | New 2.14.0 revision on orders-api, so "deployed N minutes ago" is true on the day |
| `... grant participants.txt` | Reader on the 4 apps + Log Analytics Reader on the workspace, per UPN/object id (one per line). Deliberately **not** on the resource group, which holds unrelated VMs, APIM and function apps |
| `... down --yes` | Deletes apps, env and workspace |

Current state (2026-11-04): created and verified, then **paused**. Workspace id
`9f982122-1ecf-4b1e-a9bf-6b5da8118891`. The apps run stock `python:3.12-alpine` with
`noisy_app.py` passed in base64, so no container registry is needed.

Cost: running ≈ NOK 25–30/day (4 × 0.25 vCPU/0.5 GiB); paused ≈ 0; Log Analytics ingestion is
a few MB/day. Budget on the RG: NOK 700/month, alerts at NOK 70/175/350/525 to the infra owner.

Known limits: `get_alert_history` reads alerts at subscription scope, so participants with
resource-scoped Reader get a structured error from that tool (the agent copes). Container App
logs appear in `ContainerAppConsoleLogs_CL` 5–10 min after an app starts.

### 3.3 Gemini

- One API key per team, from Google AI Studio, handed out via the password manager. Never in a
  repo. The organiser key lives only in `.env` files (git-ignored) on the organiser machines.
- Models that work for new keys (checked 2026-11-04): primary `gemini-2.5-flash`, fast
  `gemini-3.1-flash-lite`. `gemini-2.5-flash-lite` is closed to new keys.
- `GEMINI_THINKING_BUDGET=0` (the starter's default) is essential: with default thinking,
  `gemini-2.5-flash` takes ~6 s per call; without it, ~0.8 s.
- One live golden run (18 alerts) is roughly 60–80 model calls.

---

## 4. Before the event

| When | Task | How / check |
|------|------|-------------|
| T-14 | Invite list → Entra UPNs in `participants.txt` (organiser only, not in git) | — |
| T-14 | Push `starter/` as its own repo for teams (e.g. `resilient-gateway-starter`), or let teams fork the public repo and work in `starter/` | `score_team.sh` finds `gateway/` in root or `starter/` |
| T-10 | Create one Gemini key per team (+2 spare), check quota | `python -m gateway.agent.llm --ping` with each key |
| T-10 | Send the pre-event mail: install Git, Node 20, Bun, Python 3.12, uv, Azure CLI, OpenCode before the day; run `pytest -q` in the starter | biggest risk of the day is installs |
| T-7 | Dry run: a helper does Sprint 1 with OpenCode + Gemini on a clean laptop, timed | adjust "core vs stretch" in the briefing |
| T-7 | Test the setup guide on clean Windows (WSL) and macOS | the starter is verified on Windows (Python 3.14) and Linux (3.12) only |
| T-3 | `azure_bootstrap.sh grant participants.txt` | ask 1–2 participants to run `python -m mcp_server.server --self-test` with `MOCK_AZURE=false` |
| T-1 | `azure_bootstrap.sh resume`, then `status` after 10 min | lines per app > 0 |
| T-1 | Print rubric (one per judge) and the scoreboard sheet (§6.5) | — |
| T-1 | Venue: outbound HTTPS to the endpoints in `03-setup-guide.md` §7 | — |
| Day, 10:15 | `azure_bootstrap.sh redeploy-bad` | fresh "bad deploy" for Sprint 1 |

---

## 5. Run sheet for the day

- **08:30** Wi-Fi check, Gemini keys in the password manager, Azure apps running (`status`).
- **09:00** Welcome, form teams of 3–4 (mix Python and infra).
- **09:15** Setup workshop. Target: `pytest -q` green, one alert decided, `/models` lists Gemini.
  Fallback for anyone stuck: mock mode needs only Python.
- **10:00** AI-assisted development briefing (`02`).
- **10:15** Infra owner: `redeploy-bad`.
- **10:30** Challenge briefing. Live demo: untouched starter scores 33/47 (70 scaled) and 12/25 on
  chaos. Say clearly: chaos points need a live agent path; `schema_retry` is expected; final
  accuracy is scored on hidden cases too.
- **10:45** Sprint 1. Helpers watch for the pitfalls in §8.
- **12:30** Lunch checkpoint: each team shows one alert decided by `agent` with real tool calls.
- **13:15** Sprint 2. Remind at 14:30 and 15:15 about code freeze.
- **15:30** **Code freeze**: each team pushes and tags `freeze` (`git tag freeze && git push --tags`).
  Organiser starts `score_team.sh` for every team (§6.3) while the chaos round is shown live
  on the big screen for one or two teams.
- **16:00** Demos, 5 min each. Judges fill §1 evidence spot-check, §3 code review, §4, §6.
- **16:45** Retro, judges deliberate with the scoreboard.
- **17:15** Awards; after: `azure_bootstrap.sh pause`.

---

## 6. Scoring and evaluation

### 6.1 Where each point comes from

| Rubric | Points | Source |
|--------|--------|--------|
| 1 Tool-calling accuracy | 25 | harness, live golden run (evidence 2 pts: harness + judge spot-check) |
| 2 Resilience under chaos | 25 | chaos runner, mock LLM |
| 3 Safety: schema, allowlist, confidence | 12 | harness, live golden run |
| 3 Safety: injection | 6 | chaos runner (`injection` mode) |
| 3 Safety: `eval` block never in prompt | 2 | judges, code review of `prompts.py` / `for_llm()` |
| 4 Eval harness quality | 15 | judges (demo + team's own golden cases and `/metrics`) |
| 5 Latency | 10 | harness, live golden run |
| 6 Demo & AI hygiene | 5 | judges |
| **Automated** | **78** | `score_team.sh` summary line: harness /47 + chaos /25 + injection /6 |
| **Judges** | **22** | rubric sheet |

### 6.2 Why it is run this way

- **The organiser runs everything** against the team's frozen commit on sepman.net. That avoids
  reaching into laptops over venue Wi-Fi, where firewalls and client isolation usually block it.
  It also means every team is measured on the same machine.
- **Harness from the organiser, gateway from the team.** `run_evals.py` and `chaos.py` come from
  the private reference checkout, so a team editing its copy changes nothing.
- **Golden set = public 10 + hidden 8.** This rewards real triage over rules tuned to the
  public cases.
- **Chaos with the mock LLM.** With live Gemini, the 8 workers already keep calls below the
  rate limit, so the burst check would depend on Gemini's speed. Mock is identical and free for
  every team.

### 6.3 Running the scorer

```bash
ssh -p 10022 hest@sepman.net
cd ~/hackathon/private && git pull
scoring/score_team.sh team-blue git@github.com:<org>/<team-blue-repo>.git        # ref defaults to tag "freeze"
scoring/score_team.sh --summary                                                   # one line per team
```

Takes ~10–12 minutes per team. Teams can run in parallel: each team gets its own port. Outputs go to
`~/hackathon-scoring/<team>/results/`: `golden.txt` (scorecard per case), `chaos.txt`,
`pytest.txt`, `secrets.txt` (must be empty), `extras.txt`, and gateway logs.

**Extras** (`starter/EXTRAS.md`) are checked too, for the judges only. They add no points, and the
summary line lists them as `extras: 1,2,5,...`. `extras.txt` has one line per extra, marked `ok`,
`partial`, `fail`, `absent` or `judge` (a human needs to look):

| # | What the scorer checks |
|---|------------------------|
| 1 | `evals/golden/redteam_*.jsonl` has ≥ 5 valid cases. Every red-team file from teams scored *earlier* is also run against this team's live gateway (`redteam-received.txt`). Re-score everyone once at the end for the full matrix |
| 2 | `POST /chaos {"tool_poison": true}` is accepted. With live Gemini, 5 prod alerts give zero `execute_action` calls and no prod remediation, and `{}` clears the fault |
| 4 | a token counter > 0 on `/metrics` after the live golden run |
| 5 | 20 alerts on one app at 10/s: ≥ 15 marked grouped (an event containing `group`), at most 3 real investigations. Rate limiting alone doesn't count |
| 7 | `GET /dashboard` serves HTML that polls `/metrics` and `/decisions` and loads nothing from outside (`fail` if it uses a CDN) |
| 8 | a Kafka producer in `gateway/`; check the Redpanda console in the demo |
| 9 | files under `skills/` |
| 3, 6 | judge: the shoot-out table in the demo. For 6, the team's own Azure code runs its self-test with the organiser's `az login` (set `SKIP_AZURE=1` to skip) |

Watch the interaction between extra 5 and the chaos round: a team that groups alerts makes fewer
LLM calls, so during `llm_down` its breaker may open later. Check `chaos.txt` before
blaming the extra. The repo must be readable by the
GitHub account on sepman (Villu). Private team repos need that account added as a reader.

Reference results (2026-11-04) as a sanity check:

| Run | Harness /47 | Chaos /25 | Injection /6 |
|-----|-------------|-----------|--------------|
| Untouched starter (rules only) | 33 (70 scaled) public set | 12 | 3 |
| Reference, mock LLM | 39 public / 36 all 18 | 25 | 6 |
| Reference, live Gemini, mock Azure | 46 (all 18 cases), p50 enrichment 2.4 s | 22 live (burst needs mock) | 6 |
| Reference, live Gemini, live Azure | 47 (all 18 cases), p50 4.2 s | — | — |
| `score_team.sh` on sepman: untouched starter | 32 (all 18 cases) | 12 | 3 |
| `score_team.sh` on sepman: reference | 47 | 25 | 6 |

### 6.4 Judges

- Spot-check two decisions' `evidence[]` against the tool calls in `golden.json` (2 pts).
- Code review (2 pts): `alert.eval` must not reach the LLM. Check `prompts.py` and anything that
  builds `contents`.
- Rubric 4: is `/metrics` readable live? Are there ≥ 5 new golden cases with realistic
  annotations? Does the scorecard explain each failure?
- Rubric 6: ask the team to explain one agent-generated function line by line. Check `git log`
  for small commits and a second person on merges.

### 6.5 Scoreboard sheet

| Team | SHA | Harness /47 | Chaos /25 | Inj /6 | Eval-block /2 | Rubric 4 /15 | Rubric 6 /5 | Total /100 | Secrets? |
|------|-----|-------------|-----------|--------|---------------|--------------|-------------|-----------|----------|
| | | | | | | | | | |

Tie-breakers: chaos score, then live p50 latency, then fewest `safety_violations`.
Disqualifiers (per criterion, judge's call): secrets in history (`secrets.txt` non-empty after a
human check), `/chaos` disabled, unapproved endpoints, real client data.

---

## 7. What the reference changed in the starter (already merged into the public starter)

These came out of the reference run and are fixed for participants:

1. `tests/test_api.py` forced the final decision to be deterministic, so it would go red once a
   team's agent worked. It now sets `llm_down` first.
2. The chaos runner gave the untouched starter 31/31. It now splits survive and mechanism points,
   requires a live agent path, and waits for the breaker to close between modes.
3. Live Gemini defaults: thinking off, per-call budget 3000 ms (was 700, below Gemini's real
   latency), fast model `gemini-3.1-flash-lite`.
4. Golden case `oom-02-staging` now expects `escalate_to_oncall`: the app is already at max
   replicas, so `scale_out` was the wrong answer.
5. Azure bootstrap rewritten (§3.2). MCP server no longer floods logs with Azure SDK HTTP lines.

---

## 8. Helper cheat sheet: where teams get stuck

| Symptom | Cause | Fix |
|---------|-------|-----|
| Every decision is `deterministic_fallback` with live Gemini | per-call budget too low or thinking on | `GEMINI_THINKING_BUDGET=0`, `LLM_PRIMARY_BUDGET_MS=3000` |
| `404 ... no longer available to new users` | old fast model in `.env` | `GEMINI_FAST_MODEL=gemini-3.1-flash-lite` |
| Gemini error about function response/turn order | tool responses not appended as one user `Content` right after the model's `content` | append `res.content`, then one `Content(role="user", parts=[Part.from_function_response(...) ...])` |
| Agent loops until the deadline | never stops calling tools | cap at `MAX_TOOL_ROUNDS`, then one call with `tools=None` to force an answer |
| Chaos `llm_garbage` mechanism 0 | retry happens but no event | append `"schema_retry"` to the decision's `guardrail_events` |
| Chaos modes after `llm_down` all fall back | breaker never closes | `record_success()` on success; half-open probe after `CB_HALF_OPEN_AFTER_S` |
| `burst` mechanism 0 | bucket never consulted | `self.bucket.try_acquire()` before the agent call in `_agent_phase` |
| `pytest` red after Sprint 1 | old starter copy | pull the latest starter (`test_api` fix) |
| Live Azure: `query_logs` empty | apps paused or logs not yet ingested | infra owner: `status`; wait 5–10 min after `resume` |
| Live Azure: `AuthorizationFailed` | not granted, or wrong subscription | `az account set --subscription "GPT Initium"`; infra owner runs `grant` |

The reference (`hackathon-private/reference/`) is the answer key for helpers. Show patterns,
not the file.

---

## 9. After the event

```bash
cd ~/hackathon/starter && bash scripts/azure_bootstrap.sh pause      # same day
bash scripts/azure_bootstrap.sh down --yes                             # when the scoreboard is final
```

Revoke the team Gemini keys in AI Studio. Remove participants' role assignments (`down` removes
the resources they were scoped to). Fold the best team patterns back into the starter and
publish the scoreboard internally (`01-hackathon-plan.md` §8).
