"""The review layer: what the reviewer model says about the change.

One Claude call per change (the logged-in `claude` CLI), cached to review.llm.json so the demo never calls it. Without a
cached response the hand-written review.handwritten.json is used, and the dossier says so. Either way
the model only proposes: requirements, unit mapping, findings, refusals and the checks that would
back them. The builder executes every check, so a hallucinated claim shows up as 'does not hold'.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MODEL = "opus"

PROMPT = """You review an agent-written pull request for a human who will not read the diff.
Return one JSON object only, no prose, with these keys:
- requirements: [{id: "REQ-<issue>-N", kind: functional|non-functional, text, source}], derived from the issue.
- units: {<unit id>: {reqs: [REQ ids], summary, covered_by: [new test method names that exercise it]}} for every unit id listed.
- checks: [{id: "C1"..., claim, paths: [repo paths or "@issue"], pattern: Python regex matched per line, expect: present|absent|==N|>=N, units: [unit ids it backs]}].
  Every factual claim you make must be backed by a check. Checks are executed; wrong ones are shown as failing.
- findings: [{id: "F1"..., unit, severity: info|low|medium|high, title, text, checks: [ids], model_confidence: high|medium|low}].
- proposed_tests: [{id: "P1"..., for: finding id, text}].
- refusals: [{id: "R1"..., category: one of %s, units, question, why, agent_choice, options: [3 short options], evidence: [check/finding ids]}].
  Refuse to decide anything that changes policy, a public contract, security, or rests on an ambiguous requirement.

Issue:
%s

Units (id, tier, changed lines):
%s

Diff:
%s
"""


def load(case_dir):
    for name in ("review.llm.json", "review.handwritten.json"):
        path = Path(case_dir) / name
        if path.exists():
            return normalise(json.loads(path.read_text()))
    raise FileNotFoundError(f"no review in {case_dir}")


def normalise(review):
    """A refusal without `units` belongs to the units of the findings it cites as evidence."""
    for r in review["refusals"]:
        r.setdefault("units", sorted({f["unit"] for f in review["findings"] if f["id"] in r.get("evidence", [])}))
    return review


def generate(case_dir, issue, units, diff_text, categories):
    """Ask Claude for the review once, through the logged-in `claude` CLI, and cache it."""
    listing = "\n".join(f"{u['id']} [{u['tier']}] +{u['added']} -{u['removed']}" for u in units)
    prompt = PROMPT % (", ".join(categories), issue, listing, diff_text)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    out = subprocess.run(["claude", "-p", "--model", MODEL, "--output-format", "json", "--allowedTools", ""],
                         input=prompt, capture_output=True, text=True, env=env, check=True)
    reply = json.loads(out.stdout)
    text = reply["result"]
    review = json.loads(text[text.index("{"): text.rindex("}") + 1])
    review |= {"source": "llm", "source_note": f"claude CLI ({MODEL}), {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, "
               f"${reply.get('total_cost_usd', 0):.2f}, cached in review.llm.json"}
    (Path(case_dir) / "review.llm.json").write_text(json.dumps(review, indent=2))
    return normalise(review)


def available():
    return shutil.which("claude") is not None
