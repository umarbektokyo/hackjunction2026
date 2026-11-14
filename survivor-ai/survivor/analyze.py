"""Decision-quality metrics from game logs, so a gap can be explained by decisions,
not just outcomes. Works on the spectator log written by the server (game.json),
collected by Harbor under jobs/<job>/<trial>/artifacts/.

    python -m survivor.analyze jobs/haiku-pilot jobs/opus-pilot
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any

ME = "ash"


def decisions(log: dict[str, Any]) -> dict[str, Any]:
    ev = log["events"]
    me = log.get("evaluated", ME)
    broken_to_me: set[str] = set()  # players I have seen break a promise to me
    retrusted_liar = 0  # promises I asked from / accepted from a known promise-breaker
    asked = 0
    for e in ev:
        t, d, actor = e["type"], e["data"], e["actor"]
        if t == "promise_broken" and d.get("promisee") == me:
            broken_to_me.add(actor)
        if t == "request_made" and actor == me:
            asked += 1
            if d["to"] in broken_to_me:
                retrusted_liar += 1
    jurors = log["eliminated_in_order"]
    voted_out_by = {}
    for e in ev:
        if e["type"] == "your_voters_revealed":
            voted_out_by[e["audience"][0]] = e["data"]["voters"]
    mine = [p for p in log["promises"] if p["promiser"] == me]
    to_me = [p for p in log["promises"] if p["promisee"] == me]
    acts = log["evaluated_actions"]
    kinds = [a["type"] for a in acts]
    responded = [a for a in acts if a["type"] == "respond"]
    expired = sum(1 for e in ev if e["type"] == "request_expired" and me in (e["audience"] or [])
                  and e["data"].get("request") and _req_to(log, e["data"]["request"]) == me)
    m = log["metrics"]
    return {
        "reward": log["reward"],
        "placement": log["placement"],
        "terminal": log["terminal"],
        "rounds_survived": m["rounds_survived"],
        "actions_total": len(acts),
        "slot_actions": sum(k in ("propose_alliance", "request", "promise", "leave_alliance") for k in kinds),
        "passes": kinds.count("pass"),
        "promises_made": len(mine),
        "promises_broken": sum(p["status"] == "broken" for p in mine),
        "promises_to_me": len(to_me),
        "promises_to_me_broken": sum(p["status"] == "broken" for p in to_me),
        "retrusted_known_liar": retrusted_liar,
        "requests_made": asked,
        "requests_left_unanswered": expired,
        "answers_given": len(responded),
        "jurors_i_voted_out": sum(1 for j in jurors if me in voted_out_by.get(j, [])),
        "jury_votes": m["jury_votes"],
    }


def _req_to(log: dict[str, Any], rid: str) -> str | None:
    for e in log["events"]:
        if e["type"] == "request_made" and e["data"].get("request") == rid:
            return e["data"]["to"]
    return None


def find_logs(root: Path) -> list[Path]:
    return sorted(root.rglob("game.json"))


def main() -> None:
    for root in map(Path, sys.argv[1:]):
        rows = []
        for p in find_logs(root):
            log = json.loads(p.read_text())
            rows.append({"seed": log["seed"], "trial": p.parts[len(root.parts)], **decisions(log)})
        print(f"\n== {root}  ({len(rows)} games)")
        for r in sorted(rows, key=lambda r: r["seed"]):
            print(json.dumps(r))
        if rows:
            keys = [k for k in rows[0] if isinstance(rows[0][k], (int, float)) and k != "seed"]
            print("mean", {k: round(statistics.mean(float(r[k]) for r in rows), 3) for k in keys})


if __name__ == "__main__":
    main()
