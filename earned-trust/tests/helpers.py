"""Shared test helpers: throwaway git repositories."""

import subprocess
import tempfile
from pathlib import Path


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True, check=True).stdout


def repo_with(*commits):
    """A repo with one commit per {path: text or None (delete)} dict; returns its path."""
    repo = Path(tempfile.mkdtemp())
    git(repo, "init", "-q", "-b", "main")
    for files in commits:
        for path, text in files.items():
            target = repo / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "commit", "--allow-empty")
    return repo
