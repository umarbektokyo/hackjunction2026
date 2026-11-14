# Live walkthrough (10 minutes)

**Where does the trust come from?** From evidence a named person can open in seconds, not from a
model's opinion. We show it on two of Tieto's agent-written branches.

## 0. The claim (1 min)

Reviewing agent code line by line does not scale and no longer works as a signal: agents produce
clean diffs, confident commit messages and plenty of tests even when the change is wrong. We review
**claims**, attach **evidence** or **refuse**, and a **named human signs the bundle**. Concept card:
[CONCEPT.md](CONCEPT.md).

## 1. Branch `ju26-issue-2234` — "fixed" an already-fixed bug (4 min)

Open [reports/REQ-2234/report.md](reports/REQ-2234/report.md).

1. **Recommendation** at the top: REJECT. Two reasons, each naming claim IDs.
2. **Requirement coverage**: N1 "tests prove the analyzer runs on suppressed types" is
   *contradicted*; F1 is *partial*.
3. **Claim C8** (behaviour, major): "the diff changes the path that skips suppressed types" →
   contradicted. Evidence: the analyzer entry (`MsgPack00xMessagePackAnalyzer.cs:426-432`) is
   identical on base and head; the only suppression gate (`TypeCollector.cs:1383-1387`) sits *after*
   the diagnostics on both. The diff only guards duplicate-key dictionary adds.
4. **Claim C7** (tests, major): the headline tests (MsgPack004, MsgPack015) exercise unchanged code,
   so they pass on base. The verifier **refused to assert** the base result without running and
   wrote the exact check for the human.
5. **Claim C1**: the README section is accurate, but the word "now" is not: the base already did it.
6. What the agent did: a plausible crash fix wearing the issue's name. What a line-by-line reviewer
   would have seen: a tidy diff, six passing tests, updated docs.

## 2. Branch `ju26-issue-2283` — a one-line fix with a global side effect (3 min)

Open [reports/REQ-2283/report.md](reports/REQ-2283/report.md).

1. The requested fix is there: `DeclaringSyntaxReferences[0]` → `FirstOrDefault` (C1, C2, supported,
   high, with line pointers).
2. **C5** (scope): the change also wraps every analyzer diagnostic in a filter that silently drops
   anything not located in the current compilation. Nobody asked. **C4**: the filter is bypassed by
   one call site, so it is inconsistent as well as broad.
3. **C9**: the issue's trigger matrix has controls (non-generic struct, generic class). Not tested.
4. **C12**: the doc sentence is more absolute than the code.
5. Recommendation: NEEDS A HUMAN, with four questions. None of them is "read the diff".

If time allows, [REQ-2297](reports/REQ-2297/report.md): 237 files, of which 222 are regenerated
snapshots. The model never reads them; the facts step counts them and raises the risk tier. The real
finding is in F1/F2: the attribute is wrapped in `#if !NETSTANDARD2_0 && !NETFRAMEWORK` because the
agent believed it does not exist there. It does. The guard removes the feature where it was asked for.

## 3. The human step (1 min)

```sh
node dist/cli.js decide --report reports/REQ-2234 --by "Ada Example" reject \
  --note "C7/C8: tests pass on base; the regression is not addressed"
node dist/cli.js decide --report reports/REQ-2283 --by "Ada Example" accept \
  --answer C10="ran GenericsFormatterTests on base: 3 fail with AD0001; on head: pass" \
  --answer C12="wording accepted for now; issue filed" --answer C4="filter bypass accepted, tracked" --answer C9="controls to be added before merge"
node dist/cli.js log
```

`accept` refuses to run while a routed question is unanswered, and refuses to accept a "reject"
without `--override`. The log line carries the name, the report hash and the answers.

## 4. How we would know it works (1 min)

Reverts and incidents of accepted changes must not rise while review time falls; the share routed
to humans should fall as execution evidence grows; every override of a "reject" is reviewed.
Metrics table in [CONCEPT.md](CONCEPT.md#how-trust-is-measured). Failure modes and decisions in
[LESSONS.md](LESSONS.md), including the one where the human reviewer (us) read the wrong base and the
tool did not.
