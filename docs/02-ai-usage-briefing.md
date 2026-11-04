# AI-assisted development: how we work — 30-minute briefing (10:00–10:30)

Speaker notes for the facilitator. The block opens with a short **client example** (a
development team at Statnett OIS and its team rules for Copilot and OpenCode, from the team's
own AI-usage page, February 2026), then generalises into principles that hold on any Webstep
engagement, and ends with the Webstep rules for the hackathon. No client-internal document
names or codes are used; the principles are paraphrased.

Goal of the block: everyone leaves knowing (1) which tools they may use on which data,
(2) what a mature team practice for AI-generated code looks like, and (3) the Webstep rules
for today.

---

## Timing

| Min | Section |
|-----|---------|
| 0–3 | Why this matters: AI-assisted coding is standard at our clients. Speed is not the risk; *unowned* code is |
| 3–10 | Intro: a client team's AI rules (Statnett OIS example) |
| 10–17 | Five principles that travel |
| 17–23 | Responsible AI use as a consultant |
| 23–28 | What applies today at Webstep |
| 28–30 | Questions |

---

## 1. Intro: a client team's AI rules (example)

A development team at Statnett OIS uses GitHub Copilot in the development process and has
adopted OpenCode. Their eight team rules, condensed:

1. Følg kundens retningslinjer for KI. **Ikke koble til eksterne endepunkter uten tillatelse.**
2. Alle bidrar til å videreutvikle rammeverket med **skills, agents og liknende**.
3. Alltid **to utviklere involvert før kode merges til master**.
4. Den som skriver/genererer kode skal **forstå det som produseres og ha eierskap** til det.
5. Egen QA: **fjern overflødige KI-spor** som massiv testgenerering.
6. **Små endringer**: lettere å gjøre QA og forstå hva koden gjør.
7. Sørg for at det **ikke blir alt for mye tekst**.
8. Den som tar review skal **ta ordentlig review selv om det er KI involvert**.

From the same team's onboarding: AI-generated code must be quality assured, you are
responsible for the code you write or generate, and a proper code review is still required.

Talking points:
- Rule 1 is the one an eager agent breaks first: an MCP tool that calls a new external API is
  a new endpoint. Approved endpoints for today are listed in the setup guide.
- Rule 2 is why oh-my-openagent matters: agents, skills and hooks are a framework the whole
  team is expected to keep improving.
- Rules 4–7 are what judges look for in the "AI-workflow hygiene" criterion.
- We take this practice as the baseline for Webstep today.

---

## 2. Five principles that travel

Distilled from the AI guidelines we meet at clients, generalised so they hold anywhere:

1. **Bruk KI der det gir reell verdi.** Ask whether AI actually makes the task faster, better or more efficient.
2. **Vær kritisk og kvalitetssikre alt.** AI is a tool, not a replacement for professional judgement. Double-check facts, assess risk and the consequences of errors.
3. **Bruk kun godkjente verktøy på kundedata.** Protect client information. Public chatbots are for open information only; check what the client has approved for each information class.
4. **Start smått, lær og skaler.** Begin with simple tasks, build experience, expand gradually.
5. **Du eier resultatet.** You are responsible for what is produced and shared onward. Label AI-generated content before it leaves your hands.

Talking point: the hackathon is a "start smått" exercise with real stakes, an agent that
touches infrastructure. Principle 2 becomes an architecture requirement, not a slogan:
deadline, confidence gate, allowlist and deterministic fallback are principle 2 in code.

---

## 3. Responsible AI use as a consultant

| Theme | What it asks of you |
|-------|---------------------|
| **Know the data** | Where does it live, how is it classified and protected? Is the tool approved for that class? Is the data suitable for AI (structure, quality, maturity)? |
| **Approved services only** | Client-approved AI services for client information. Public chatbots only for open information. A new endpoint is a new approval: ask first |
| **Verify and label** | QA AI output before you use or share it. Label AI-generated content. You own what you share onward |
| **Assess what you build** | Purpose: what can the system generate or expose? Robustness, security, privacy, explainability, non-discrimination. Place it in the right **AI Act** risk category |

Talking point: today's gateway reads observability data and *recommends* remediation. Ask the
room which AI Act category that is, and why "recommend" versus "execute" changes the answer.
This is exactly why the spec keeps remediation behind an allowlist and a human.

---

## 4. What applies today (Webstep hackathon rules of engagement)

| Principle | Today at Webstep |
|-----------|------------------|
| Approved tools only | OpenCode + oh-my-openagent with the Gemini key you were given, Azure via `az login`. No other LLM endpoints, no client data in public chatbots |
| Data classification | Everything in the starter and in `VilluResourceGroup` is synthetic / open. Do not import real client alerts or logs |
| No external endpoints without permission | Allowed: Gemini API, Azure management/monitor APIs, PyPI, npm, Docker Hub. Anything else: ask the facilitator first |
| Two developers before merge | Pair on every merge to your team's main branch, even at 15:25 |
| Understand and own generated code | In the demo each team explains one generated function line by line. Judges may ask "why is this here?" |
| Remove AI noise | No 400-line test files nobody read. No essays in docstrings. Small commits |
| Label AI-generated content | Commit messages or PR descriptions state when code was agent-generated (`Co-authored-by` or a one-line note) |
| Proper review even with AI | The reviewer runs the tests and the eval harness, not just a skim |

Closing line: the agent you build today will have the same problem you have. It can produce
confident output fast. The reliability layer is you applying principle 2 to the machine.
