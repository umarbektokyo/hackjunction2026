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

## Failure modes seen

(filled in from the reports — see below)
