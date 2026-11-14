#!/bin/sh
# Sign the four reports as the accountable human, then recompute reports/METRICS.md.
# Usage: decisions/sign.sh "Your Name"   (run from earned-trust/, inside `nix develop`)
# Every answer below was checked by hand against the sample repo; see the note on each.
set -e
BY="${1:?usage: decisions/sign.sh \"Your Name\"}"
cev() { node dist/cli.js "$@"; }

# 2234: the regression is already fixed on the base; the headline tests do not test the change.
cev decide --report reports/REQ-2234 --by "$BY" reject \
  --note "C7/C8 contradicted: MsgPack004/015 paths identical on base and head; N1 not met. Only real change is the duplicate-key guard; resubmit it as that."

# 2297: C11 answered from git. Rejected on F1/F2: the #if guard drops the attribute where it exists.
cev decide --report reports/REQ-2297 --by "$BY" reject \
  --answer C11="git diff base..head -- tests/.../Resources: 1209 added lines = 402 #if + 402 #endif + 402 attribute + 3 brace-fix lines; 1 deletion (brace). Nothing else. The 3 unchanged files are in Resources/InterfaceUnion, which no test uses." \
  --note "ExcludeFromCodeCoverage exists on netstandard2.0 and .NET Framework 4.0+; the guard removes it exactly there, and the requirement says every type."

# 2283: the crash fix is right, but the global diagnostic filter is unrequested and bypassed at :248,
# and the trigger matrix controls are untested. Request changes rather than answer C4/C9/C10/C12.
cev decide --report reports/REQ-2283 --by "$BY" reject \
  --note "Keep the FirstOrDefault fix; drop or justify the global location filter (C4, bypassed at TypeCollector.cs:248); add the non-crashing controls from the issue (C9); fix the absolute doc wording (C12)."

# 2129: no routed questions, but high tier and no execution evidence. Not signed here:
# run `cev review ... --exec` first, then decide.

cev metrics >/dev/null && echo "decisions logged; reports/METRICS.md updated"
