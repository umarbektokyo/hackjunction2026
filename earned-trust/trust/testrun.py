"""Run the tests that came with a change, twice: on the change, and with its source reverted to base.

A test is evidence for the change only if it passes with it and fails, or no longer compiles,
without it. A test that passes both ways does not test the change. Never reports a pass it did not see.
"""

import re
import shutil
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .gitdiff import git

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".work"
JUNIT_JAR = WORK / "junit-console-1.11.4.jar"
JUNIT_URL = ("https://repo1.maven.org/maven2/org/junit/platform/junit-platform-console-standalone/"
             "1.11.4/junit-platform-console-standalone-1.11.4.jar")


def checkout(repo, rev, name, revert=None):
    """A worktree of `rev` under .work/<name>; revert=(base, path) puts that path back to base."""
    path = WORK / name
    if not path.exists():
        git(repo, "worktree", "add", "--force", "--detach", str(path), rev)
    git(str(path), "checkout", "-q", "--detach", "--force", rev)
    git(str(path), "clean", "-qfdx")
    if revert:
        base, sub = revert
        for added in git(repo, "diff", "--name-only", "--diff-filter=A", base, rev, "--", sub).split():
            (path / added).unlink()
        git(str(path), "checkout", "-q", base, "--", sub)
    return str(path)


def dotnet(cwd, spec, names):
    flt = "|".join(f"FullyQualifiedName~{n}" for n in names)
    out = subprocess.run(["dotnet", "test", spec["project"], "--filter", flt, "--logger", "console;verbosity=normal"],
                         cwd=cwd, capture_output=True, text=True).stdout
    return dotnet_results(out, names)


def dotnet_results(out, names):
    """Per test name: passed, failed, does not compile or not found, from `dotnet test` console output."""
    if "Build FAILED" in out:
        return {n: "does not compile" for n in names}
    return {n: "passed" if re.search(rf"Passed\s+\S*\b{n}\b", out) else
               "failed" if re.search(rf"Failed\s+\S*\b{n}\b", out) else "not found in output" for n in names}


def junit(cwd, spec, names):
    if not JUNIT_JAR.exists():
        WORK.mkdir(exist_ok=True)
        urllib.request.urlretrieve(JUNIT_URL, JUNIT_JAR)
    classes, reports = Path(cwd, ".classes"), Path(cwd, ".reports")
    sources = [str(p) for d in (spec["src"], spec["tests"]) for p in Path(cwd, d).rglob("*.java")]
    if subprocess.run(["javac", "-d", str(classes), "-cp", str(JUNIT_JAR), *sources], capture_output=True).returncode:
        return {n: "does not compile" for n in names}
    subprocess.run(["java", "-jar", str(JUNIT_JAR), "execute", "-cp", str(classes), "--scan-classpath",
                    "--disable-banner", "--reports-dir", str(reports)], cwd=cwd, capture_output=True)
    return junit_results(reports, names)


def junit_results(reports, names):
    """Per test name: passed, failed, skipped or not found, from JUnit's XML reports in `reports`."""
    seen = {}
    for xml in Path(reports).glob("*.xml"):
        for case in ET.parse(xml).iter("testcase"):
            bad = case.find("failure") is not None or case.find("error") is not None
            seen[case.get("name").split("(")[0]] = "failed" if bad else "skipped" if case.find("skipped") is not None else "passed"
    return {n: seen.get(n, "not found in output") for n in names}


RUNNERS = {"dotnet": (dotnet, "dotnet"), "junit": (junit, "javac")}


def verdict(here, without):
    """What one test's two runs mean, in words a reviewer can use."""
    proves = here == "passed" and without in ("failed", "does not compile")
    if proves and without == "failed":
        why = "passes with the change and fails without it: it tests the change"
    elif proves:
        why = "passes with the change; without it the test does not compile, so it tests new code"
    elif here == "passed":
        why = f"passes with the change, and is {without} without it: it does not test the change"
    else:
        why = f"{here} with the change"
    return {"status": here, "without_fix": without, "proves_fix": proves, "why": why}


def run(repo, spec, names, head, base):
    if not names:
        return {}
    runner, tool = RUNNERS[spec["kind"]]
    if not shutil.which(tool):
        return {n: {"status": "not run", "why": f"{tool} is not installed on the review machine"} for n in names}
    rev = git(repo, "rev-parse", head).strip()[:10]
    here = runner(checkout(repo, head, rev), spec, names)
    without = runner(checkout(repo, head, rev + "-without", (base, spec["src"])), spec, names)
    return {n: verdict(here[n], without[n]) for n in names}
