"""Local batch evaluation of scripted policies (no LLM).

    python -m survivor.evaluate --policy reference --seeds 0:100
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from typing import Any

from .config import GameConfig
from .game import Game
from .policies import AllianceFarmer, Coalition, Exploiter, RandomPolicy, Reference, StopEarly, do_nothing, passive, play

POLICIES = {
    "do_nothing": lambda seed: do_nothing,
    "stop_early": lambda seed: StopEarly(1),
    "passive": lambda seed: passive,
    "random": lambda seed: RandomPolicy(seed),
    "reference": lambda seed: Reference(),
    "coalition": lambda seed: Coalition(1, 0),
    "exploiter": lambda seed: Exploiter(seed),
    "alliance_farmer": lambda seed: AllianceFarmer(),
}


def run(policy: str, seed: int) -> dict[str, Any]:
    g = play(Game(GameConfig(seed=seed)), POLICIES[policy](seed))
    return {"seed": seed, "policy": policy, "reward": g.reward(), "placement": g.placement(),
            "terminal": g.terminal, "winner": g.winner, **g.metrics()}


def parse_seeds(s: str) -> list[int]:
    if ":" in s:
        a, b = s.split(":")
        return list(range(int(a), int(b)))
    return [int(x) for x in s.split(",")]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    rewards = [r["reward"] for r in rows]
    wins = sum(r["placement"] == 1 for r in rows)
    p = wins / n
    return {
        "n": n,
        "mean_reward": round(statistics.mean(rewards), 3),
        "win_rate": f"{wins}/{n} = {p:.2f} ± {1.96 * math.sqrt(p * (1 - p) / n):.2f}",
        "finalist_rate": round(sum(r["placement"] <= 2 and r["placement"] > 0 for r in rows) / n, 2),
        "mean_placement": round(statistics.mean(r["placement"] or 8 for r in rows), 2),
        "promises_broken": round(statistics.mean(r["promises_broken"] for r in rows), 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="all")
    ap.add_argument("--seeds", default="0:100")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    seeds = parse_seeds(a.seeds)
    names = list(POLICIES) if a.policy == "all" else a.policy.split(",")
    out = {}
    for name in names:
        rows = [run(name, s) for s in seeds]
        out[name] = summarize(rows)
        if not a.json:
            print(f"{name:12s} {out[name]}")
    if a.json:
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
