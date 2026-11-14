"""The review layer: what the reviewer model says about the change.

One Claude call per change, cached to review.llm.json so the demo never calls the API. Without a
cached response the hand-written review.handwritten.json is used, and the dossier says so. Either way
the model only proposes: requirements, unit mapping, findings, refusals and the checks that would
back them. The builder executes every check, so a hallucinated claim shows up as 'does not hold'.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MODEL = "claude-opus-5-5"

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
            return json.loads(path.read_text())
    raise FileNotFoundError(f"no review in {case_dir}")


def generate(case_dir, issue, units, diff_text, categories):
    """Ask Claude for the review once and cache it. Needs ANTHROPIC_API_KEY (or an `ant` profile)."""
    import anthropic  # only needed for this step, never for the demo

    listing = "\n".join(f"{u['id']} [{u['tier']}] +{u['added']} -{u['removed']}" for u in units)
    prompt = PROMPT % (", ".join(categories), issue, listing, diff_text)
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL, max_tokens=64000,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason != "end_turn":
        raise RuntimeError(f"review not usable: stop_reason={message.stop_reason}")
    text = "".join(b.text for b in message.content if b.type == "text")
    review = json.loads(text[text.index("{"): text.rindex("}") + 1])
    review |= {"source": "llm", "source_note": f"{message.model}, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, "
               f"{message.usage.input_tokens} in / {message.usage.output_tokens} out tokens, cached"}
    (Path(case_dir) / "review.llm.json").write_text(json.dumps(review, indent=2))
    return review


def key_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
