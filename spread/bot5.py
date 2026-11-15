"""Evil Club's desk, v5: a Python port of source-exp/RoutePulse v21e (commit eaa121a, MIT per the challenge rules)
in rp2/. The port must replay the TypeScript's actions exactly on the same seed: compare RP_LOG files with rp_diff.py.

    python bot5.py --seed bench-1                 one practice week, level 8
    python bot5.py --board                        our next ranking run (resumes an unfinished one)
    python bot5.py --final                        our copy of the final (waits until it is set)
    RP_LOG=logs/x.jsonl python bot5.py --seed s   also log every batch of actions, for a diff against the TypeScript run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

from spread.client import Client, SpreadError, Unreachable
from spread.starter import next_final, report

from rp2.desk import Desk
from rp2.rptime import DAY

try:
    from rp2.desk_b import wire
except ImportError:  # pragma: no cover - wherever the porters put it
    from rp2.outbox import wire  # type: ignore

WAKE_ON = ["price_request", "order_won", "order_changed", "order_cancelled", "visit_failed", "gig_expired", "deadline_close",
           "gig_booked", "gig_dropped", "no_show", "driver_late", "offer_answered", "delivered", "release", "forecast"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def log_actions(path, now, stop_at, actions) -> None:
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"now": now, "stopAt": stop_at, "actions": wire(actions)}, separators=(",", ":")) + "\n")


def play_practice(world, level: int, verbose: bool = True) -> dict:
    client = world.client
    snapshot = world.snapshot()
    now, ends_at = snapshot["now"], snapshot["endsAt"]
    desk = Desk(world, level, now, ends_at, client.map(), world.roster())
    if now > 0:
        history = world.events()
        world._last_seq = history[-1]["seq"] if history else -1
        desk.rejoin(snapshot, history)
        desk.tick_timers(False)
    log = os.environ.get("RP_LOG")
    while desk.now < ends_at:
        day = desk.now // DAY
        stop_at = min(ends_at, (day + 1) * DAY, desk.next_timer_at())
        actions = desk.drain_outbox_sorted()
        log_actions(log, desk.now, stop_at, actions)
        step = world.advance(until=WAKE_ON, max=stop_at, actions=wire(actions))
        desk.read_results(actions, step["results"])
        desk.now = step["now"]
        for event in step["events"]:
            desk.handle(event)
        desk.flush_pending_price_requests()
        desk.tick_timers(False)
        if verbose and desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
    desk.finalize_pending_revenue(ends_at)
    desk.send(False)
    return world.score()


def play_board(client, level: int) -> dict:
    mine = [w for w in client.worlds() if w["boardRun"] is not None and w["level"] == level and not w["ended"]]
    world = client.world(mine[0]["worldId"]) if mine else client.create(level=level, board=True)
    print(f"Ranking run {world.id}{' (resumed)' if mine else ''}, level {level}.", flush=True)
    while True:
        try:
            return {"world": world.id, **play_practice(world, level)}
        except KeyboardInterrupt:
            raise
        except SpreadError as error:
            if error.status in (400, 401):
                raise
            print(f"spread: {error}. Rebuilding the desk in 3 seconds.", file=sys.stderr, flush=True)
            time.sleep(3)
        except Exception:
            print(f"error, rebuilding the desk in 3 seconds:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            time.sleep(3)


def play_final(world) -> None:
    """starter.ts playFinal: rebuild from events + snapshot, then play the live stream."""
    client = world.client
    worlds, raw_map, roster = client.worlds(), client.map(), world.roster()
    history0 = world.events()
    snapshot = world.snapshot()
    if snapshot["now"] >= snapshot["endsAt"]:
        return
    seq0 = history0[-1]["seq"] if history0 else -1
    tail = world.events(after=seq0)
    full = history0 + tail
    start_after = full[-1]["seq"] if full else -1
    level = next((w["level"] for w in worlds if w["worldId"] == world.id), 8)
    desk = Desk(world, level, snapshot["now"], snapshot["endsAt"], raw_map, roster)
    desk.is_final = True
    desk.rejoin(snapshot, full)
    desk.tick_timers(True)
    desk.send(True)
    print(f"rejoined at minute {snapshot['now']}: {len(full)} events", flush=True)
    last_seq, roster_at, idle_check = start_after, time.monotonic(), 0.0
    for event in world.stream(after=start_after, idle=0.6):
        day = desk.now // DAY
        if event is None:
            if time.monotonic() - idle_check >= 4:
                idle_check = time.monotonic()
                try:
                    f = client.final()
                    if f["now"] > desk.now:
                        for ev in world.events(after=last_seq):
                            if ev["seq"] > last_seq:
                                last_seq = ev["seq"]
                                desk.handle(ev)
                        desk.now = max(desk.now, f["now"])
                except SpreadError:
                    pass
        elif event["seq"] > last_seq:
            last_seq = event["seq"]
            desk.handle(event)
        desk.flush_pending_price_requests()
        if desk.has_pending_quote():
            desk.send_quotes_only()
        desk.tick_timers(True)
        desk.send(True)
        if time.monotonic() - roster_at > 45:
            roster_at = time.monotonic()
            try:
                desk.supply.update_roster(world.roster())
            except SpreadError:
                pass
        if desk.now // DAY > day:
            try:
                report(WEEKDAYS[day % 7], world.score())
            except SpreadError:
                pass
        if desk.now >= snapshot["endsAt"]:
            desk.finalize_pending_revenue(snapshot["endsAt"])
            return


def run_final(client, world_id=None) -> dict:
    world = client.world(world_id) if world_id else None
    while True:
        try:
            if world is None:
                world = next_final(client)
                print(f"Final world {world.id}.", flush=True)
            play_final(world)
            return world.score()
        except KeyboardInterrupt:
            raise
        except SpreadError as error:
            if error.status == 401:
                raise
            if not isinstance(error, Unreachable) and error.status in (403, 404):
                print(f"spread: {error}. The world is gone or closed; stopping.", file=sys.stderr, flush=True)
                return world.score() if world is not None and error.status == 403 else {}
            print(f"spread: {error}. Rebuilding and continuing in 3 seconds.", file=sys.stderr, flush=True)
            time.sleep(3)
        except Exception:
            print(f"error, rebuilding in 3 seconds:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            time.sleep(3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=8)
    ap.add_argument("--seed")
    ap.add_argument("--board", action="store_true")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--world", help="play this world live from the stream, like the final")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the final score as one JSON line")
    a = ap.parse_args()
    client = Client()
    if a.final or a.world:
        try:
            score = run_final(client, a.world)
        except KeyboardInterrupt:
            sys.exit("Stopped. The final world keeps running without us; start again with --final to rejoin.")
        if score:
            report("End", score)
        return
    if a.board:
        score = play_board(client, a.level)
        report("End", score)
        print(json.dumps({"board": True, **score}), flush=True)
        return
    world = client.create(level=a.level, seed=a.seed)
    if not a.quiet:
        print(f"Practice world {world.id}, level {a.level}.", flush=True)
    try:
        score = play_practice(world, a.level, not a.quiet)
    except BaseException:
        try:
            world.delete()
        except SpreadError:
            pass
        raise
    if a.json:
        print(json.dumps({"seed": a.seed, "world": world.id, **score}), flush=True)
    else:
        report("End", score)


if __name__ == "__main__":
    main()
