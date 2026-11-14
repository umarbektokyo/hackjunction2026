# Earned Trust in AI Code: evidence dossier

Tieto's challenge, Junction 2026. An agent-written pull request arrives as an **evidence dossier**,
not a diff. The reviewer reads only what the AI refused to decide or could not prove. Concept card:
[CONCEPT.md](CONCEPT.md). Demo script: [DEMO.md](DEMO.md).

## Run

```sh
./run.sh
```

Fetches the sample repo if missing, rebuilds the dossier and opens the reviewer at
http://localhost:8283. Needs Python 3.11+ and git, nothing else. For a projector, zoom the browser.

Pieces, if you want them separately:

```sh
python3 -m trust.build 2283          # dossier/2283.json from the branch + review layer
python3 -m trust.build 2283 --llm    # review layer from one Claude call (pip install anthropic, ANTHROPIC_API_KEY), cached
python3 -m trust.serve 2283          # the page only
```

## Layout

| Path | What |
|------|------|
| `trust/gitdiff.py` | git diff → hunks with real line numbers |
| `trust/units.py` | hunks → units (changed C# members, Markdown sections, file headers) |
| `trust/evidence.py` | callers (two levels), checks, test runs, the four gates |
| `trust/review.py` | the review layer: cached Claude call or the hand-written file |
| `trust/build.py` | assembles `dossier/<issue>.json` |
| `trust/decisions.py` | sign-off records, merge blockers, measured values |
| `trust/serve.py` | standard-library server: the page, `/api/state`, `/api/decide` |
| `web/index.html` | the reviewer: one page, no build step, no dependencies |
| `input/<issue>/` | issue text, case config, review layer |
| `input/owners.json` | routing table: category → named owner (synthetic) |

## Honesty notes

- The review layer is hand-written (no API key at the hackathon) and labelled so on the page. Its
  claims are still executed as checks against the code; a wrong claim shows as failing.
- Tests show *not run*: the .NET SDK is not installed. Nothing is shown as passing that did not run.
- Owners are synthetic people. Sample code is public (MessagePack-CSharp fork by Tieto).

Notes for the team: [PLAN.md](PLAN.md), [DECISIONS.md](DECISIONS.md), [LESSONS.md](LESSONS.md).
