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
| **Instructor guide**: infrastructure, pre-event timeline, run sheet, scoring procedure, helper cheat sheet | [docs/06-instructor-guide.md](docs/06-instructor-guide.md) |
| Slide deck for the day | [slides/hackathon-slides.pptx](slides/hackathon-slides.pptx) |
| Starter repository for participants (Python, tested) | [starter/](starter/README.md) |

Source material (original brief, the client team's AI guidelines used as the intro example, Azure
CLI transcripts) and the reference solution live in the private repo `Villu/hackathon-private`,
checked out locally as `private/` (git-ignored here).

## Before the event

See the timeline in [docs/06-instructor-guide.md](docs/06-instructor-guide.md) §4. In short: push
`starter/` for teams, one Gemini key per team, `starter/scripts/azure_bootstrap.sh resume` +
`grant`, pre-event install mail, one timed OpenCode dry run.

## Verified in this package (2026-11-04)

- Starter: `pytest -q` → 47 passed, 5 xfailed (the participants' TODOs), `ruff` clean, on
  Windows (Python 3.14) and Linux (3.12). macOS not tested.
- Reference solution (private repo) with every TODO done: live Gemini + mock Azure 46/47 on all
  18 golden cases (p50 enrichment 2.4 s); live Gemini + live Azure 47/47; chaos 25/25 + injection
  6/6 in mock mode. Untouched starter: 32–33/47, chaos 12/25, injection 3/6.
- Azure: `azure_bootstrap.sh up` run against `GPT Initium`; all five MCP tools verified live
  (revisions, logs, resource state); apps currently paused.
- Organiser scoring script (`hackathon-private/scoring/score_team.sh`) run end to end on sepman.net.
- Not verified: OpenCode + oh-my-openagent timing for the TODOs, a clean macOS setup,
  participant role grants (no participant list yet).
