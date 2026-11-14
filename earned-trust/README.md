# Earned Trust in AI Code — CEV reference implementation

**Challenge:** Tieto, Junction 2026. *How can AI review code made by AI so that humans can trust it?*

**Answer:** review **claims, not lines**. The change is decomposed into falsifiable claims tied to a
requirement; an AI verifier attaches evidence (file:line, test, execution result) to each claim or
**refuses to decide**; a named human signs the evidence bundle. See [CONCEPT.md](CONCEPT.md) for the
concept card and [LESSONS.md](LESSONS.md) for the lessons log and failure modes.

Reports for Tieto's four agent-written branches are in [`reports/`](reports/), one folder per
requirement ID. Start with [REQ-2234](reports/REQ-2234/report.md); the demo script is [WALKTHROUGH.md](WALKTHROUGH.md).

| Branch | Risk | Claims (supported / contradicted / unverifiable) | Recommendation | Headline finding |
|---|---|---|---|---|
| [REQ-2234](reports/REQ-2234/report.md) | low | 14 (11 / 3 / 0) | **reject** | The regression it claims to fix is already fixed on the base; the headline tests pass without the change. Only code change: duplicate-key crash guards. |
| [REQ-2283](reports/REQ-2283/report.md) | low | 13 (9 / 3 / 1) | **needs human** | The one-line crash fix is right; it comes with an unrequested global filter that drops diagnostics, inconsistently applied. Controls from the issue's trigger matrix untested. |
| [REQ-2297](reports/REQ-2297/report.md) | medium | 13 (12 / 0 / 1) | **needs human** | `[ExcludeFromCodeCoverage]` is wrapped in `#if !NETSTANDARD2_0 && !NETFRAMEWORK` on a wrong belief that it does not exist there; 222 regenerated files hide a 20-line change. |
| [REQ-2129](reports/REQ-2129/report.md) | high | 14 (14 / 0 / 0) | **needs human** | The largest change is the cleanest: every claim supported with pointers. High tier + no execution evidence keeps a human in the loop; attribute shape differs from the issue's example. |

Model cost for the four reports: about $6.50 with `sonnet`, 6-12 minutes each at concurrency 4.

## Layout

```
requirements/REQ-*.md   requirement cards (intent, F*, N* items) written from the GitHub issues
reports/REQ-*/          report.md (for the human) + report.json (for machines) per branch
decisions/log.jsonl     who accepted what, with the report hash and their answers
src/                    the tool: facts → claims → verify → coverage → report → decide
```

Pipeline, per change (`src/review.ts`):

1. **facts** (`facts.ts`, deterministic): classify files (source / template / test / docs / build /
   generated / snapshot), size, public-API touch, risk tier, unrequested build changes.
2. **claims** (one model call): 6-14 falsifiable claims from requirement + commit message + diff.
   Docs promises, test promises and out-of-scope changes become claims of their own.
3. **verify** (one model call per claim, read-only tools on HEAD and BASE checkouts): verdict
   `supported | contradicted | unverifiable`, confidence with its basis, evidence pointers, the
   question for the human. Policy rule: "supported" without a code/test pointer is demoted.
4. **execution** (`--exec`, optional): run the tests the change added on HEAD, then again with the
   non-test source reverted. Tests that pass both times do not test the change.
5. **coverage** (one model call): every requirement item → addressed / partial / missing / contradicted.
6. **report** + **recommendation**: accept-on-evidence / needs-human / reject, with reasons.
7. **decide** (`cev decide`): a named human accepts or rejects; acceptance requires an answer to every
   routed question and an explicit `--override` to accept a "reject".

## Run it

Needs the `claude` CLI logged in (it is the model backend; set `CEV_MODEL=opus` for a stronger
model) and Node 22. With Nix: `nix develop` gives node, pnpm, git and the .NET 8 SDK for `--exec`.

```sh
pnpm install && pnpm build
git clone https://github.com/te-industry-tech-office/junction26-messagepack-csharp ../sample-repo
./review-all.sh ../sample-repo            # all four branches → reports/REQ-*/
```

One branch, with execution evidence (builds the .NET test project, slow the first time):

```sh
node dist/cli.js review --repo ../sample-repo --base origin/HEAD --head origin/ju26-issue-2234 \
  --requirement requirements/REQ-2234.md --out reports/REQ-2234 --exec
```

Sign off as the accountable human:

```sh
node dist/cli.js decide --report reports/REQ-2234 --by "Ada Example" reject --note "C7/C8 contradicted: tests pass on base, regression not addressed"
node dist/cli.js decide --report reports/REQ-2297 --by "Ada Example" accept --answer C5="ran snapshot tests locally"
node dist/cli.js log
```

Notes: the sample branches were cut from the repository's default branch (a dependabot branch), so
review them against `origin/HEAD`; against `origin/master` the diff also contains someone else's
PolySharp bump. Model calls are cached under `.work/` so a re-run is free and reproducible.

## Status and hand-over (14 Nov, judging 15 Nov)

- Measurement: `node dist/cli.js metrics` writes [`reports/METRICS.md`](reports/METRICS.md) from the
  reports and `decisions/log.jsonl`.
- Decisions: `decisions/sign.sh "Name"` holds three proposed rejects (2234, 2297, 2283); it must be
  run by the accountable human, not by a model. 2129 waits for an `--exec` run.
- The visual half of this entry (a function-level reviewer UI, Python) is on branch
  `earned-trust`. Its `earned-trust/HANDOFF.md` is the hand-over for both halves and lists the next
  tasks: feed these reports into that UI, then merge the two (both use `earned-trust/`, so agree a
  layout first).
