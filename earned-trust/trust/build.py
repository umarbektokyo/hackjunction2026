"""Build the evidence dossier for one change: python -m trust.build 2283 [--llm]"""

import hashlib
import json
import sys
from pathlib import Path

from . import evidence, gitdiff, review, units as unitmod

ROOT = Path(__file__).resolve().parent.parent


def confidence(finding, checks):
    """Where a finding's confidence comes from: executed checks, or the model's own word."""
    cited = [checks[c] for c in finding["checks"] if c in checks]
    failing = [c["id"] for c in cited if not c["holds"]]
    if failing:
        basis = "contradicted by " + ", ".join(failing)
    elif cited:
        basis = "facts backed by " + ", ".join(c["id"] for c in cited)
    else:
        basis = "model only"
    return {"basis": basis, "model": finding.get("model_confidence", "unstated"), "backed": bool(cited) and not failing}


def build(issue, use_llm=False):
    case_dir = ROOT / "input" / str(issue)
    case = json.loads((case_dir / "case.json").read_text())
    owners = json.loads((ROOT / "input" / "owners.json").read_text())
    issue_text = (case_dir / "issue.md").read_text()
    repo, base, head = str(ROOT / case["repo"]), case["base"], case["head"]

    diff = gitdiff.diff(repo, base, head)
    units = unitmod.split(diff, lambda p: gitdiff.show(repo, head, p))
    nonblank = sum(1 for hs in diff.values() for h in hs for l in h if l[0] != " " and l[3].strip())
    assert nonblank == sum(u["added"] + u["removed"] for u in units), "a changed line belongs to no unit"

    if use_llm:
        rv = review.generate(case_dir, issue_text, units, gitdiff.git(repo, "diff", base, head), list(owners["routing"]))
    else:
        rv = review.load(case_dir)

    checks = {c["id"]: evidence.run_check(repo, head, issue_text.splitlines(), c) for c in rv["checks"]}
    test_names = [u["name"] for u in units if u["tier"] == "test" and "[Fact]" in "\n".join(l["text"] for l in u["lines"])]
    tests = evidence.run_tests(repo, case["test_project"], test_names, head, base)

    refusals = []
    for r in rv["refusals"]:
        owner = owners["routing"].get(r["category"], owners["approver"])
        refusals.append({**r, "owner": owner})

    files = {}
    for u in units:
        u |= {"reqs": [], "summary": "", "covered_by": []} | rv["units"].get(u["id"], {})
        if u["file"] not in files:
            files[u["file"]] = gitdiff.show(repo, head, u["file"])
        u["body"] = files[u["file"]][u["start"] - 1:u["end"]]           # the whole function, as it is after the change
        u["callers"] = evidence.blast_radius(repo, head, u)
        u["calls"] = evidence.calls_out(repo, head, u)
        mine = [r for r in refusals if u["id"] in r["units"]]
        u["gates"], u["status"] = evidence.gates(u, list(checks.values()), tests, mine)
        u["findings"] = [f["id"] for f in rv["findings"] if f["unit"] == u["id"]]
        u["refusals"] = [r["id"] for r in mine]

    findings = [{**f, "confidence": confidence(f, checks)} for f in rv["findings"]]
    count = lambda s: sum(u["status"] == s for u in units)
    lines = lambda us: sum(u["added"] + u["removed"] for u in us)
    dossier = {
        "case": case, "issue_text": issue_text, "owners": owners,
        "review_source": {"kind": rv["source"], "note": rv.get("source_note", "")},
        "requirements": rv["requirements"], "units": units, "checks": list(checks.values()),
        "tests": tests, "findings": findings, "proposed_tests": rv.get("proposed_tests", []),
        "refusals": refusals,
        "summary": {
            "units": len(units), "cleared": count("cleared"), "held": count("held"), "routed": count("routed"),
            "lines_changed": lines(units),
            "lines_to_read": lines([u for u in units if u["status"] != "cleared"]),
            "lines_routed": lines([u for u in units if u["status"] == "routed"]),
            "checks": len(checks), "checks_hold": sum(c["holds"] for c in checks.values()),
            "tests": len(tests), "tests_run": sum(t["status"] in ("passed", "failed") for t in tests.values()),
            "tests_passed": sum(t["status"] == "passed" for t in tests.values()),
            "findings": len(findings), "refusals": len(refusals),
        },
    }
    body = json.dumps(dossier, indent=1)
    dossier["id"] = hashlib.sha256(body.encode()).hexdigest()[:12]   # decisions cite the exact dossier
    out = ROOT / "dossier" / f"{issue}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(dossier, indent=1))
    return out, dossier


def main():
    args = sys.argv[1:]
    issue = next((a for a in args if a.isdigit()), "2283")
    use_llm = "--llm" in args
    if use_llm and not review.key_available():
        sys.exit("--llm needs ANTHROPIC_API_KEY; without it the cached or hand-written review is used.")
    out, d = build(issue, use_llm)
    s = d["summary"]
    print(f"{out.relative_to(ROOT)}  review={d['review_source']['kind']}  units={s['units']} "
          f"cleared={s['cleared']} held={s['held']} routed={s['routed']}  "
          f"read {s['lines_to_read']}/{s['lines_changed']} lines  checks {s['checks_hold']}/{s['checks']} hold  "
          f"tests run {s['tests_run']}/{s['tests']}")


if __name__ == "__main__":
    main()
