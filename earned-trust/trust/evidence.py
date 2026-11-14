"""Deterministic evidence: call sites, claim checks, test runs and the four gates per unit."""

import re
import shutil
from collections import Counter
import subprocess

from .gitdiff import git, show
from .units import spans

GATES_REQUIRED = {"shipped": ("traced", "checked", "executed", "uncontested"),
                  "test": ("traced", "checked", "uncontested"),
                  "doc": ("traced", "checked", "uncontested")}


def blast_radius(repo, rev, unit):
    """Who calls the changed member, and who calls those callers (two levels). [] for docs and tests."""
    if unit["file"].endswith(".md") or unit["name"] == "file header" or "[Fact]" in _text(unit):
        return []
    first = callers(repo, rev, unit["name"], unit["file"], unit["name"], unit.get("callers_pattern"))
    seen = {unit["name"]}
    for site in first:
        if site["member"] not in seen:
            seen.add(site["member"])
            site["callers"] = callers(repo, rev, site["member"], site["file"], site["member"])
    return first


def _file(repo, rev, path, cache={}):
    """(lines, member spans) of a file at `rev`, read once."""
    if (path, rev) not in cache:
        lines = show(repo, rev, path)
        cache[path, rev] = (lines, spans(path, lines))
    return cache[path, rev]


def _member_at(repo, rev, path, line):
    return next((n for n, a, b in _file(repo, rev, path)[1] if a <= line <= b), "?")


def _excerpt(repo, rev, path, line, around=2):
    lines = _file(repo, rev, path)[0]
    return [{"line": i, "text": lines[i - 1]} for i in range(max(1, line - around), min(len(lines), line + around) + 1)]


def calls_out(repo, rev, unit):
    """Members of the same file that the visible lines of this unit call, with each callee's signature."""
    if unit["file"].endswith(".md"):
        return []
    lines, members = _file(repo, rev, unit["file"])
    out, seen = [], set()
    for l in unit["lines"]:
        if l["kind"] == "-":
            continue
        for name in re.findall(r"(?<![\w.])(?:this\.)?([A-Za-z_]\w*)\s*(?:<[^()]*>)?\(", l["text"]):
            span = next(((a, b) for n, a, b in members if n == name and n not in (unit["name"], "file header")), None)
            if not span or span[0] <= l["new"] <= span[1] or (name, l["new"]) in seen:
                continue
            seen.add((name, l["new"]))
            decl = next(i for i in range(span[0], span[1] + 1) if re.search(rf"\b{name}\s*[<(]", lines[i - 1]))
            out.append({"member": name, "file": unit["file"], "line": l["new"], "text": l["text"].strip(),
                        "decl": decl, "signature": lines[decl - 1].strip()})
    return out


def callers(repo, rev, name, home, own_member, pattern=None):
    """Call sites of member `name` declared in file `home`, outside `own_member`, with their enclosing member.

    By name, not by symbol: an unqualified call counts only in `home`, a qualified one only as
    `<Class>.name(` where Class is the file's stem. Calls through other receivers are missed (a stated limit).
    """
    cls = home.rsplit("/", 1)[-1].split(".")[0]
    try:
        out = git(repo, "grep", "-n", "-E", pattern or rf"{name} *\(", rev, "--", "*.cs")
    except subprocess.CalledProcessError:   # git grep exits 1 when nothing matches
        return []
    sites = []
    for line in out.splitlines():
        _, path, no, text = line.split(":", 3)
        local = path == home and re.search(rf"(?<![\w.])(this\.)?{name} *\(", text)
        if not (pattern or local or re.search(rf"\b{cls}\.{name} *\(", text)) or text.strip().startswith("//"):
            continue
        member = _member_at(repo, rev, path, int(no))
        if (path, member) != (home, own_member):
            sites.append({"file": path, "line": int(no), "member": member, "text": text.strip(),
                          "excerpt": _excerpt(repo, rev, path, int(no))})
    return sites


def _text(unit):
    return "\n".join(l["text"] for l in unit["lines"])


def run_check(repo, rev, issue_lines, check):
    """A check is a claim plus a regex over named files. It holds when every file meets `expect`:
    'present', 'absent', '==N' or '>=N' (match count), optionally within a line `range`."""
    rx, matches, holds = re.compile(check["pattern"]), [], True
    for path in check["paths"]:
        lines = issue_lines if path == "@issue" else show(repo, rev, path)
        lo, hi = check.get("range", (1, len(lines)))
        hits = [{"file": path, "line": i + 1, "text": t.strip()}
                for i, t in enumerate(lines) if lo <= i + 1 <= hi and rx.search(t)]
        matches += hits
        exp = check["expect"]
        n = len(hits)
        holds &= {"present": n > 0, "absent": n == 0}.get(exp) if exp in ("present", "absent") else \
            (n == int(exp[2:]) if exp.startswith("==") else n >= int(exp[2:]))
    return {**check, "holds": holds, "count": len(matches), "matches": matches[:8]}


def run_tests(repo, project, names):
    """Run the named tests with `dotnet test` when the SDK exists. Never reports a pass it did not see."""
    if not shutil.which("dotnet"):
        return {n: {"status": "not run", "why": ".NET SDK not installed on the review machine"} for n in names}
    flt = "|".join(f"FullyQualifiedName~{n}" for n in names)
    out = subprocess.run(["dotnet", "test", project, "--filter", flt, "--logger", "console;verbosity=normal"],
                         cwd=repo, capture_output=True, text=True).stdout
    result = {}
    for n in names:
        status = "passed" if re.search(rf"Passed\s+\S*\b{n}\b", out) else \
            "failed" if re.search(rf"Failed\s+\S*\b{n}\b", out) else "not found in output"
        result[n] = {"status": status, "why": "dotnet test"}
    return result


def gates(unit, checks, tests, refusals):
    """Gate states: 'pass', 'fail' or 'missing', each with the evidence it rests on."""
    mine = [c for c in checks if unit["id"] in c.get("units", [])]
    covering = [t for t, r in tests.items() if t in unit.get("covered_by", [])]
    g = {
        "traced": ("pass", unit["reqs"]) if unit["reqs"] else ("missing", ["no requirement"]),
        "checked": ("missing", ["no check"]) if not mine else
                   ("pass" if all(c["holds"] for c in mine) else "fail", [c["id"] for c in mine]),
        "executed": ("missing", ["no covering test"]) if not covering else
                    ("pass" if all(tests[t]["status"] == "passed" for t in covering) else "missing",
                     [f"{n} of {len(covering)} tests {st}" for st, n in
                      sorted(Counter(tests[t]["status"] for t in covering).items())]),
        "uncontested": ("pass", []) if not refusals else ("fail", [r["id"] for r in refusals]),
    }
    required = GATES_REQUIRED[unit["tier"]]
    if refusals:
        status = "routed"
    elif all(g[k][0] == "pass" for k in required):
        status = "cleared"
    else:
        status = "held"
    return {k: {"state": s, "evidence": e, "required": k in required} for k, (s, e) in g.items()}, status
