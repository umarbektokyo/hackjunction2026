# Decisions log

| Date | Decision | Why |
|------|----------|-----|
| 2026-11-14 | Sample: branch `ju26-issue-2283` only (4 files, 194 non-blank changed lines). | Small enough to analyse fully and honestly in a day. |
| 2026-11-14 | Requirements derived from upstream issue #2283 as `REQ-2283-1..5`, labelled *derived*; REQ-5 labelled *implicit*. | Tieto's requirements set was not reachable (challenge page renders no content without login). |
| 2026-11-14 | Stack changed from Go + SvelteKit (earlier attempt) to Python + BUI, per the new brief. | One language for analysis and UI; native tool look. |
| 2026-11-14 | BUI spike passed: panel, list and node editor render headlessly, native window opens on macOS (Python 3.14, blenderui 0.5.1). Kept BUI, no SvelteKit fallback. | Within the 45-minute budget, no blockers. |
| 2026-11-14 | Whole UI in Menlo, no bold. | BUI sets the font globally (no per-label monospace); synthetic bold smears. Hierarchy from size and one accent colour. |
| 2026-11-14 | Deterministic builder computes units, line numbers, callers, checks and gates; the model only writes the review layer. | Evidence must be traceable; the model proposes claims, the builder executes them. |
| 2026-11-14 | Every model claim is a *check* (regex over named files at the head commit, with an expectation). A finding's confidence shows which checks back it, or *model only*. No numeric confidence. | Confidence must come from somewhere stated. |
| 2026-11-14 | No `ANTHROPIC_API_KEY`: review layer hand-written (`input/2283/review.handwritten.json`) in the model's output shape, labelled in the UI header. LLM path (`--llm`, `claude-opus-5-5`, one streamed call, cached to `review.llm.json`) written but untested. | The brief says build everything else and report the blocker. |
| 2026-11-14 | No .NET SDK: all tests *not run*; the executed gate stays open for shipped code; the runner reports only passes it parsed from `dotnet test` output. | Never present tests as passing unless they ran. |
| 2026-11-14 | Risk tier by path: `src/` = shipped (needs execution), `tests/` = test, `*.md` = doc (checks enough). | Evidence scales with risk; tier is not the model's opinion. |
| 2026-11-14 | Units split by indentation and brace counting, not a C# parser; blank-only lines belong to no unit; builder asserts full coverage. | Smallest thing that is right for the sample; stated as a limit. |
| 2026-11-14 | Callers found by `git grep` by name, two levels; unqualified calls count only in the declaring file, qualified only as `Class.Member(`. | A local function `Collect` in the generator produced a false caller. |
| 2026-11-14 | Ran an independent audit of the dossier as a separate read-only agent; folded in its results (MsgPack004 is an Error; unkeyed test passes because of the filter; no red/green evidence; F8). | A reviewer of the reviewer, as the concept asks of the AI. |
| 2026-11-14 | Owners are synthetic names in `input/owners.json`, one per routing category, plus an approver. | Only synthetic data; the routing mechanism is the point. |
| 2026-11-14 | Sign-off stored append-only in `decisions/<issue>.json` with owner, time, evidence IDs and the dossier hash; merge button disabled while anything is routed-undecided, rejected or held. | Smallest thing that shows an accountable, evidence-linked decision. |
| 2026-11-14 | Dossier JSON is committed; the UI only reads it. | Offline, deterministic demo; no API calls during the presentation. |
| 2026-11-14 | Dropped the BUI window for one static page (`web/index.html`) served by a standard-library Python server. | The team found the Blender-style UI dense and far from the idea: functions as nodes, minimal, teenage-engineering feel. The brief allowed a web fallback. |
| 2026-11-14 | The page shows only what a reviewer needs: verdict, node map, one unit's evidence, the decision, six measured numbers. Principles, production metrics and the category policy live in CONCEPT.md, not on screen. | "Only what is needed." Every element on screen answers: what changed, is it safe, who decides. |
| 2026-11-14 | No UI dependencies and no build step; the app runs on plain `python3`. | Less code, nothing to install at the venue. |
| 2026-11-14 | Third UI: a three-pane editor, like a Git client where the unit is a function, not a file. Mentions on top, the diff, the calls it makes below; tests and the AI's question on the right. Removed the node map, the gate row, evidence lists, real/not-real buttons and the number strip. | The team's concept is "each function is its own file, reviewed with the lines around it". Gates and counters were our jargon; they stay in the dossier JSON and CONCEPT.md. |
| 2026-11-14 | Builder now stores code context around every caller and the same-file functions each unit calls, with signatures. | The editor needs real lines, not names. |
