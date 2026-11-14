#!/usr/bin/env python3
"""Generate the Harbor tasks for Survivor: one task directory per seed.

    python harbor/make_tasks.py                 # seeds 101..105
    python harbor/make_tasks.py --seeds 7 8 9   # other seeds
    python harbor/make_tasks.py --check         # fail if committed tasks are stale

Every task is the template in harbor/template/ with the seed filled in, plus a
vendored copy of the game package so each task directory is self-contained
(Harbor builds images from the task's own environment/ directory):

    environment/mcp-server/survivor/   engine + MCP server (sidecar image only)
    solution/survivor/                 engine + scripted policies + MCP driver
                                       (uploaded only for the oracle agent)

The agent image (environment/Dockerfile) gets no game code at all.
Re-run this script whenever survivor/ changes. Standard library only.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
TEMPLATE = HERE / "template"
PACKAGE = PROJECT / "survivor"
DEFAULT_SEEDS = [101, 102, 103, 104, 105]

SERVER_MODULES = ["__init__.py", "config.py", "game.py", "npc.py", "mcp_server.py"]
SOLUTION_MODULES = ["__init__.py", "config.py", "game.py", "npc.py", "policies.py", "mcp_driver.py"]
SERVER_DEPS = ["mcp", "pydantic", "uvicorn"]
CLIENT_DEPS = ["mcp"]
TEXT_SUFFIXES = {".toml", ".md", ".yaml", ".sh", ".py", ".txt", ""}


def locked_versions() -> dict[str, str]:
    lock = tomllib.loads((PROJECT / "uv.lock").read_text())
    return {p["name"]: p["version"] for p in lock["package"] if "version" in p}


def load_engine():
    """Import the current survivor.config / survivor.game (standard library only)."""
    sys.path.insert(0, str(PROJECT))
    try:
        import survivor.config as config
        import survivor.game as game
    finally:
        sys.path.pop(0)
    return config, game


def _num(x: float) -> str:
    return f"{x:g}"


def scoring_table(cfg) -> str:
    """The reward rules of Game.reward(), rendered from GameConfig for the instruction."""
    n = len(cfg.players)
    base = getattr(cfg, "finalist_base", 0.0)
    share = cfg.finalist_share
    jurors = n - 2
    loser = f"{_num(share)} × (jury votes you received ÷ {jurors} jurors)"
    if base:
        loser = f"{_num(base)} + {loser}, i.e. {_num(base)} to {_num(round(base + share * (jurors // 2) / jurors, 4))}"
    rows = [
        ("You win the jury vote (1st place)", "**1.0**"),
        ("You reach the final two but lose the jury vote (2nd place)", loser),
    ]
    paid = dict(getattr(cfg, "placement_reward", ()))
    for place in sorted(paid):
        rnd = n + 1 - place  # eliminated in round r => final place n + 1 - r
        rows.append((f"You are voted out in round {rnd} (place {place} of {n})", _num(paid[place])))
    rows.append(("You are voted out earlier" if paid else "You are eliminated before the final two", "0"))
    rows.append(("The game is not finished when you stop calling tools", "0, whatever your position"))
    lines = ["| Outcome | Reward |", "|---|---|", *(f"| {a} | {b} |" for a, b in rows)]
    return "\n".join(lines)


def substitutions(seed: int) -> dict[str, str]:
    config, game = load_engine()
    cfg = config.GameConfig(seed=seed)
    rules_hash = game.rules_hash(cfg) if hasattr(game, "rules_hash") else ""
    return {
        "__SEED__": str(seed),
        "__RULES_VERSION__": config.RULES_VERSION,
        "__RULES_HASH__": rules_hash,
        "__SCORING_TABLE__": scoring_table(cfg),
        "__DISCUSSION_TURNS__": str(cfg.discussion_turns),
        "__MAX_ALLIANCES__": str(cfg.max_alliances),
    }


def requirements(names: list[str], versions: dict[str, str]) -> str:
    return "".join(f"{n}=={versions[n]}\n" for n in names)


def vendor(dest: Path, modules: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in modules:
        shutil.copyfile(PACKAGE / name, dest / name)


def task_name(seed: int) -> str:
    return f"survivor-seed-{seed}"


def build_task(seed: int, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(TEMPLATE, out)
    subs = substitutions(seed)
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            text = path.read_text()
            new = text
            for key, value in subs.items():
                new = new.replace(key, value)
            if new != text:
                path.write_text(new)
    versions = locked_versions()
    env = out / "environment"
    (env / "requirements-client.txt").write_text(requirements(CLIENT_DEPS, versions))
    (env / "mcp-server" / "requirements.txt").write_text(requirements(SERVER_DEPS, versions))
    vendor(env / "mcp-server" / "survivor", SERVER_MODULES)
    vendor(out / "solution" / "survivor", SOLUTION_MODULES)
    for script in (out / "solution" / "solve.sh", out / "tests" / "test.sh"):
        script.chmod(0o755)


def same_tree(a: Path, b: Path) -> list[str]:
    """Relative paths that differ between two directory trees."""
    diffs: list[str] = []

    def walk(cmp: filecmp.dircmp, rel: Path) -> None:
        ignore = {"__pycache__"}
        diffs.extend(str(rel / n) for n in [*cmp.left_only, *cmp.right_only] if n not in ignore)
        _, mismatch, errors = filecmp.cmpfiles(cmp.left, cmp.right, cmp.common_files, shallow=False)
        diffs.extend(str(rel / n) for n in [*mismatch, *errors])
        for name, sub in cmp.subdirs.items():
            if name not in ignore:
                walk(sub, rel / name)

    walk(filecmp.dircmp(a, b), Path("."))
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=DEFAULT_SEEDS)
    ap.add_argument("--out", type=Path, default=HERE / "tasks", help="tasks directory (default: harbor/tasks)")
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if tasks differ from a fresh build")
    ap.add_argument("--prune", action="store_true", help="delete survivor-seed-* tasks for seeds not listed")
    args = ap.parse_args()

    if args.check:
        stale = []
        with tempfile.TemporaryDirectory() as tmp:
            for seed in args.seeds:
                fresh = Path(tmp) / task_name(seed)
                build_task(seed, fresh)
                current = args.out / task_name(seed)
                if not current.is_dir():
                    stale.append(f"{task_name(seed)}: missing")
                    continue
                stale.extend(f"{task_name(seed)}/{d}" for d in same_tree(fresh, current))
        if stale:
            print("stale tasks, re-run harbor/make_tasks.py:\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print(f"{len(args.seeds)} tasks up to date")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    wanted = {task_name(s) for s in args.seeds}
    if args.prune:
        for old in args.out.glob("survivor-seed-*"):
            if old.is_dir() and old.name not in wanted:
                shutil.rmtree(old)
                print(f"removed {old.relative_to(PROJECT)}")
    for seed in args.seeds:
        build_task(seed, args.out / task_name(seed))
        print(f"wrote {(args.out / task_name(seed)).relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
