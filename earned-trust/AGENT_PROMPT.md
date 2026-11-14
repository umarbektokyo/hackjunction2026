# Agent brief: Earned Trust in AI Code (Tieto, Junction 2026)

You are building our team's entry for Tieto's **Earned Trust in AI Code** challenge at Junction 2026
(Espoo, 13–15 Nov 2026). Judging is **Sunday 15 Nov**; today is Saturday 14 Nov. Time is the main
constraint: a finished, polished, small thing beats an ambitious unfinished one. When this is done,
the team moves on to `break-the-agent/`, so finish cleanly and leave clear notes.

Work only inside `earned-trust/` in the repo at `/Users/umarbek/Documents/claude/hackjunction2026`.
Do not touch `spread/`, `break-the-agent/`, `decode-the-noise/` or `nullfellows/`. Do not commit or
push; the team reviews and commits.

## 1. Read first (before planning)

- `challenges/main/earned-trust-in-ai-code.md` — the full brief, deliverables and judging criteria.
  Re-read the judging criteria before every major decision:
  - **Clarity 30%**: a clear recommendation with stated principles, explicit trade-offs and limits.
  - **Practicality 25%**: works in a real PR flow and scales, with a *named human* owning each decision.
  - **Measurement 25%**: how trust is measured (reverts/incidents don't rise as review time falls,
    AI findings real and accepted, time to merge, share routed to humans).
  - **Evidence 20%**: evidence traceable to a requirement lets a named human accept a change without a
    full read, incl. what the AI found, what it **refused to decide**, and why.
- `ANTONINA.md` (repo root), section "Earned Trust in AI Code" — the team's original idea. Use it as
  inspiration, not a spec (see section 3).
- The sample code: `https://github.com/te-industry-tech-office/junction26-messagepack-csharp`. Clone
  it into `earned-trust/sample-repo/` (gitignored). Branches with agent-written changes:
  `ju26-issue-2283` (4 files), `ju26-issue-2234` (4 files), `ju26-issue-2129` (28 files),
  `ju26-issue-2297` (237 files). Upstream issues are on `MessagePack-CSharp/MessagePack-CSharp`.
  **Start with `ju26-issue-2283` only.** Add a second branch only if everything else is done.
