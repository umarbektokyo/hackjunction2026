"""Evil Club's desk, v4: a Python port of source-exp/RoutePulse (the #9 system on the Saturday 00:00 board, TypeScript,
Junction 2026), in rp/. The port must replay their world to the cent on the same seed; compare with rp_bench.sh.

    python bot4.py --seed bench-1                 one practice week, level 8
    python bot4.py --board                        our next ranking run (resumes an unfinished one)
    python bot4.py --final                        our copy of the final (waits until it is set)
    RP_LOG=logs/x.jsonl python bot4.py --seed s   also log every batch of actions, for a diff against the TypeScript run
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

from rp.desk import WAKE_ON, Desk, wire
from rp.planner import DAY

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def log_actions(path, now, stop_at, actions) -> None:
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"now": now, "stopAt": stop_at, "actions": wire(actions)}, separators=(",", ":")) + "\n")


def play_practice(world, level: int, verbose: bool = True, params=None) -> dict:
    client = world.client
    snapshot = world.snapshot()
    now, ends_at = snapshot["now"], snapshot["endsAt"]
    desk = Desk(world, level, now, ends_at, client.map(), world.roster(), params)
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
        desk.tick_timers(False)
        if verbose and desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
    desk.finalize_pending_revenue(ends_at)
    desk.send(False)
    return world.score()


def play_board(client, level: int, params=None) -> dict:
    mine = [w for w in client.worlds() if w["boardRun"] is not None and w["level"] == level and not w["ended"]]
    world = client.world(mine[0]["worldId"]) if mine else client.create(level=level, board=True)
    print(f"Ranking run {world.id}{' (resumed)' if mine else ''}, level {level}.", flush=True)
    while True:
        try:
            return {"world": world.id, **play_practice(world, level, params=params)}
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


def play_final(world, params=None) -> None:
    client = world.client
    history = world.events()
    snapshot = world.snapshot()
    if snapshot["now"] >= snapshot["endsAt"]:
        return
    level = next((w["level"] for w in client.worlds() if w["worldId"] == world.id), 8)
    desk = Desk(world, level, snapshot["now"], snapshot["endsAt"], client.map(), world.roster(), params)
    desk.rejoin(snapshot, history)
    seq0 = history[-1]["seq"] if history else -1
    tail = world.events(after=seq0)
    open_ids = {r["id"] for r in snapshot["openRequests"]}
    for ev in tail:
        if ev["kind"] == "price_request" and ev["request"]["id"] in open_ids:
            continue
        if ev["kind"] == "order_won" and ev["order"]["id"] in desk.orders:
            continue
        desk.handle(ev)
    after = tail[-1]["seq"] if tail else seq0
    desk.tick_timers(True)
    desk.send(True)
    print(f"rejoined at minute {snapshot['now']}: {len(history)} events, {len(desk.orders)} orders", flush=True)
    roster_at = time.monotonic()
    for event in world.stream(after=after, idle=0.6):
        day = desk.now // DAY
        t0 = time.perf_counter()
        if event is None:
            try:
                desk.now = max(desk.now, client.final()["now"])
            except SpreadError:
                pass
        else:
            desk.handle(event)
        if any(a["type"] == "quote" for a in desk.outbox):
            desk.send(True)
        desk.tick_timers(True)
        desk.send(True)
        if event is not None and event["kind"] == "price_request" and (dt := 1000 * (time.perf_counter() - t0)) > 1500:
            print(f"SLOW quote: {dt:.0f} ms", flush=True)
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
            return


def run_final(client, params=None) -> dict:
    world = None
    while True:
        try:
            if world is None:
                world = next_final(client)
                print(f"Final world {world.id}.", flush=True)
            play_final(world, params)
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
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the final score as one JSON line")
    ap.add_argument("--params", default="{}", help="JSON policy overrides: pricing, dispatch and online_learning")
    a = ap.parse_args()
    params = json.loads(a.params)
    allowed = {"target_mult", "late_threshold_mult", "quote_mult", "lane_fit_mult", "cheap_lane_discount", "cheap_lane_cost_cap", "pace_discount", "driver_fee_mult", "offer_fee_mult", "direct_offers", "bundling", "online_learning"}
    unknown = set(params) - allowed
    if unknown:
        ap.error(f"unknown policy parameter(s): {', '.join(sorted(unknown))}")
    bool_params = {"direct_offers", "bundling", "online_learning"}
    if any(not isinstance(v, (int, float)) or isinstance(v, bool)
           or (v < 0 if k in bool_params else v <= 0)
           or (k in bool_params and v not in (0, 1)) for k, v in params.items()):
        ap.error("policy multipliers must be positive numbers; direct_offers, bundling and online_learning must be 0 or 1")
    client = Client()
    if a.final:
        try:
            score = run_final(client, params)
        except KeyboardInterrupt:
            sys.exit("Stopped. The final world keeps running without us; start again with --final to rejoin.")
        if score:
            report("End", score)
        return
    if a.board:
        score = play_board(client, a.level, params)
        report("End", score)
        print(json.dumps({"board": True, **score}), flush=True)
        return
    world = client.create(level=a.level, seed=a.seed)
    if not a.quiet:
        print(f"Practice world {world.id}, level {a.level}.", flush=True)
    try:
        score = play_practice(world, a.level, not a.quiet, params)
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
