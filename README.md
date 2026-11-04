# Hackathon: Resilient Agentic Gateways for Enterprise Event Streams

One-day hackathon package for Webstep. Teams build an event-driven AI gateway that triages
infrastructure alerts with a Gemini agent, MCP tools against Azure, and a deterministic
reliability layer, using OpenCode + oh-my-openagent.

| What | Where |
|------|-------|
| Day plan, schedule, roles, pre-event checklist, risks | [docs/01-hackathon-plan.md](docs/01-hackathon-plan.md) |
| 30-minute "AI-assisted development" briefing (client example as intro, Webstep rules) | [docs/02-ai-usage-briefing.md](docs/02-ai-usage-briefing.md) |
| Setup guide: OpenCode, oh-my-openagent, Gemini, Azure CLI, starter | [docs/03-setup-guide.md](docs/03-setup-guide.md) |
| Software specification (contracts, deliverables, chaos modes, config, API) | [docs/04-software-spec.md](docs/04-software-spec.md) |
| Judging rubric (100 points, printable) | [docs/05-judging-rubric.md](docs/05-judging-rubric.md) |
| Slide deck for the day | [slides/hackathon-slides.pptx](slides/hackathon-slides.pptx) |
| Starter repository for participants (Python, tested) | [starter/](starter/README.md) |

Source material (original brief, the client team's AI guidelines used as the intro example, Azure
CLI transcripts) and the reference solution live in the private repo `Villu/hackathon-private`,
checked out locally as `private/` (git-ignored here).

## Before the event

1. Push `starter/` to the internal Git as its own repository (`git init` inside it; `.gitignore` is in place).
2. Run `starter/scripts/azure_bootstrap.sh` once with `az login` to create the Log Analytics
   workspace and the sample Container App; post the workspace id to participants.
3. Distribute one Gemini key per team via the password manager.
4. Walk through `docs/03-setup-guide.md` on a clean laptop and note the versions.

## Verified in this package

- Starter: `pytest -q` → 47 passed, 5 xfailed (the xfails are the participants' TODOs), `ruff` clean.
- Running gateway with the MCP subprocess, the alert simulator (all three payload shapes), the
  golden-set runner and the chaos runner were exercised locally in mock mode.
- Not exercised: live Gemini calls (no key on the build machine) and the Azure backend
  (no `az` on the build machine). Both are isolated behind `LLM_PROVIDER` / `MOCK_AZURE` flags.
