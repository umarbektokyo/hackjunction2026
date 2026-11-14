# Concept card — Claims → Evidence → Verdict (CEV) review

*Tieto challenge "Earned Trust in AI Code", Junction 2026. Team Evil Club.*

## Recommendation in one sentence

Stop reviewing agent-written code line by line. Make the change **state its claims**, make an AI
verifier **attach evidence to every claim or refuse**, and let a **named human sign the evidence
bundle**, not the diff.

## The problem with line-by-line review of agent code

- Volume: an agent produces 200-line and 2,000-line changes faster than a human can read them.
- The old signal is gone: a tidy diff, a clear commit message and plenty of tests used to mean a
  careful author. Agents produce all three by default, including when the change is wrong.
- The failure mode is different: agents rarely make typos; they **over-promise**. Docs and tests
  describe behaviour the code does not have, fixes land next to the bug instead of on it, and
  scope quietly grows (dependency bumps, template edits, 200 regenerated files).
- Accountability has to stay with a person. "The AI approved it" is not an answer in an incident
  review.

## The concept: review claims, not lines

Every change is decomposed into **claims**: falsifiable sentences about what it does, what it
documents, what its tests prove, what it changes that nobody asked for, and what it must not have
changed. Each claim is tied to an item of the **requirement** (REQ-2234 F1, N2, ...).

A verifier then works claim by claim and returns exactly one of three verdicts:

| Verdict | Meaning | Needs |
|---|---|---|
| **supported** | evidence shows the claim holds | at least one code/test/execution pointer (file:line) — enforced by policy, not by prompt |
| **contradicted** | evidence shows the opposite | the pointer that shows it, and the question for the human |
| **unverifiable** | the verifier **refuses to decide** | why it could not, and the exact check the human must do |

The human never reads "looks good to me". They read: *claim C3 "the analyzer still validates
suppressed types" is contradicted: `TypeCollector.cs:723-727` returns before any validation and
the change does not touch it.* Then they decide, and their name goes on the record.

## Principles

1. **Evidence before opinion.** A verdict without a pointer a human can open in seconds is
   downgraded to "unverifiable" by a deterministic rule. The model cannot talk its way to "supported".
2. **The PR's own words are claims, never evidence.** Commit message, description, docs and test
   names are inputs to be checked. This is the single biggest defence against hallucinated fixes.
3. **Confidence comes from the evidence kind, not from the model's feeling.** Execution evidence
   (the new tests pass on HEAD and fail with the source change reverted) beats a test that reads
   right, which beats reading the whole code path, which beats reading a hunk.
4. **Refusing to decide is a first-class result.** Anything that needs a runtime, data or a
   judgement the requirement does not settle goes to a named human with a concrete question.
   The share of claims routed to humans is a metric we watch, not a failure.
5. **Risk sets the bar.** Deterministic facts (lines of source, public API, templates, missing
   tests, unrequested build changes, generated-file churn) put the change in a tier. A high tier
   needs execution evidence and a human on every unverifiable item; a low tier can be accepted
   on cited evidence alone.
6. **Scope is a claim too.** Every change not traceable to a requirement item becomes its own
   claim. The human decides whether it stays, but it can no longer hide.
7. **A named human signs the bundle.** Acceptance records who accepted, the hash of the exact
   report they saw, which routed questions they answered and how, and any override of a
   "reject". The decision log is the audit trail.
8. **Deterministic where possible, model where necessary.** File classification, risk tier,
   unrequested-change detection, the "supported needs a pointer" rule and the execution check are
   plain code. The model extracts claims, reads code and writes the chain of reasoning.

## How trust is measured

| Metric | Why | Direction |
|---|---|---|
| Revert and incident rate of CEV-accepted changes | the only ground truth for "we trusted correctly" | must not rise as review time falls |
| AI findings accepted by humans (true positives) vs dismissed | are "contradicted" verdicts real? | high and stable |
| Share of claims routed to humans | calibration: too low = overconfident, too high = useless | track per risk tier; expect it to fall as execution evidence improves |
| Time from PR open to decision, split by tier | the efficiency gain, by tier | falls for low tier first |
| Overrides of "reject" and their outcomes | where the humans and the verifier disagree | review every one |
| Mutation-check pass rate of agent-written tests | how often agents ship tests that test nothing | reported per agent/model |

## Trade-offs

- **Cost and latency.** One review is 10-20 model calls, several of them reading code with tools
  (≈ $1-3 and 5-10 minutes with a mid-size model). Cheaper than a senior engineer's hour, but not
  free; cache by claim and re-verify only changed claims on a new push.
- **The verifier can be wrong.** Hence the pointer rule, the deterministic demotion, execution
  evidence where possible and the human sign-off. We measure, we do not assume.
- **Requirement quality bounds review quality.** No requirement card → no coverage table. Writing
  the card is the one new input we ask for; it is also what an agent should get before it codes.
- **Execution evidence needs a build.** Where the pipeline cannot run tests, test claims remain
  unverifiable by design and the human runs them. That is honest, and it is visible in the report.

## Limits

- Not a product: a reference implementation with a CLI and Markdown/JSON reports, no CI
  integration, no UI.
- Verifies against a requirement card, not against the whole architecture or roadmap.
- Static evidence only unless `--exec` can build the repository.
- English-language C# and the Tieto sample repository are what we tested on.

## What the human does

1. Opens the report. Reads the recommendation and its reasons (ten seconds).
2. Opens each pointer under a contradicted or routed item (a minute each).
3. Answers each routed question with what they checked (`cev decide ... --answer C7="ran the
   analyzer tests locally, 5/5 pass"`), or rejects.
4. Their name, the report hash and their answers go to `decisions/log.jsonl`.

No full read. Full accountability.
