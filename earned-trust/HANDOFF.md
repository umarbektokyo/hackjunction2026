# Hand-over: Earned Trust reviewer (state on 14 Nov 2026, judging 15 Nov)

Read this before touching anything. `AGENT_PROMPT.md` is the original brief and is **out of date on
the UI** (it asks for BUI/Blender widgets; the team rejected that). This file wins where they differ.

## What the team wants (the concept, in their words)

"Think of it as GitHub Desktop, but the unit is a function instead of a file." Every function is
its own node, treated almost as a separate file. You review a function by seeing:

- on top: the **mentions**, the real lines in other functions that call it;
- in the middle: its **diff**;
- at the bottom: the **calls**, the functions it calls;
- its **tests**, clearly visible.

It should feel like "an overly powerful text editor", in a **teenage engineering** style: minimal,
beautiful, only essential information. One orange accent, light warm grey, thin lines, small
uppercase mono labels.

### What was tried and rejected (do not bring back)

1. **BUI / Blender desktop UI, four tabs.** "Looks so bad and complicated."
2. **Node map with a side panel.** "Random boxes with text flying around." Also rejected with it:
   the four gates with pass/fail, evidence/check lists, real/not-real buttons, the bottom strip of
   numbers, big verdict numerals. The user asked "what is pass/fail, what is all the extra stuff?"
3. Current version (three-pane editor) was received as "yes, it is closer".

Rule of thumb: if an element does not help answer "what changed here, what does it touch, is it
tested, who decides", it does not go on screen. Put it in `CONCEPT.md` instead. When unsure about a
UX direction, ask the user for a reference product before building; that is what finally worked.

## Done on 14 Nov afternoon (the three UI tasks from the morning hand-over)

All in `web/index.html`, checked by headless Chromium screenshots at 1600×1000 (not yet by the
user at full size; they saw the earlier version and said "yes, it is closer").

1. **Right pane cut down.** Status label, one-line summary, the question box with its buttons.
   "Why the AI refuses" is a `<details>` inside the box. "The AI noticed" is titles only; each
   expands to its text and the suggested tests for that note (`proposed_tests[].for === finding.id`).
   The test list and the "exercises" list are gone from the right pane; a test unit shows one line
   (status + why not run).
2. **Diff formatting.** `line()` turns leading whitespace into a hanging indent (CSS var `--i`,
   wrapped lines indent 4ch more), wraps with `overflow-wrap: anywhere`, mutes comment lines, and
   takes an optional `[start, end)` range for **intraline highlighting**. `changed(a, b)` cuts the
   common prefix and suffix of a removed/added pair, snapped to whole words; `renderEditor` pairs
   each run of `-` lines with the `+` run after it.
3. **Left bar dimming.** `testsOf(unit)` = `covered_by` tests plus the test-tier helpers they call,
   transitively. `related(selection)`: code unit → `testsOf`; test or helper → union of `testsOf`
   for every code unit that owns it; docs → no dimming. Unrelated test rows get `.dim`.

Also: `#<unit id>` in the URL opens that unit (handy for demo and screenshots, e.g.
`http://localhost:8283/#TypeCollector.cs:GetObjectInfo`); `.row` had `box-sizing` reset by
`button { all: unset }`, which caused a horizontal scrollbar in the list (fixed); long file paths
in the editor's top bar ellipsize from the left. `DEMO.md` "Tests" section updated.

## Done on 14 Nov, later (user questions: whole function, tests, dots, commits)

