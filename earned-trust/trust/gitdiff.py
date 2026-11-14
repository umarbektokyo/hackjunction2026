"""Git access: the diff of a change as hunks with real line numbers, and file contents."""

import re
import subprocess

HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def show(repo, rev, path):
    """File contents at a revision, as a list of lines (index 0 = line 1)."""
    return git(repo, "show", f"{rev}:{path}").splitlines()


def diff(repo, base, head, context=3):
    """Parse `git diff` into {path: [hunk]}.

    A hunk is a list of lines (kind, old_no, new_no, text) where kind is ' ', '+' or '-'.
    Removed lines carry the new-file line number they sit before, so every line maps to a
    position in the new file.
    """
    files, path, hunk, old, new = {}, None, None, 0, 0
    for line in git(repo, "diff", f"-U{context}", base, head).splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            files.setdefault(path, [])
        elif line.startswith(("--- ", "diff ", "index ", "new file", "deleted file")):
            continue
        elif m := HUNK.match(line):
            old, new = int(m[1]), int(m[2])
            hunk = []
            files[path].append(hunk)
        elif hunk is not None and line[:1] in (" ", "+", "-"):
            kind, text = line[0], line[1:]
            hunk.append((kind, old if kind != "+" else None, new, text))
            old += kind != "+"
            new += kind != "-"
    files.pop(None, None)
    return files
