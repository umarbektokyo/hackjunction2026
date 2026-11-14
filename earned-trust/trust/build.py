"""Build the evidence dossier for one change: python -m trust.build <case> [--llm] [--reuse-tests]

A case is a folder input/<case>/ with case.json (repo, base, head, test runner, style config),
issue.md (the requirement) and a review layer (review.llm.json or review.handwritten.json).
"""

import hashlib
import json
import re
import sys
from pathlib import Path

from . import evidence, gitdiff, review, style, testrun, units as unitmod

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


def load_case(case_id):
    case_dir = ROOT / "input" / case_id
    case = json.loads((case_dir / "case.json").read_text())
    owners_file = case_dir / "owners.json"
    owners = json.loads((owners_file if owners_file.exists() else ROOT / "input" / "owners.json").read_text())
    return case_dir, case, owners, (case_dir / "issue.md").read_text()


def split_units(repo, base, head):
    diff = gitdiff.diff(repo, base, head)
    units = unitmod.split(diff, lambda p: gitdiff.show(repo, head, p))
    nonblank = sum(1 for hs in diff.values() for h in hs for l in h if l[0] != " " and l[3].strip())
    assert nonblank == sum(u["added"] + u["removed"] for u in units), "a changed line belongs to no unit"
    return units


def test_names(units):
    """The test methods the change adds or edits (xUnit [Fact] or JUnit @Test)."""
    marked = lambda u: re.search(r"\[Fact\]|@Test\b", "\n".join(l["text"] for l in u["lines"]))
    return [u["name"] for u in units if u["tier"] == "test" and marked(u)]


def attach_evidence(units, rv, refusals, checks, tests, repo, head):
    """Give every unit its review text, whole body, callers, calls, gates and status."""
    files = {}
    for u in units:
        u |= {"reqs": [], "summary": "", "covered_by": []} | rv["units"].get(u["id"], {})
        if u["file"] not in files:
            files[u["file"]] = gitdiff.show(repo, head, u["file"])
        u["body"] = files[u["file"]][u["start"] - 1:u["end"]]
        u["callers"] = evidence.blast_radius(repo, head, u)
        u["calls"] = evidence.calls_out(repo, head, u)
        mine = [r for r in refusals if u["id"] in r["units"]]
        u["gates"], u["status"] = evidence.gates(u, list(checks.values()), tests, mine)
        u["findings"] = [f["id"] for f in rv["findings"] if f["unit"] == u["id"]]
        u["refusals"] = [r["id"] for r in mine]


def summarise(units, checks, tests, findings, refusals):
    count = lambda s: sum(u["status"] == s for u in units)
    lines = lambda us: sum(u["added"] + u["removed"] for u in us)
    return {
        "units": len(units), "cleared": count("cleared"), "held": count("held"), "routed": count("routed"),
        "lines_changed": lines(units), "lines_to_read": lines([u for u in units if u["status"] != "cleared"]),
        "lines_routed": lines([u for u in units if u["status"] == "routed"]),
        "checks": len(checks), "checks_hold": sum(bool(c["holds"]) for c in checks.values()),
        "tests": len(tests), "tests_run": sum(t["status"] in ("passed", "failed") for t in tests.values()),
        "tests_passed": sum(t["status"] == "passed" for t in tests.values()),
        "findings": len(findings), "refusals": len(refusals),
    }


def previous_tests(case_id):
    """The test results of the last build, for rebuilding without running the tests again."""
    return json.loads((ROOT / "dossier" / f"{case_id}.json").read_text())["tests"]


def build(case_id, use_llm=False, reuse_tests=False):
    case_dir, case, owners, issue_text = load_case(case_id)
    repo, base, head = str(ROOT / case["repo"]), case["base"], case["head"]
    units = split_units(repo, base, head)
    rv = review.generate(case_dir, issue_text, units, gitdiff.git(repo, "diff", base, head), list(owners["routing"])) \
        if use_llm else review.load(case_dir)
    checks = {c["id"]: evidence.run_check(repo, head, issue_text.splitlines(), c) for c in rv["checks"]}
    checks |= {c["id"]: c for c in style.checks(repo, head, case.get("style"), units)}
    tests = previous_tests(case_id) if reuse_tests else testrun.run(repo, case["tests"], test_names(units), head, base)
    refusals = [{**r, "owner": owners["routing"].get(r["category"], owners["approver"])} for r in rv["refusals"]]
    attach_evidence(units, rv, refusals, checks, tests, repo, head)
    findings = [{**f, "confidence": confidence(f, checks)} for f in rv["findings"]]
    dossier = {
        "case": case, "issue_text": issue_text, "owners": owners,
        "review_source": {"kind": rv["source"], "note": rv.get("source_note", "")},
        "requirements": rv["requirements"], "units": units, "checks": list(checks.values()),
        "tests": tests, "findings": findings, "proposed_tests": rv.get("proposed_tests", []),
        "refusals": refusals, "summary": summarise(units, checks, tests, findings, refusals),
    }
    dossier["id"] = hashlib.sha256(json.dumps(dossier, indent=1).encode()).hexdigest()[:12]   # decisions cite it
    out = ROOT / "dossier" / f"{case_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(dossier, indent=1))
    return out, dossier


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    case_id, use_llm = (args[0] if args else "2283"), "--llm" in sys.argv
    if use_llm and not review.available():
        sys.exit("--llm needs the `claude` CLI, logged in.")
    out, d = build(case_id, use_llm, "--reuse-tests" in sys.argv)
    s = d["summary"]
    print(f"{out.relative_to(ROOT)}  review={d['review_source']['kind']}  units={s['units']} "
          f"cleared={s['cleared']} held={s['held']} routed={s['routed']}  "
          f"checks {s['checks_hold']}/{s['checks']} hold  tests run {s['tests_run']}/{s['tests']}")


if __name__ == "__main__":
    main()
