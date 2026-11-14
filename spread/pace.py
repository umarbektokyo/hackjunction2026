"""Runs a practice world in real time, like the final: the clock moves by itself whether or not a desk answers.
A desk plays it from the stream with `python bot2.py --world <id>`; kill and restart that desk to test rejoin.

    python pace.py --seed live-1 --minutes 34      # prints the world id, then paces the week over 34 real minutes
    python pace.py --seed live-1 --final-clock     # the final's own clock (API.md): 18 s a weekday hour 06-22, 6 s on
                                                   # Saturday, 9 s on the last Monday, 3 s at night and Sunday; ~34 minutes

The world id is also written to logs/pace-<seed>.id. Ctrl-C deletes the world.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from spread.client import Client, SpreadError, Unreachable

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", required=True)
    ap.add_argument("--level", type=int, default=8)
    ap.add_argument("--minutes", type=float, default=34.0, help="real minutes for the whole week")
    ap.add_argument("--final-clock", action="store_true", help="move the clock like the final (fast nights, slow weekdays)")
    ap.add_argument("--wait", type=float, default=15.0, help="real seconds before the clock starts, for the desk to connect")
    a = ap.parse_args()
    client = Client()
    world = client.create(level=a.level, seed=a.seed, board=False)
    with open(os.path.join(HERE, "logs", f"pace-{a.seed}.id"), "w") as f:
        f.write(world.id)
    snap = world.snapshot()
    start, ends = snap["now"], snap["endsAt"]
    speed = (ends - start) / (a.minutes * 60)
    cum = None
    if a.final_clock:
        def sec_per_hour(m: int) -> float:
            day, hour = m // 1440, m % 1440 // 60
            if day == 7 and 6 <= hour < 22:
                return 9.0
            if day >= 7 or day % 7 == 6 or not 6 <= hour < 22:
                return 3.0
            return 6.0 if day % 7 == 5 else 18.0
        cum, t = [], 0.0
        for m in range(start, ends + 1):
            cum.append(t)
            t += sec_per_hour(m) / 60
        print(f"final clock: {t / 60:.1f} real minutes", flush=True)
    print(f"world {world.id}  minutes {start}..{ends}  speed {speed:.2f} world min/s", flush=True)
    time.sleep(a.wait)
    t0, now, last_print = time.monotonic(), start, start
    try:
        while now < ends:
            elapsed = time.monotonic() - t0
            if cum is not None:
                import bisect
                target = min(ends, start + bisect.bisect_right(cum, elapsed) - 1)
            else:
                target = min(ends, start + int(elapsed * speed))
            if target > now:
                try:
                    now = world.advance(to=target)["now"]
                except Unreachable as error:      # a slow server: try again, never delete the world for it
                    print(f"pace: {error}", flush=True)
                    time.sleep(2)
                    continue
            if now - last_print >= 24 * 60:
                last_print = now
                try:
                    s = world.score()
                except Unreachable:
                    continue
                print(f"minute {now}  margin €{s['marginCents'] / 100:,.0f}  orders {s['wonOrders']}  on time {s['onTimeShare']:.1%}", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        try:
            world.delete()
            print("world deleted", flush=True)
        except SpreadError:
            pass
        raise
    print(json.dumps({"seed": a.seed, "world": world.id, **world.score()}), flush=True)


if __name__ == "__main__":
    main()
