# Setup Guide (09:15–10:00)

Target: by 10:00 every participant can (1) run OpenCode with oh-my-openagent against Gemini,
(2) run the starter's tests, (3) reach Azure with the CLI. Helpers roam; if you are stuck
for more than five minutes, raise a hand.

Windows users: WSL2 (Ubuntu) is strongly recommended for OpenCode. The starter itself runs
natively on Windows with `py`.

---

## 0. Prerequisites (check first)

| Tool | Check | Install if missing |
|------|-------|--------------------|
| Git | `git --version` | https://git-scm.com |
| Node.js 20+ | `node --version` | https://nodejs.org (LTS) |
| Bun (for `bunx`) | `bun --version` | macOS/Linux: `curl -fsSL https://bun.sh/install \| bash` · Windows: `powershell -c "irm bun.sh/install.ps1 \| iex"` · or `npm install -g bun` |
| Python 3.12+ | `python3 --version` (Windows: `py --version`) | https://www.python.org/downloads |
| uv (recommended) | `uv --version` | `pip install uv` or https://docs.astral.sh/uv |
| Azure CLI | `az version` | Windows: `winget install Microsoft.AzureCLI` · macOS: `brew install azure-cli` · Ubuntu: `curl -sL https://aka.ms/InstallAzureCLIDeb \| sudo bash` |
| Docker (optional, Kafka only) | `docker ps` | Docker Desktop |

---

## 1. Install OpenCode (1.4.0 or newer)

Pick one:

```bash
# any OS
curl -fsSL https://opencode.ai/install | bash
```

```bash
# npm (all OS)
npm install -g opencode-ai
```

```bash
# macOS
brew install anomalyco/tap/opencode
```

```powershell
# Windows native (WSL still recommended)
scoop install opencode
# or: choco install opencode
```

Verify:

```bash
opencode --version
```

---

## 2. Connect Gemini to OpenCode

You received one Gemini API key per team. Treat it like a password: never commit it, never
paste it into chat.

Option A (interactive): start `opencode` in any folder, run `/connect`, choose **Google**,
paste the key.

Option B (environment variable, works for scripts too):

```bash
# macOS / Linux / WSL
export GOOGLE_GENERATIVE_AI_API_KEY="<team key>"
export GEMINI_API_KEY="$GOOGLE_GENERATIVE_AI_API_KEY"   # used by the Python starter
```

```powershell
# Windows PowerShell
$env:GOOGLE_GENERATIVE_AI_API_KEY = "<team key>"
$env:GEMINI_API_KEY = $env:GOOGLE_GENERATIVE_AI_API_KEY
```

Test inside OpenCode: `/models` should list `google/gemini-2.5-pro`, `google/gemini-2.5-flash`
and newer Gemini models. Ask it something trivial.

---

## 3. Install oh-my-openagent

oh-my-openagent (formerly oh-my-opencode) is the plugin that gives OpenCode the Sisyphus
orchestrator, specialist agents (Oracle, Librarian, Explore, ...), background subagents,
LSP/AST tools and Claude-Code-compatible skills and hooks.

```bash
bunx oh-my-openagent install
```

The installer asks about subscriptions. Answer **No** to Claude, ChatGPT and Copilot,
**Yes** to Gemini, and skip the rest. It writes `"plugin": ["oh-my-openagent"]` into your
`opencode.json` and its own config into `~/.omo/omo.jsonc`.

Because the default agent-to-model mapping assumes Claude/GPT, point the agents at Gemini.
Open `~/.omo/omo.jsonc` and make sure the main agents use Gemini, e.g.:

```jsonc
{
  "agents": {
    "sisyphus":  { "model": "google/gemini-2.5-pro" },
    "oracle":    { "model": "google/gemini-2.5-pro" },
    "librarian": { "model": "google/gemini-2.5-flash" },
    "explore":   { "model": "google/gemini-2.5-flash" }
  }
}
```

(Use the newest Gemini Pro/Flash your key has access to; the ids above are the safe fallback.)

Verify:

```bash
bunx oh-my-openagent doctor
```

Then start `opencode` inside the starter repo (next step). Sisyphus should be the default
agent. Type `ulw` (ultrawork) in front of a task to let it plan and delegate.

The starter repo already contains an `opencode.json` that references the plugin and an
`AGENTS.md` that tells the agents the project rules. Do not run `/init`; the file is there.

---

## 4. Clone and run the starter

```bash
git clone <internal-git-url>/resilient-gateway-starter.git
cd resilient-gateway-starter
```

Create the environment (pick one):

```bash
# uv (fast)
uv sync --extra dev
```

```bash
# plain venv, macOS/Linux/WSL
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```powershell
# plain venv, Windows PowerShell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Copy the env template and fill in the Gemini key (leave `MOCK_AZURE=true` for now):

```bash
cp .env.example .env
```

Run the tests. They must be green before you touch anything:

```bash
pytest -q
```

Start the gateway and fire one synthetic alert (two terminals):

```bash
uvicorn gateway.main:app --reload --port 8080
```

```bash
python -m simulator.alert_generator --scenario cpu_spike --count 1
```

You should see a `TriageDecision` in the gateway log with `decision_source: "deterministic_fallback"`.
That is the untouched starter: the agent is a stub, so everything falls back. Your job today
is to make the agent path win without losing that fallback.

Optional live model check (uses your key, costs a fraction of an øre):

```bash
python -m gateway.agent.llm --ping
```

---

## 5. Azure CLI login

```bash
az login
az account set --subscription "GPT Initium"     # e419a266-2639-4134-9ded-7a777b020ae9
az account show --query "{sub:name, user:user.name}" -o table
az group show --name VilluResourceGroup --query location -o tsv
```

If `az login` cannot open a browser (WSL, SSH):

```bash
az login --use-device-code
```

Then in `.env` set `MOCK_AZURE=false` and fill in `LOG_ANALYTICS_WORKSPACE_ID` (the facilitator
posts it). Check the MCP tools reach Azure:

```bash
python -m mcp_server.server --self-test
```

Cost guard: the resource group has a NOK 500/month budget with alerts at 25/50/100/250. Log
Analytics queries are cheap; do not create new resources without asking the infra owner.

---

## 6. Optional: Kafka instead of REST

```bash
docker compose up -d redpanda
python -m simulator.alert_generator --sink kafka --scenario mixed --rate 5
```

Set `STREAM_SOURCE=kafka` in `.env`. The REST path stays available for the eval harness.

---

## 7. Approved endpoints for today

| Endpoint | Purpose |
|----------|---------|
| `generativelanguage.googleapis.com` | Gemini API |
| `management.azure.com`, `api.loganalytics.io`, `login.microsoftonline.com` | Azure |
| `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `opencode.ai`, `bun.sh` | Packages and tooling |
| `docker.io`, `ghcr.io` | Container images |

Anything else is a new external endpoint: ask the facilitator first (rule of the day).

---

## Checklist (raise a hand when done)

- [ ] `opencode --version` ≥ 1.4.0
- [ ] `/models` in OpenCode lists Gemini models
- [ ] `bunx oh-my-openagent doctor` is happy; Sisyphus answers in the starter repo
- [ ] `pytest -q` green in the starter
- [ ] One synthetic alert produced a `TriageDecision`
- [ ] `az account show` shows subscription `GPT Initium`
