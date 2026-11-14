# Lessons log

Short entries, newest last. Each is a decision we took or a failure mode we saw, with what we did about it.

## Decisions

- **D1 — Review against the real base.** The sample branches were cut from the repository's default
  branch (`dependabot/nuget/develop/PolySharp-1.15.0`), not `master`. Diffing against `master`
  attributes a PolySharp bump to the agent. We review against `origin/HEAD` and keep "unrequested
  build change" as a deterministic finding for when it really is in the PR.
- **D2 — The PR's own text is a claim.** Commit message, README additions and test names go into the
  claims step as *things to check*, never into the verify step as evidence.
- **D3 — "Supported" needs a pointer, by code not by prompt.** The verifier is told this, and
  `review.ts` demotes any supported verdict without a code/test/execution pointer anyway.
- **D4 — Unverifiable is a result, not an error.** Each one carries the concrete check for the
  human, and the human must answer it (`--answer`) before `cev decide accept` will record acceptance.
- **D5 — Execution evidence is optional and visible.** Where we cannot build, the report says so
  and test claims stay unverifiable. We do not fake confidence.
- **D6 — Hide generated churn from the model, not from the facts.** 237 regenerated `.g.cs` files
  are counted and raise the risk tier, but the model reads only source, templates, tests and docs.

- **D7 — Self-refuting claims are a claims-step bug, not a finding.** The first runs produced claims
  like "the tests cover the controls; they cover only generic structs", which the verifier then
  marked contradicted and the rule turned into a reject. We tightened the claims prompt (one atomic
  statement, no "and"/"including", "every"/"only" only when the change asserts it) and changed the
  rule: only a blocker/major contradiction rejects; a minor one routes to the human.
- **D8 — The reviewer reviewed the wrong base too.** Before the tool ran, we read branch 2234 by hand
  against `master` and concluded the fix never touched the early `return null` that skips suppressed
  types. On the branch's real base that gate already sits after the diagnostics (upstream had fixed
  the regression). The tool, diffing against `origin/HEAD`, got it right; the human did not. Kept
  here because it is the whole point: evidence beats reading.

## Failure modes seen in the agent-written branches

| # | Branch | Failure mode | What the evidence showed | Where it is in the report |
|---|---|---|---|---|
| FM1 | 2234 | **Fixing an already-fixed bug, and saying so.** Commit says "Implementation for #2234"; README gains a section on analyzer behaviour for suppressed types. | The analyzer entry and the MsgPack004/015 paths are identical on base and head; the only code change guards duplicate-key dictionary adds. The headline tests pass on base. | REQ-2234 C1, C7, C8 (contradicted), N1 contradicted |
| FM2 | 2234 | **Tests that do not test the change.** New tests named after the issue exercise unchanged code. | Verifier traced each test to the path it exercises; two of six hit changed lines. | REQ-2234 C7; execution check (`--exec`) would show them passing with the fix reverted |
| FM3 | 2283 | **Silent blast-radius growth.** A one-line crash fix (`[0]` → `FirstOrDefault`) comes with a new global filter that drops every diagnostic whose location is not in the compilation. | The filter wraps the callback in the constructor (`TypeCollector.cs:239`) and is bypassed by one call site (`:248`), so it is both broader than asked and inconsistent. | REQ-2283 C4, C5; F4/N1 partial |
| FM4 | 2283 | **Documentation more absolute than the code.** Docs say MsgPack004 is "only" reported for members declared in the compiled project. | Inherited unattributed members from a referenced base type are still reported in the consumer (`TypeCollector.cs:940-953`). | REQ-2283 C12 |
| FM5 | 2283 | **Partial coverage presented as coverage.** The issue's trigger matrix has crashing cases and non-crashing controls; only the crashing cases got tests. | Grep for callers of the new test helper: three tests, all generic structs. | REQ-2283 C9; F3 partial |
| FM7 | 2297 | **Confident wrong fact becomes a design decision.** README says `[ExcludeFromCodeCoverage]` is "only emitted for targets where it is available (not netstandard2.0 or .NET Framework)" and every emission is wrapped in `#if !NETSTANDARD2_0 && !NETFRAMEWORK`. | The attribute exists on .NET Framework 4.0+ and netstandard2.0; the guard removes the feature exactly where many consumers run it. The requirement said "every type". | REQ-2297 F1/F2 partial, C5, C8 |
| FM6 | all | **Scope creep hidden in volume.** 2297 regenerates 222 `.g.cs` files for a 20-line template change; 2129 adds public API and four analyzer IDs. | Deterministic file classification raises the risk tier and excludes the churn from what the model reads. | REQ-2297 / REQ-2129 risk tier and scope claims |

## What the verifier refused to decide, and why

- Whether a new test fails on the base branch without running it (2283 C10, 2234 C7). It asked the
  human to run the class against base. That is what `--exec` automates where a build is available.
- Whether a Roslyn behaviour it recalled (PE-loaded backing fields and `IsImplicitlyDeclared`) holds
  (2283 C10). It said so and lowered confidence instead of asserting.
- Whether an absolute wording in docs is intended (2283 C12). A product decision, not a code fact.
