"""Coding standards as evidence: Checkstyle on the changed Java units, judged on the changed lines.

Violations on lines the change did not touch are counted as pre-existing, not held against it.
"""

import re
import shutil
import subprocess

from . import testrun
from .gitdiff import git

REPORT = re.compile(r"^\[(\w+)\] (.+?):(\d+)(?::\d+)?: (.+) \[(\w+)\]$")


def violations(worktree, config, files):
    """[(path, line, message)] from a Checkstyle run over `files`."""
    out = subprocess.run(["checkstyle", "-c", config, *files], cwd=worktree, capture_output=True, text=True).stdout
    return [(m[2], int(m[3]), f"{m[4]} [{m[5]}]") for m in map(REPORT.match, out.splitlines()) if m]


def check_for(n, unit, found, config):
    added = {l["new"] for l in unit["lines"] if l["kind"] == "+"}
    mine = [{"file": unit["file"], "line": line, "text": msg} for path, line, msg in found
            if path.endswith(unit["file"]) and unit["start"] <= line <= unit["end"]]
    new = [m for m in mine if m["line"] in added]
    return {"id": f"S{n}", "kind": "style", "claim": f"The changed lines of {unit['name']} follow the project's "
            f"coding standards ({config}).", "paths": [unit["file"]], "units": [unit["id"]],
            "holds": not new, "count": len(new), "matches": new[:8], "preexisting": len(mine) - len(new)}


def checks(repo, head, spec, units):
    """One check per changed Java unit; [] when the case has no style config or Checkstyle is missing."""
    changed = [u for u in units if u["file"].endswith(".java") and u["added"]]
    if not spec or spec.get("kind") != "checkstyle" or not changed or not shutil.which("checkstyle"):
        return []
    tree = testrun.checkout(repo, head, git(repo, "rev-parse", head).strip()[:10])
    found = violations(tree, spec["config"], sorted({u["file"] for u in changed}))
    return [check_for(n, u, found, spec["config"]) for n, u in enumerate(changed, 1)]
