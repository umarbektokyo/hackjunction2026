# Earned Trust in AI Code: evidence dossier

> Saved from the `earned-trust` branch at merge time (it conflicted with main's README). This describes the Python evidence-dossier reviewer (`trust/`, `web/`); [README.md](README.md) describes the TypeScript `cev` tool.

Tieto's challenge, Junction 2026. An agent-written pull request arrives as an **evidence dossier**,
not a diff. The reviewer reads only what the AI refused to decide or could not prove. Concept card:
[CONCEPT.md](CONCEPT.dossier.md). Demo script: [DEMO.md](DEMO.md).

Two changes ship with it, switchable at the top left:

| Case | Code | Agent change | AI review |
|---|---|---|---|
| **REQ-W3** | Waddenislands (Java exam solution, human-written) | Option 3 in a thread, written by `claude -p` (`input/w3/agent.patch`) | Claude (`input/w3/review.llm.json`) |
| **#2283** | Tieto's MessagePack-CSharp fork | branch `ju26-issue-2283` from Tieto | hand-written stand-in |

## Run

```sh
./run.sh                 # build the sample repos, rebuild every dossier, open http://localhost:8283
./run.sh --reuse-tests   # same, without running the tests again
./test.sh                # every unit test (Python + JavaScript)
```

Needs Python 3.11+ and git. Tests of the change run when the toolchain exists: a JDK for REQ-W3,
the .NET 8 SDK for #2283 (`nix develop` on `main` provides it); otherwise they show *not run*.
Checkstyle on PATH adds coding-standard checks for Java. For a projector, zoom the browser.

```sh
python3 -m trust.build w3          # dossier/w3.json
python3 -m trust.build w3 --llm    # new review layer from one call to the logged-in `claude` CLI, cached
python3 -m trust.serve             # the page only
```

## Layout

| Path | What |
|------|------|
| `trust/gitdiff.py` | git diff → hunks with real line numbers |
| `trust/units.py` | hunks → units (changed C#/Java members, Markdown sections, imports) |
| `trust/evidence.py` | callers (two levels), calls, claim checks, the four gates |
| `trust/testrun.py` | runs the change's tests with and without the change (JUnit, dotnet) |
| `trust/style.py` | Checkstyle on the changed lines, as evidence |
| `trust/review.py` | the review layer: cached Claude call or the hand-written file |
| `trust/build.py` | assembles `dossier/<case>.json` |
| `trust/decisions.py` | append-only sign-off records, reopen, merge blockers |
| `trust/serve.py` | standard-library server: page, `/api/cases`, `/api/state`, `/api/decide` |
| `web/js/` | the page as ES modules: `model`, `diff`, `syntax` (pure logic), `view-*` (HTML), `app` (events) |
| `tests/`, `web/test/` | unit tests (`./test.sh`) |
| `input/<case>/` | case config, requirement text, review layer, owners |
| `samples.sh` | builds `sample-wadden/` (base + agent branch) and clones Tieto's repo |

## Honesty notes

- REQ-W3's review is a real Claude call, cached; #2283's is hand-written and labelled so on the page.
  Every claim either way is executed as a check against the code; a wrong claim shows as failing.
- A test counts for the change only if it passes with it and fails, or no longer compiles, without it.
  Nothing is shown as passing that did not run.
- Owners are synthetic people. The Waddenislands exam text is quoted as the requirement for REQ-W3.

Notes for the team: [HANDOFF.md](HANDOFF.md), [PLAN.md](PLAN.md), [DECISIONS.md](DECISIONS.md), [LESSONS.md](LESSONS.dossier.md).
