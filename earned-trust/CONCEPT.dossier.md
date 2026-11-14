# Concept card: Earned Trust in AI Code

## Recommendation

Line-by-line review is no longer the right default. The diff of an agent-written change is not the
thing a human should read. The PR should arrive as an **evidence dossier**: the change split into
units (changed methods, test helpers, doc sections), each tied to a requirement ID and put through
four gates: **traced** (it serves a requirement), **checked** (deterministic checks back every
claim the reviewer AI makes), **executed** (the tests that cover it actually ran and passed) and
**uncontested** (the AI has not refused to decide something about it). Units that pass every gate
their risk tier needs are cleared without a human read. A human reads only what is **held** (the
missing evidence is named) or **routed** (the AI refused to decide, with the question, the reason
and a named owner). The human checks a story and answers specific questions. They do not hunt for
bugs in a diff.

## Principles

| # | Principle | Balances |
|---|-----------|----------|
| 1 | **Evidence scales with risk.** Shipped code needs executed evidence. Test and doc code need checked evidence. The tier comes from the path, not from the model's opinion. | risk |
| 2 | **No claim without a check.** A model claim is labelled *model only* unless a deterministic check (pattern match, call-site search, test run) backs it. Confidence states where it comes from. | hallucination, confidence |
| 3 | **Refusal is a feature.** Policy changes, public contracts, security and ambiguous requirements are not the AI's to decide. It says what it won't decide, why, and who owns it. | transparency |
| 4 | **A named human owns every decision.** Each routed item has one owner from a routing table, and each decision is recorded with the evidence IDs it rested on. | accountability, quality |
| 5 | **Missing evidence is shown, never filled in.** "Not run" is a state, not a pass. | quality, confidence |
| 6 | **Trust is earned per category and measured.** Auto-clear widens only while reverts and incidents stay flat as review time falls, and it narrows on the first revert. | risk, quality |

## In a real pull-request flow

1. The agent opens a PR. A review bot builds the dossier: diff → units → callers → checks → gates.
   One model call writes the review layer (requirements, findings, refusals and the checks that
   back them). Everything else is computed.
2. CI runs the tests and fills the **executed** gate. Held shipped units clear once their covering
   tests pass. No human is needed for that.
3. The bot posts the dossier on the PR. Each refusal goes to the owner its category maps to in the
   routing table (e.g. diagnostic policy → analyzer maintainer, public contract → docs/API owner,
   security → security champion, ambiguous requirement → product owner).
4. Owners accept, reject or ask for a change on their item. Each decision is stored with the
   dossier ID (a hash of the exact evidence shown) and the evidence IDs it rested on.
5. The change approver merges only when every routed item is decided and nothing is held. The
   approver stays accountable for the merge, and the record shows what they relied on.

This scales because human attention grows with the number of refusals and evidence gaps, not with
the number of changed lines.

## Measurement

What we would measure in production, per category (tier × change kind):

| Metric | Formula | Healthy when |
|--------|---------|--------------|
| Revert rate, auto-cleared | units reverted within 30 days ÷ units auto-cleared | ≤ revert rate of human-reviewed units |
| Incidents linked | incidents whose fix touches a cleared unit ÷ cleared units | flat as review time falls |
| Finding acceptance | findings a human confirmed ÷ findings shown | ≥ 0.8 (findings are real) |
| Refusal precision | routed items a human changed or rejected ÷ routed items | not near 0 (else routing is noise) |
| Time to merge | PR opened → merged | falls |
| Reviewer minutes | human time per PR (from decision timestamps) | falls |
| Share routed | lines routed ÷ lines changed | falls slowly as trust is earned |

**Earn/lose rule.** Widen auto-clear for a category after N = 50 changes in it with a revert rate
at or below the human-reviewed baseline and finding acceptance ≥ 0.8. One revert of an auto-cleared
unit returns that category to routed until it earns trust again.

## Trade-offs

- **Computed evidence over model judgement.** We trust a regex check over a model sentence. We
  give up nuance: some true and important claims can't be expressed as a check, so they stay
  labelled *model only*.
- **Path-based risk tiers.** Simple and predictable. We give up precision: a risky line in a test
  helper is treated as low risk.
- **Refusing by category.** A narrow, explainable set of refusal categories. We give up coverage:
  a risk outside the categories is not routed unless a finding flags it.
- **Holding shipped code without executed tests.** Safe by default. We give up speed when CI is
  slow or a test runner is missing.
- **One model call, cached.** Deterministic, cheap, auditable. We give up an interactive
  back-and-forth with the reviewer model.

## Limits of this reference implementation

- Units are split by indentation (class members at four spaces), not by a C# parser.
- Callers are found by name with a qualification rule. Calls through other receivers are missed.
- Checks are regex claims. A badly written check can be trivially true. Checks need review too.
- The review layer in this build is hand-written in the model's output shape (no API key at the
  hackathon). It is labelled in the UI. The LLM path exists but is untested.
- No tests were run: the .NET SDK is not installed on the review machine. All three show "not run".
- One change sampled (issue 2283, 4 files). Owners are synthetic people.
- The model can fail to refuse. Recommended addition, **not implemented**: enforce refusal
  categories with path and pattern rules (e.g. any change to diagnostic plumbing, public docs or
  security config is routed whatever the model says).

## What the sample showed (issue 2283)

- 13 units: 6 cleared, 2 held, 5 routed.
- A human reads 72 of 194 changed lines (62 of them routed). The rest is cleared by evidence.
- 24 checks, 24 hold. 3 new tests, 0 run.
- 8 findings (3 medium, 3 low, 2 info); 7 are backed by checks and 1 is labelled model only.
  2 refusals: R1 diagnostic policy → Aino Virtanen, analyzer maintainer; R2 public contract →
  Mikko Laine, docs and public API owner.
- The headline: a one-line constructor change routes 27 diagnostic call sites through a new
  filter. MsgPack004 is an Error, so the filter can silence errors. The unkeyed-member test passes
  because of that filter, not because of the crash fix. The fix for a local crash is a global
  policy change, and that is what the dossier sends to a human. The test helpers, most of the line
  count, are cleared.
- The tests do not reach either changed crash site, and nothing shows they fail without the fix
  (proposed P0: run them red on the base commit). So even with .NET installed, a green run would
  not be enough evidence for the two held units on its own.