- **Whole function in the editor.** The dossier stores `unit.body` (the unit's lines at head);
  `whole(u)` in `web/index.html` merges the diff back in. In units over 60 lines, unchanged
  stretches more than 3 lines from a change fold into "⋯ N unchanged lines" (click to open).
- **Tests run for real, twice.** `evidence.run_tests` runs `dotnet test` in two worktrees under
  `.work/` (gitignored): the head, and the head with `src/` reverted to base. A test proves the fix
  only if it passes with the change and fails without it (`proves_fix`); the *executed* gate needs
  that. 2283: 3 of 3 prove the fix (without it they crash with the issue's IndexOutOfRangeException).
  Needs .NET 8: `nix develop /home/ayo/Projects/hackjunction2026/earned-trust -c ./run.sh` (the
  flake is on `main`). Without dotnet tests show "not run", as before.
- **Dots explain themselves on hover** (`MEANS` in the page; test dots use the test's `why`).
  New dot: hollow orange = passes but does not test the fix. "held" now reads "not proven by a test".
- **Stale hand-written findings:** F-notes on GetObjectInfo ("Which site crashed is not
  established", "The new tests do not reach either…") are contradicted by the test run now. Ask
  Umarbek / the user before rewriting them; the real fix is task 2 below.

## Next tasks (judging is 15 Nov)

1. **Ask the user to look at the page at full size** and react; do not add elements unasked.
2. **Switch between the four changes (the user asked for this).** Each Tieto branch is one agent
   commit; only 2283 has a dossier. Plan: a switcher in the left header (`/api/state?case=N`,
   `serve.py` serving every `dossier/*.json`), `input/<N>/case.json` per branch (base is
   `origin/HEAD`'s merge-base, not `master`), and the review layer from task 3. 2297 touches 222
   generated `.g.cs` files: group them into one unit per template, not 222 rows.
3. **Feed real evidence into this UI.** `main` has a second half of this entry (see below): real
   Claude reviews of all four Tieto branches in `earned-trust/reports/REQ-*/report.json` (claims,
   verdicts, evidence pointers file:line, routed questions). Replace `input/2283/review.handwritten.json`
   with an adapter from `REQ-2283/report.json`, then add the other three branches. Biggest gain left.
4. **Merge the two halves.** Both live in `earned-trust/` and both have README, CONCEPT, LESSONS:
   a plain `git merge` will conflict. Agree a layout with the user and Umarbek first (suggestion:
   CLI + reports at `earned-trust/`, this reviewer at `earned-trust/reviewer/`).
5. Slides (5), a 3-minute demo, a backup video.

Not built, raised by the user: a **visual before/after gallery for UI components**. The Tieto
sample is a C# library with no UI, so there is nothing to render. Ask before starting.

## The other half, on `main`: `cev` (claims → evidence → verdict)

`earned-trust/` on `main` (TypeScript, Node 22 via `nix develop`; plain shell has no node/pnpm):

- `node dist/cli.js review ...` asks the logged-in `claude` CLI for claims, verifies each with
  read-only tools on HEAD and BASE, writes `reports/REQ-*/report.{md,json}`. Done for all four
  branches ($6.49). Base is `origin/HEAD`, not `origin/master`.
- `node dist/cli.js metrics` → `reports/METRICS.md`: per change and across changes (share routed,
  review load in lines/places, findings, findings accepted, agreement, time to decision, cost;
  reverts stated as not measurable yet). Everything computed from reports + `decisions/log.jsonl`.
- `decisions/sign.sh "Name"` records three proposed rejects (2234, 2297, 2283), with 2297 C11
  answered from git. **Not run: the user must sign as the accountable human.** Do not sign for them.
- `nix develop` now also has the .NET 8 SDK downloaded: `review ... --exec` can run the tests
  (slow first build). 2129 is waiting for that before a decision.
- Sample repo for both halves: `sample-repo/` here (gitignored, all branches fetched).

## How it works

```
./run.sh        # rebuilds dossier/2283.json, serves http://localhost:8283 (plain python3, no venv)
```

- `trust/build.py` builds the dossier from `sample-repo` (gitignored clone of Tieto's repo, branch
  `ju26-issue-2283`; `run.sh` clones it if missing) and `input/2283/`.
- `trust/units.py` splits the diff into units (changed C# members, test methods, Markdown sections).
- `trust/evidence.py` finds callers with code excerpts (`unit.callers[].excerpt`, two levels),
  outgoing calls with signatures (`unit.calls`), runs checks, runs tests if `dotnet` exists, and
  sets each unit's status: `cleared`, `held` (tests not run) or `routed` (AI refuses to decide).
- `trust/review.py`: the AI's review text. Hand-written in `input/2283/review.handwritten.json`
  because there is no API key; `--llm` would call Claude once and cache it (untested).
- `trust/serve.py`: standard-library server. `GET /api/state`, `POST /api/decide`.
- `trust/decisions.py`: sign-off records in `decisions/` (gitignored). `rm -rf decisions` before a demo.
- `.claude/launch.json` (repo root) lets the Claude desktop Browser pane start the server.

UI wording for the three statuses: "checked · safe to skip" (black dot), "waiting for a test run"
(ring), "needs a decision · <owner>" (orange). Keep it that plain.

## Honest state

- Verified: dossier builds (13 units: 6 cleared, 2 held, 5 routed; 24 of 24 checks hold); every
  unit renders with no console errors; decisions are recorded and the merge stays blocked.
- Not verified: the page at full size by a human; the `--llm` path; real `dotnet test` output
  parsing. All tests show "not run" because .NET is not installed. Never show a test as passing
  unless it ran.
- Missing from Tieto: their requirements set and coding standards (requirements are derived from
  the GitHub issue and labelled so). Owners are synthetic names.
- Docs: `CONCEPT.md` (concept card for judges), `DEMO.md` (script for the current three-pane UI),
  `LESSONS.md`, `DECISIONS.md`, `PLAN.md`. Update `DEMO.md` when the UI changes. `CONCEPT.md` still
  describes gates and metrics; that is fine there, it is the reasoning behind the screen.

## Working with this team

- Keep the code small, clean and modular. No new dependencies without a reason.
- Do not touch the other project folders (`spread/`, `break-the-agent/`, `decode-the-noise/`,
  `nullfellows/`).
- Show the user a screenshot early and often. Do not add information to the screen unasked.
