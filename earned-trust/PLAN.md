# PLAN: Earned Trust in AI Code (Tieto, Junction 2026)

## Concept

An agent-written pull request should arrive as an **evidence dossier**, not a diff. The dossier
splits the change into **units** (changed methods, test helpers, doc sections), ties every unit to
a requirement ID, and puts each one through four **gates**: *traced* (it serves a requirement),
*checked* (deterministic checks back the AI's claims about it), *executed* (the tests that cover it
actually ran and passed) and *uncontested* (the AI has not refused to decide something about it).
Units that pass every gate their risk tier demands are **cleared** without a human read. Units that
lack evidence are **held**, with the missing evidence named. Units the AI **refuses** to decide on
are **routed** to a named owner, with the question, the reason and the evidence. The human reads the
story, not the diff, and signs off item by item. Trust is not assumed: it is earned per category,
measured over time, and lost on a revert.

### Principles

1. **Evidence scales with risk.** Shipped code needs executed evidence; test and doc code needs
   checked evidence. The tier comes from the path, not from the model's opinion. (risk)
2. **No claim without a check.** A model claim is labelled *model only* unless a deterministic
   check (pattern match, call-site search, test run) backs it. Confidence states its source.
   (hallucination, confidence)
3. **Refusal is a feature.** Policy changes, public contracts, security and requirement ambiguity
   are not the AI's to decide. It says what it won't decide, why, and who owns it. (transparency)
4. **A named human owns every decision.** Each routed item has an owner from a routing table, and
   each decision is recorded with the evidence IDs it rested on. (accountability)
5. **Missing evidence is shown, never filled in.** "Not run" is a state, not a pass. (quality)
6. **Trust is earned per category and measured.** Auto-clear widens only while reverts and
   incidents stay flat as review time falls, and narrows on the first revert. (measurement)

## Reviewer walkthrough (one page, three panes, like a Git client for functions)

| Pane | What the reviewer sees | Criterion |
|------|------------------------|-----------|
| Left | The changed functions, tests and doc sections as a list (dot = safe to skip, ring = waiting for tests, orange = needs a decision); the merge state and its owner | Clarity, Practicality |
| Middle | One editor buffer for the selected function: the lines that mention it (callers, with context), its diff, the functions it calls (with signatures). Names are links, so you walk the code | Evidence |
| Right | The AI's one-line summary, the question it refuses to decide with the owner's buttons, the tests for this function with their real status and source, what the AI noticed | Evidence, Practicality |

## Architecture (smallest that works)

```
sample-repo (git) ─┐
input/<issue>/     ├─> python3 -m trust.build ──> dossier/<issue>.json ──> python3 -m trust.serve
  issue.md         │     git diff, unit split, callers (git grep),          (stdlib server + one
  owners.json      │     checks, test run (if dotnet), gates, counts         HTML page; writes
  review.*.json  ──┘     review layer: review.llm.json (one cached call)     decisions/)
                         or review.handwritten.json (labelled)
```

- `trust/gitdiff.py` diff → hunks; `trust/units.py` hunks → units; `trust/evidence.py` callers,
  checks, tests, gates; `trust/review.py` review layer; `trust/build.py` assembles the dossier;
  `trust/decisions.py` sign-off; `trust/serve.py` + `web/index.html` the reviewer.
- Everything except the review layer is computed. The demo runs offline from the JSON.

## Build steps

1. Review layer for 2283 by hand + owners. ✔
2. Builder: units, lines and callers match a manual read of the diff. ✔
3. First UI in BUI (Blender-style desktop widgets). Built, then dropped: too dense. ✔
4. Second UI: a node map with a side panel. Built, then dropped: boxes, not a tool. ✔
5. Third UI: a three-pane editor for functions (mentions, diff, calls; tests on the right). ✔
6. Docs: README, CONCEPT, DECISIONS, LESSONS, DEMO. ✔

## Risks and cuts

- No API key: review layer hand-written and labelled; LLM path written but untested.
- No dotnet: tests "not run"; the executed gate holds shipped-code units. Shown honestly.
- Unit detection is indentation-based for C# (not a parser); fine for this sample, stated as a limit.
- Cut first: callees, second branch, decision export beyond the JSON file.
