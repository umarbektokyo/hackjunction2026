"""Run a local Survivor match with command-driven agent participants.

Each controller is an executable that reads one protocol JSON object from stdin and
prints one JSON object to stdout. It can wrap any LLM or agent framework without
changing the deterministic Harbor task path.
"""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import time
from pathlib import Path
from typing import Any

from .command_agent import CommandSeat
from .config import GameConfig, PLAYER_NAMES
from .game import ActionError, Game
from .npc import NPC
from .policies import Reference

PROJECT = Path(__file__).resolve().parents[1]


def parse_seeds(value: str) -> list[int]:
    if ":" in value:
        start, stop = value.split(":", 1)
        return list(range(int(start), int(stop)))
    if "-" in value:
        start, stop = value.split("-", 1)
        return list(range(int(start), int(stop) + 1))
    return [int(part) for part in value.split(",") if part]


def write_snapshot(path: Path, game: Game) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(game.export()))
    tmp.replace(path)


def run_game(seed: int, output: Path, ash_command: list[str] | None,
             opponent_command: list[str] | None, opponent_seats: set[str],
             ash_label: str, opponent_label: str, timeout: float,
             discussion_turns: int) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    game_path = output / "game.json"

    def make_npc(pid: str, personality: Any, game: Game) -> Any:
        if opponent_command is not None and pid in opponent_seats:
            return CommandSeat(pid, personality, game, opponent_command, timeout, opponent_label)
        return NPC(pid, personality, game)

    game = Game(GameConfig(seed=seed, discussion_turns=discussion_turns),
                npc_factory=make_npc,
                snapshot_callback=lambda current: write_snapshot(game_path, current))
    ash = (CommandSeat("ash", None, game, ash_command, timeout, ash_label)
           if ash_command is not None else None)
    reference = Reference() if ash is None else None
    calls = 0

    while not game.terminal:
        if not game.needs_evaluated():
            game.run_npcs()
            if game.terminal:
                break
            if not game.needs_evaluated():
                continue
        obs = game.observe("ash", since=0)
        if game.phase == "discussion":
            action = ash.decide_slot() if ash else reference(obs)
        else:
            targets = obs.get("you_may_vote_for", [])
            target = ash.decide_vote(targets, revote=game.phase == "revote") if ash else None
            if ash is None:
                target = (reference(obs) or {}).get("target")
            action = {"type": "vote", "target": target}

        try:
            game.act(action)
        except (ActionError, KeyError, TypeError) as error:
            game._log("controller_action_rejected", "ash", ["ash"],
                      error=str(error)[:240], fallback="safe_action")
            if game.phase in ("voting", "revote"):
                legal = obs.get("you_may_vote_for", [])
                fallback = {"type": "vote", "target": sorted(legal)[0]}
            elif game.current_actor == "ash":
                fallback = {"type": "pass"}
            elif game.pending_for("ash"):
                fallback = {"type": "respond", "item_id": game.pending_for("ash")[0], "accept": False}
            else:
                fallback = {"type": "pass"}
            game.act(fallback)
        calls += 1
        if calls > 3000:
            raise RuntimeError(f"arena match for seed {seed} exceeded 3000 ash decisions")

    write_snapshot(game_path, game)
    row = {
        "seed": seed, "status": "ok", "terminal": game.terminal,
        "reward": game.reward(), "placement": game.placement(),
        "winner": game.winner, "agent_decisions": calls,
        **game.metrics(),
    }
    (output / "row.json").write_text(json.dumps(row) + "\n")
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Run command-controlled agents in Survivor.")
    parser.add_argument("--seeds", default="101-105", help="e.g. 101-105, 101:106, or 101,102")
    parser.add_argument("--all-seats-command", help="use one JSON-in/JSON-out command for all eight seats")
    parser.add_argument("--ash-command", help="controller command for evaluated seat ash")
    parser.add_argument("--opponent-command", help="controller command for selected NPC seats")
    parser.add_argument("--opponent-seats", default="all", help="all, or comma-separated NPC names")
    parser.add_argument("--ash-label", default="ash-agent")
    parser.add_argument("--opponent-label", default="opponent-agent")
    parser.add_argument("--timeout", type=float, default=90.0, help="seconds allowed per agent decision")
    parser.add_argument("--discussion-turns", type=int, default=1,
                        help="discussion slots per player per round; default 1 keeps LLM arenas tractable")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.all_seats_command:
        ash_command = shlex.split(args.all_seats_command)
        opponent_command = ash_command
        args.ash_label = args.ash_label if args.ash_label != "ash-agent" else "shared-agent"
        args.opponent_label = args.opponent_label if args.opponent_label != "opponent-agent" else "shared-agent"
    else:
        ash_command = shlex.split(args.ash_command) if args.ash_command else None
        opponent_command = shlex.split(args.opponent_command) if args.opponent_command else None
    if ash_command is None and opponent_command is None:
        parser.error("provide --all-seats-command, --ash-command, or --opponent-command")
    if not 1 <= args.discussion_turns <= 4:
        parser.error("--discussion-turns must be between 1 and 4")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if ash_command == [] or opponent_command == []:
        parser.error("agent commands must not be empty")
    npc_names = set(PLAYER_NAMES) - {"ash"}
    if args.opponent_seats == "all":
        opponent_seats = npc_names
    else:
        opponent_seats = {seat.strip() for seat in args.opponent_seats.split(",") if seat.strip()}
        invalid = opponent_seats - npc_names
        if invalid:
            parser.error(f"unknown opponent seats: {', '.join(sorted(invalid))}")

    seeds = parse_seeds(args.seeds)
    if not seeds:
        parser.error("provide at least one seed")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else PROJECT / "results" / "runs" / f"arena-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    metadata = {
        "kind": "command-agent-arena", "seeds": seeds,
        "ash_label": args.ash_label, "opponent_label": args.opponent_label,
        "opponent_seats": sorted(opponent_seats) if opponent_command else [],
        "discussion_turns": args.discussion_turns, "decision_timeout_seconds": args.timeout,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    (out / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")

    rows = []
    for seed in seeds:
        game_dir = out / f"seed{seed}-a1"
        row = run_game(seed, game_dir, ash_command, opponent_command, opponent_seats,
                       args.ash_label, args.opponent_label, args.timeout,
                       args.discussion_turns)
        rows.append(row)
        print(json.dumps(row), flush=True)
    (out / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"{len(rows)} games · mean reward {statistics.mean(r['reward'] for r in rows):.3f} · {out}")


if __name__ == "__main__":
    main()