- The hackathon page `https://hackjunction.app/participate/45/challenges/351` may have more
  material (Tieto's requirements set, coding standards). If you can't reach it, carry on and list
  what's missing in your report.

## 2. Plan before building

Write `earned-trust/PLAN.md` before writing app code:
- The concept in one paragraph and its 4–6 principles (how it balances risk, hallucination,
  transparency, confidence and quality).
- The reviewer's walkthrough screen by screen, mapped to the four judging criteria.
- Architecture and data flow, the smallest that works.
- Build steps in order, each with a "done when".
- Risks and what you'll cut first if time runs out.

Then build it. Don't wait for approval unless you're blocked (see section 6).

## 3. The concept to build towards

The challenge asks: *is line-by-line review still the right way?* Our answer: the PR arrives as an
**evidence dossier**, not a diff. The reviewer checks a story rather than hunting for bugs.

Starting ideas from the team (keep what serves the criteria):
- Split the change into **units** (changed functions/methods). For each unit, show: the requirement
  ID it serves; its blast radius (who calls it, what it calls, which callers' inputs and outputs
  change); AI-generated tests and their **actual** results; the AI's confidence per claim.
- A **refusal list**: things the AI explicitly won't decide, with the reason, routed to a named
  human. The team's example: a config change that looks harmless (a `*` wildcard) but grants access
  to a secret. Security, public API changes, and requirement ambiguity are good refusal categories.
- **Sign-off**: a named human accepts or rejects each routed item; the decision is recorded with the
  evidence it was based on.
- **Measurement**: a panel describing how trust would be measured in production (the brief's metrics),
  with whatever you actually measured on the sample (e.g. share of units auto-cleared vs routed,
  generated tests that pass/fail, findings confirmed by a human).

Drop from the original idea: the custom git server, the visual-component gallery (the sample is C#,
no UI), and splitting whole apps into visual/data/logic layers. Requirement IDs: Tieto said they'd
bring a requirements set. If you can't find it, derive requirements from the upstream GitHub issue,
give them IDs like `REQ-2283-1`, and label them as derived in the UI.

## 4. Technology and code size

- **Minimise code.** Every file must earn its place. No speculative abstractions, no feature flags,
  no plugin systems.
- **One language: Python** (3.11+, a `venv` or `uv` in `earned-trust/`), for both the analysis and the
  UI. Prefer the standard library; add a dependency only when it removes real code.
- **UI: BUI** (`https://github.com/ppmpreetham/BUI`, `pip install blenderui`): a native desktop UI
  library that draws Blender's widgets, with a Python API (45 components incl. panels and a node
  editor). Its node editor suits showing changed functions and their callers as a graph. Caveats:
  GPL-3.0 (fine for a hackathon entry), and macOS support is marked partial/experimental, while
  this machine is macOS. **Spike first (max 45 minutes):** install it and render a window with a
  panel, a list and a node graph from sample data. If that doesn't work cleanly, stop and fall back to
  a static **SvelteKit** site reading the same JSON. Log the outcome in `DECISIONS.md`.
- Preferred shape: a Python script analyses the branch and calls the LLM once, writing a **dossier
  JSON** to disk. The UI only reads that JSON. The demo then runs offline, deterministically and fast,
  with no API calls during the presentation.
- `earned-trust/PLAN.md`, `DECISIONS.md`, `input/` and `dossier/` may exist from an earlier attempt
  that planned a Go + SvelteKit stack. Reuse what's useful and update them for this stack.
- Available on this machine: Python, Go, Node, pnpm, git, gh. **Not installed: dotnet**, and no LLM
  API key is set in the environment.
  - LLM: read the key from an env var (e.g. `ANTHROPIC_API_KEY`), never hard-code it, and cache
    responses in the dossier JSON. Default to the latest Claude models. If no key is available, build
    everything else with a clearly marked hand-written dossier and report the blocker.
  - C# test execution needs the .NET SDK. Do not install it or other system software yourself.
    Build the rest, mark generated-test results as "not run" in the dossier, and report the blocker.
    Never present tests as passing unless they were actually run.

## 5. Design

Judges stress design and we must not look vibe-coded.
- Lean into BUI's look: a dense, professional tool (Blender-style panels, dark theme), which reads as
  a real engineering tool rather than a generated web page. Keep it consistent: one accent colour for
  "needs a human", monospace for code and data, no emoji.
- Information hierarchy does the work. Every number shown should mean something. The reviewer must
  see in the first screen: what changed, which requirement, what the AI cleared, what it refused and
  who has to decide.
- Check it at laptop resolution and on a projector-sized window (large text). Fix anything cramped.

## 6. Deliverables (all in `earned-trust/`)

1. The app, runnable with one command documented in `README.md` (e.g. `./run.sh`).
2. `CONCEPT.md`: the concept card — recommendation, principles, trade-offs, limits.
3. `DECISIONS.md`: a short log of decisions as you make them (date, decision, why). Start it on day one.
4. `LESSONS.md`: failure modes seen (including the AI's own mistakes on the sample) and lessons.
5. `DEMO.md`: a 3–5 minute walkthrough script for the live demo and video, following the reviewer's
   path and naming where each judging criterion is shown.

## 7. Rules for honesty

- Everything the UI calls evidence must be real and traceable: line numbers, call sites, test runs.
  Anything hand-written or simulated is labelled as such in the UI.
- Confidence values must come from somewhere stated (model self-report, test results, static checks),
  not invented.
- Use only synthetic or public sample data.

## 8. When you finish (or get blocked)

Report back with: what's built and how to run it; what you verified yourself (and how); what is
not done or not verified; blockers needing the team (dotnet, API key, Tieto material); the top three
things to improve if there's more time.
