"""Runs bot.py on fixed level 8 seeds in parallel and prints one results row per seed plus a total.

    python bench.py --name v1 --seeds 20 --params '{"fee_open": 1.3}'
    python bench.py --name ml --bot bot2.py --seeds 8 --jobs 7

Results are appended to logs/bench.jsonl so versions can be compared later.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
PY = str(Path(sys.executable).parent.resolve() / Path(sys.executable).name)


def run(seed: str, level: int, params: str, starter: bool, bot: str = "bot.py") -> dict:
    if starter:
        cmd = [PY, "-c", "import sys;from spread.starter import main;sys.argv=['s','--level',sys.argv[1],'--seed',sys.argv[2]];main()", str(level), seed]
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
        line = [l for l in out.stdout.splitlines() if l.startswith("End")]
        return {"seed": seed, "raw": line[0] if line else out.stderr[-300:]}
    cmd = [PY, str(HERE / bot), "--level", str(level), "--seed", seed, "--params", params, "--quiet", "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {"seed": seed, "error": (out.stderr or out.stdout)[-500:]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="run")
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--level", type=int, default=8)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--starter", action="store_true")
    ap.add_argument("--bot", default="bot.py", help="the bot script to run, e.g. bot2.py")
    a = ap.parse_args()
    seeds = [f"bench-{i}" for i in range(a.first, a.first + a.seeds)]
    with ThreadPoolExecutor(a.jobs) as pool:
        rows = list(pool.map(lambda s: run(s, a.level, a.params, a.starter, a.bot), seeds))
    if a.starter:
        for r in rows:
            print(r["seed"], r["raw"])
        return
    ok = [r for r in rows if "marginCents" in r]
    for r in rows:
        if "error" in r:
            print(r["seed"], "ERROR", r["error"])
        else:
            print(f"{r['seed']:<10} margin €{r['marginCents']/100:>11,.2f}  orders {r['wonOrders']:>4}  on time {r['onTimeShare']:6.1%}  undelivered {r['undeliveredShare']:5.1%}  {'ranked' if r['ranked'] else 'NOT ranked'}")
    if ok:
        total = sum(r["marginCents"] for r in ok) / 100
        ranked = sum(r["ranked"] for r in ok)
        worst = min(r["onTimeShare"] for r in ok)
        mean_ot = sum(r["onTimeShare"] for r in ok) / len(ok)
        print(f"\n{a.name}: mean margin €{total/len(ok):,.0f}/week  ranked {ranked}/{len(ok)}  on time mean {mean_ot:.1%} worst {worst:.1%}")
        (HERE / "logs").mkdir(exist_ok=True)
        with open(HERE / "logs" / "bench.jsonl", "a") as f:
            f.write(json.dumps({"name": a.name, "bot": a.bot, "level": a.level, "params": json.loads(a.params), "rows": rows}) + "\n")


if __name__ == "__main__":
    main()
