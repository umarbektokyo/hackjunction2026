# Lessons log

Failure modes we saw, and what we took from them.

## The agent's own mistakes on issue 2283

- **A global fix for a local bug.** The crash was in two diagnostic sites. The agent also changed
  the constructor so that every analyzer diagnostic of TypeCollector (27 call sites) goes through a
  new filter. The filter drops anything without a source location in this compilation, including
  in-source diagnostics created with a null location. One line, wide blast radius. (F2, routed as R1.)
- **A new helper that disagrees with its neighbour.** `GetPropertyIdentifierLocation` ignores
  `ParameterSyntax`, while the MemberNeedsKey path nearby handles it. A positional record property
  gets a null location, and the filter then drops its diagnostic silently. (F3.)
- **Tests that reach neither changed line.** The line-1077 change is in the loop over fields. The
  new tests declare only properties. No test has a null key, which line 985 needs. The tests show
  the scenario works. They don't cover the change, and nothing shows they fail without it: the
  sample repo is 3.0-rc.1 while the issue was filed on 3.1.8. (F5, proposed test P0.)
- **A test that passes for the wrong reason.** Before the change, the unkeyed-member path already
  reported MsgPack004 (an Error) instead of crashing. The new unkeyed test passes because the
  filter silences that error, not because of the crash fix. (R1.)
- **Docs that promise a policy the issue never asked for.** The README and the MsgPack004 docs now
  say that problems in a referenced type are reported only by its defining project, and a test
  locks that in. The issue asked for no crash and a generated resolver. (R2.)
- **What it got right.** The record-struct test is the issue's repro verbatim, across a real
  metadata boundary, and it asserts that the resolver is generated, not only that nothing crashed.

## Failure modes of AI review itself

- **Claims without checks.** A reviewer model states facts about code fluently and some are wrong.
  Every factual claim must name a check the builder executes. A failing check shows as
  "does not hold" instead of being believed.
- **Tests reported as passing when they never ran.** The easiest lie to tell. "Not run" is its own
  state, and the executed gate stays open until a real run is recorded.
- **Confidence numbers with no source.** "92% confident" means nothing. We show where confidence
  comes from: the checks behind a finding, or "model only" with the model's self-report.
- **Refusing too much.** If everything is routed, routing is noise and humans stop reading.
  Refusals must be few, categorical and specific. Refusal precision (routed items a human changed)
  tells you if they are.
- **Root cause stated as fact.** Neither the issue author nor the agent showed which site crashed.
  The dossier says the cause is inferred (F4) instead of picking one.

## Build lessons

- **Our own checks caught our own wrong claim.** The hand-written review first claimed "every key
  in the new tests is Key(0)". The check failed on `Key(1)` and the finding showed "contradicted by
  C23" in the UI. The claim we meant was "no key is null", and the check now says that. This is the
  hallucination guard working on a human author too.
- **An independent audit pays off.** A second pass, run as a separate agent with no edit rights,
  confirmed every finding, then found the two strongest points above (the wrong-reason test and the
  missing red/green evidence) and the untouched analyzer release notes (F8).
- **A working spike is not a design decision.** BUI (Blender's widgets) rendered fine in a
  20-minute spike, so we built the whole UI in it. It came out dense and tool-like: four tabs,
  every fact on screen. The team's idea was the opposite: the change as a map of nodes, minimal.
  We rewrote it as one page. Lesson: show a screenshot to the team before building the rest.
- **We missed the team's idea twice before asking what it looked like.** The node map was still
  our reading of "nodes". The idea was simpler: a Git client where the unit is a function, with
  its mentions above the diff and its calls below. One sentence from the team ("think of it as
  GitHub Desktop") did more than two rebuilds. Lesson: ask for a reference product first.
- **Less on screen made the concept clearer.** Cutting principles, metric tables and policy
  tables from the UI left three things: what needs a human, why, and who. Those are the product.
- **`git grep -E` has no `\b`.** The word-boundary pattern silently matched nothing. We filter
  boundaries in Python after the grep instead.
- **Name-based caller search was fooled by a local function.** The generator declares a local
  function named `Collect`, which looked like a caller of `TypeCollector.Collect`. Fix: an
  unqualified call counts only in the declaring file. Elsewhere only `ClassName.Member(` counts.
- **Blank lines between members belonged to no unit.** The unit totals didn't add up to the diff.
  Blank-only changes are now excluded, and the builder asserts that every non-blank changed line
  lands in exactly one unit.
- **Evidence first, UI second.** Writing the checks before the screens surfaced F5 (tests don't
  reach the changed lines), which no diff read had shown us.
