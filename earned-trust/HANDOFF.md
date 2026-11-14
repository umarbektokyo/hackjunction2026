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

## Next tasks, in the user's priority order

All three are in `web/index.html` (one file, plain HTML/CSS/JS, no build step).

1. **Right pane is still too cluttered.** Suggested cut: keep the status label, the one-line
   summary and the question box with its buttons. Fold "why the AI refuses" behind a `<details>`.
   Show "the AI noticed" as titles only, each expandable, with the suggested tests (dashed rows
   today) inside the related note. Remove the test list from the right pane once task 3 is done:
   the left bar and the editor's top bar then carry the tests.
2. **Diff should have proper formatting, not big blobs of text.** Long C# lines currently wrap with
   `word-break: break-all` and lose their indentation. Suggested: keep indentation with a hanging
   indent (leading spaces → `padding-left: Nch`, negative `text-indent`), wrap with
   `overflow-wrap: anywhere`, mute comment lines, and add **intraline highlighting**: for a
   removed/added pair, find the common prefix and suffix and emphasise only the part that changed
   (see unit `TypeCollector.cs:GetObjectInfo`, lines 985 and 1077, for the worst case). The same
   `line()` helper renders mentions, calls and test source, so fix it once.
3. **Left bar: dim unrelated tests.** When a code function is selected, grey out every row under
   TESTS except the tests for that function (`unit.covered_by` holds their names; include the
   helpers those tests call, via `unit.calls`). When a test is selected, the picture stays the
   same: tests that belong to the same code as the selected test stay normal, the others are grey.
   A function with no tests (`GetPropertyIdentifierLocation`) greys all of them. Docs: no dimming.

After those: check the page at real size in a browser and ask the user to look; the previous model
only saw it scaled down in a small preview pane.

Not built, raised by the user: a **visual before/after gallery for UI components**. The Tieto
sample is a C# library with no UI, so there is nothing to render. It would need a separate sample
project; ask before starting.

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
