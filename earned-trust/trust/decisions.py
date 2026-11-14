"""Sign-off records: who decided what, when, on which evidence, against which dossier.

Stored as decisions/<issue>.json, append-only: a later record for the same item supersedes an
earlier one, and both stay in the file.
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(issue):
    return ROOT / "decisions" / f"{issue}.json"


def load(issue):
    p = _path(issue)
    return json.loads(p.read_text()) if p.exists() else []


def record(issue, dossier_id, item, decision, by, evidence, note=""):
    records = load(issue)
    records.append({"item": item, "decision": decision, "by": by, "evidence": evidence, "note": note,
                    "dossier": dossier_id, "at": datetime.now().isoformat(timespec="seconds")})
    _path(issue).parent.mkdir(exist_ok=True)
    _path(issue).write_text(json.dumps(records, indent=1))
    return records


def latest(records):
    """The standing decision per item. A later 'reopen' withdraws it; both stay in the file."""
    last = {r["item"]: r for r in records}
    return {k: r for k, r in last.items() if r["decision"] != "reopen"}


def merge_blockers(d, records):
    """Why the approver may not merge yet. Empty list = mergeable."""
    done = latest(records)
    reasons = [f"{r['id']} undecided: {r['owner']['name']}" for r in d["refusals"] if r["id"] not in done]
    reasons += [f"{r['id']} rejected by {done[r['id']]['by']['name']}" for r in d["refusals"]
                if r["id"] in done and done[r["id"]]["decision"] == r["options"][-1]]
    held = [u["name"] for u in d["units"] if u["status"] == "held"]
    if held:
        reasons.append(f"{len(held)} held unit(s) lack executed evidence: {', '.join(held)}")
    return reasons


def measured(d, records):
    """(label, value, meaning) measured on this change. Every value is counted, none estimated."""
    s, done = d["summary"], latest(records)
    decided = [r for r in d["refusals"] if r["id"] in done]
    changed = [r for r in decided if done[r["id"]]["decision"] != r["options"][0]]
    judged = [f for f in d["findings"] if f["id"] in done]
    real = [f for f in judged if done[f["id"]]["decision"] == "real"]
    return [
        ("units cleared", f"{s['cleared']}/{s['units']}", "passed every gate their risk tier requires; no human read"),
        ("lines to read", f"{s['lines_to_read']}/{s['lines_changed']}", "changed lines in routed and held units"),
        ("checks hold", f"{s['checks_hold']}/{s['checks']}", "claims executed against the head commit"),
        ("tests run", f"{s['tests_run']}/{s['tests']}", "not run is not a pass: the executed gate stays open"),
        ("findings confirmed", f"{len(real)}/{len(judged)}", "finding acceptance: judged real by the approver"),
        ("refusals changed", f"{len(changed)}/{len(decided)}", "refusal precision: 0 means routing is too wide"),
    ]
