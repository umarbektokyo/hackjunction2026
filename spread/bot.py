"""Evil Club's Spread desk. It builds on the kit's starter (restart, notes, retries) and changes
three decisions:

1. Which options to quote, and at what price: a world-level price multiplier that adapts to a
   target win rate, plus a surcharge that grows with our backlog of cars without a driver
   ("congestion pricing"), so we stop winning cars when drivers can't keep up.
2. Which cars to decline: lanes whose ends have too few drivers living nearby.
3. Driver fees: open higher than the typical fee and rise to a cap by the last safe pickup.

Every idea is a parameter, so `bench.py` can measure each one with and without.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import deque

from spread.client import Client, SpreadError, Unreachable, World
from spread.starter import DAY, HOUR, WAKE_ON, WEEKDAYS, Desk, next_final, report

DEFAULTS = {
    "price_mult": 1.25,       # starting price, times the list price
    "target_win": 0.55,       # win rate the multiplier steers towards
    "adapt_step": 0.01,       # change of the multiplier per quote result
    "mult_min": 1.0, "mult_max": 1.6,
    "same_day": 1.15,         # extra factor on same_day (None-like 0 = don't quote it)
    "next_day": 1.05,
    "backlog_k": 0.02,        # surcharge per car without a driver
    "backlog_free": 10,       # cars without a driver before the surcharge starts
    "min_drivers": 3,         # drivers living within 30 km of pickup needed to quote normally
    "max_minutes": 10_000,    # decline drives longer than this (road minutes)
    "decline_mult": 5.0,      # price factor used to decline
    "fee_open": 1.25,         # opening fee, times the typical fee
    "fee_cap": 1.9,           # fee reached 3 h before lastPickupAt
    "fee_steps": 6,
    "urgent_open": 2.0, "urgent_cap": 3.0,
    "fee_adapt": 0.0,         # step of the adaptive opening fee per booking (0 = fixed fee_open)
    "fee_target": 0.5,        # share of gigs that should book at the opening fee
    "fee_min": 0.3, "fee_max": 1.5,
    "trust_k": 0.0,           # price uplift per on-time order to a dealer (level 8 rule is +1%)
    "trust_cap": 25,
    "min_margin": -1e9,       # decline when price - expected fee is below this (cents)
    "exp_fee": 1.0,           # expected booked fee, times the typical fee, for that check
    "exp_fee_long": 0.0,
    "min_slack": 0,           # decline an option when deadline - now - drive is below this (minutes)
    "loc_k": 0.0,             # surcharge per unbooked car of ours picked up within 30 km
    "loc_free": 3,
    "fee_clock": 0,           # 1 = flat opening fee, then 3 jumps in the last 4 market hours; no night raises
    "climb_h": 4,
    "past_saving": 0,         # 1 = once a car cannot be on time, stop paying rescue fees for it
    "late_flat": 1.1,         # fee for such a car, times the typical fee, +late_step per market day
    "late_step": 0.25,
    "inflight": 0.0,          # weight of quotes awaiting an answer in the local congestion count      # extra expected fee per road hour beyond 2 h, times the typical fee
}


MKT_OPEN, MKT_CLOSE = 7 * 60 + 30, 20 * 60


def _mkt_day(t: int) -> bool:
    return (t // DAY) % 7 < 6          # Monday to Saturday


def mkt_add(t: int, m: int) -> int:
    """`m` minutes after `t`, counting only 07:30-20:00, Monday to Saturday."""
    while m > 0:
        day0, tod = t // DAY * DAY, t % DAY
        if not _mkt_day(t) or tod >= MKT_CLOSE:
            t = day0 + DAY + MKT_OPEN
            continue
        if tod < MKT_OPEN:
            t = day0 + MKT_OPEN
            continue
        step = min(m, day0 + MKT_CLOSE - t)
        t, m = t + step, m - step
    return t


def mkt_back(t: int, m: int) -> int:
    """`m` market minutes before `t`."""
    while m > 0:
        day0, tod = t // DAY * DAY, t % DAY
        if not _mkt_day(t) or tod <= MKT_OPEN:
            t = day0 - DAY + MKT_CLOSE
            continue
        if tod > MKT_CLOSE:
            t = day0 + MKT_CLOSE
            continue
        step = min(m, t - (day0 + MKT_OPEN))
        t, m = t - step, m - step
    return t


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class EvilDesk(Desk):
    def __init__(self, world: World, level: int, now: int, params: dict, world_map: dict, roster: list):
        super().__init__(world, level, now)
        self.p = {**DEFAULTS, **params}
        self.mult = self.p["price_mult"]
        self.fee_open = self.p["fee_open"]
        self.trust: dict[str, int] = {}
        self.pending: dict[str, str] = {}      # request id -> pickup place, while the dealer decides
        self.counted: set[str] = set()
        self.quoted: dict[str, dict] = {}       # request id -> {kind: price}
        self.results = deque(maxlen=60)          # recent wins (1) and losses (0)
        places = {pl["id"]: pl for pl in world_map["places"]}
        self.minutes = {(r["from"], r["to"]): r["minutes"] for r in world_map["roads"]}
        homes: dict[str, int] = {}
        for d in roster:
            homes[d["homePlaceId"]] = homes.get(d["homePlaceId"], 0) + 1
        # drivers who get a notification for a gig starting at each place (home within 30 km)
        self.near = {pid: sum(n for h, n in homes.items() if haversine(places[pid], places[h]) <= 30) for pid in places}
        self.close = {a: {b for b in places if haversine(places[a], places[b]) <= 30} for a in places}

    # ---- quoting -------------------------------------------------------------------------
    def backlog(self) -> int:
        """Orders still waiting for a driver."""
        n = 0
        for oid, o in self.orders.items():
            legs = self.leg_gigs.get(oid, {})
            if any(o["deliveredAt"][i] is None and legs.get(i) not in self.booked for i in range(len(o["legs"]))):
                n += 1
        return n

    def unbooked_near(self, place: str) -> int:
        """Our cars waiting for a driver with a pickup within 30 km of `place`."""
        n, near = 0, self.close.get(place, {place})
        for oid, o in self.orders.items():
            legs = self.leg_gigs.get(oid, {})
            for i, leg in enumerate(o["legs"]):
                if o["deliveredAt"][i] is None and legs.get(i) not in self.booked and leg["pickup"]["placeId"] in near:
                    n += 1
        if self.p["inflight"]:
            pw = (sum(self.results) / len(self.results)) if self.results else self.p["target_win"]
            n += self.p["inflight"] * pw * sum(1 for pl in self.pending.values() if pl in near)
        return n

    def quote(self, request) -> None:
        self.requests[request["id"]] = request
        p = self.p
        surcharge = p["backlog_k"] * max(0, self.backlog() - p["backlog_free"])
        mult = self.mult + surcharge
        self.surcharged = getattr(self, "surcharged", set())
        if surcharge > 0:
            self.surcharged.add(request["id"])
        ends_ok = all(self.near.get(leg["pickup"]["placeId"], 0) >= p["min_drivers"]
                      and self.minutes.get((leg["pickup"]["placeId"], leg["delivery"]["placeId"]), 0) <= p["max_minutes"]
                      for leg in request["legs"])
        if p["loc_k"]:
            here = self.unbooked_near(request["legs"][0]["pickup"]["placeId"])
            loc = p["loc_k"] * max(0, here - p["loc_free"])
            if loc > 0:
                mult += loc
                self.surcharged.add(request["id"])
        mult *= 1 + p["trust_k"] * min(p["trust_cap"], self.trust.get(request["dealerId"], 0))
        drive = sum(self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in request["legs"])
        exp_cost = request["referenceFeeCents"] * (p["exp_fee"] + p["exp_fee_long"] * max(0, drive - 120) / 60)
        prices = {}
        for opt in request["options"]:
            kind_f = {"same_day": p["same_day"], "next_day": p["next_day"]}.get(opt["kind"], 1.0)
            f = mult * kind_f
            slack = opt["deadline"] - max(self.now, request["respondBy"]) - drive
            if (not ends_ok or kind_f == 0 or opt["listPriceCents"] * f - exp_cost < p["min_margin"]
                    or slack < p["min_slack"]):
                f = p["decline_mult"]
            prices[opt["kind"]] = max(1, int(opt["listPriceCents"] * f + 0.5))
        self.quoted[request["id"]] = prices
        if any(prices[o["kind"]] < o["listPriceCents"] * p["decline_mult"] - 1 for o in request["options"]):
            self.pending[request["id"]] = request["legs"][0]["pickup"]["placeId"]
        self.outbox.append({"type": "quote", "requestId": request["id"], "prices": prices})

    def learn(self, won: bool, request_id: str) -> None:
        self.pending.pop(request_id, None)
        prices = self.quoted.get(request_id)
        req = self.requests.get(request_id)
        if not prices or not req or request_id in getattr(self, "surcharged", ()):
            return
        # only quotes that were meant to win teach the multiplier
        if min(prices[o["kind"]] / o["listPriceCents"] for o in req["options"]) >= self.p["decline_mult"] - 1e-6:
            return
        self.results.append(1 if won else 0)
        step = self.p["adapt_step"]
        self.mult += step * (1 - self.p["target_win"]) if won else -step * self.p["target_win"]
        self.mult = min(self.p["mult_max"], max(self.p["mult_min"], self.mult))

    # ---- fees ----------------------------------------------------------------------------
    def fees_for(self, order, cars):
        p = self.p
        ref = self.requests[order["id"]]["referenceFeeCents"] * cars / len(order["legs"])
        if p["past_saving"] and self.now >= order["lastPickupAt"]:
            # It will be late whatever we pay: a modest fee that rises once per market day.
            self.urgent.discard(order["id"])
            return self._steps(ref, [(mkt_add(self.now, 750 * k) if k else self.now, p["late_flat"] + p["late_step"] * k) for k in range(5)])
        if p["fee_clock"]:
            if order["id"] in self.urgent:
                cap = p["urgent_cap"]
                return self._steps(ref, [(self.now, max(self.fee_open, 0.75 * cap)), (self.now + 30, cap)])
            f0, cap = self.fee_open, max(p["fee_cap"], self.fee_open)
            T = order["lastPickupAt"] - 3 * HOUR
            climb = int(p["climb_h"] * HOUR)
            start = max(mkt_add(self.now, 45), mkt_back(T, climb))
            steps = [(self.now, f0)]
            for i in range(3):
                at = mkt_add(start, climb * i // 3)
                if at < T + 2 * HOUR:
                    steps.append((at, f0 + (cap - f0) * (i + 1) / 3))
            return self._steps(ref, steps)
        if order["id"] in self.urgent:
            lo, hi, end = p["urgent_open"], p["urgent_cap"], self.now + 90
        else:
            lo, hi, end = self.fee_open, max(p["fee_cap"], self.fee_open), max(self.now + 60, order["lastPickupAt"] - 3 * HOUR)
        n = max(1, int(p["fee_steps"]))
        span = max(1, end - self.now)
        steps, last = [], 0
        for k in range(n):
            fee = max(last, int(ref * (lo + (hi - lo) * k / max(1, n - 1)) + 0.5), 1)
            steps.append({"at": self.now + int(span * k / n), "feeCents": fee})
            last = fee
        # drop steps that share a minute
        out = []
        for s in steps:
            if out and s["at"] <= out[-1]["at"]:
                out[-1] = s
            else:
                out.append(s)
        return out

    @staticmethod
    def _steps(ref, steps):
        out, last = [], 0
        for at, m in steps:
            fee = max(last, int(ref * m + 0.5), 1)
            if out and at <= out[-1]["at"]:
                out[-1] = {"at": out[-1]["at"], "feeCents": fee}
            else:
                out.append({"at": at, "feeCents": fee})
            last = fee
        return out[:48]

    def handle(self, event) -> None:
        if event["kind"] == "order_won":
            self.learn(True, event["order"]["id"])
        elif event["kind"] == "order_lost":
            self.learn(False, event["requestId"])
        elif event["kind"] == "gig_booked" and self.p["fee_adapt"]:
            post = self.posts.get(event["gigId"])
            order_id = post["stops"][0]["orderId"] if post else None
            if post and order_id not in self.urgent:
                first = event["feeCents"] <= post["schedule"][0]["feeCents"]
                t, step = self.p["fee_target"], self.p["fee_adapt"]
                self.fee_open += -step * (1 - t) if first else step * t
                self.fee_open = min(self.p["fee_max"], max(self.p["fee_min"], self.fee_open))
        super().handle(event)
        if event["kind"] == "delivered":
            o = self.orders.get(event["orderId"])
            if o and o["id"] not in self.counted and all(x is not None for x in o["deliveredAt"]):
                self.counted.add(o["id"])
                d = o["dealerId"]
                if max(o["deliveredAt"]) <= o["deadline"]:
                    self.trust[d] = self.trust.get(d, 0) + 1
                else:
                    self.trust[d] = self.trust.get(d, 0) // 2


WAKE = list(WAKE_ON) + ["order_lost"]


def play_practice(world: World, level: int, params: dict, verbose: bool) -> dict:
    client = world.client
    snapshot = world.snapshot()
    desk = EvilDesk(world, level, snapshot["now"], params, client.map(), world.roster())
    ends_at = snapshot["endsAt"]
    while desk.now < ends_at:
        day, midnight = desk.now // DAY, (desk.now // DAY + 1) * DAY
        actions, desk.outbox = desk.outbox, []
        step = world.advance(until=WAKE, max=min(ends_at, midnight), actions=actions)
        desk.read_results(actions, step["results"])
        desk.now = step["now"]
        for event in step["events"]:
            desk.handle(event)
        if verbose and desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
            print(f"           mult {desk.mult:.3f}  backlog {desk.backlog()}", flush=True)
    return world.score()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=8)
    ap.add_argument("--seed")
    ap.add_argument("--params", default="{}", help="JSON overrides of DEFAULTS")
    ap.add_argument("--board", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the final score as one JSON line")
    a = ap.parse_args()
    params = json.loads(a.params)
    client = Client()
    world = client.create(level=a.level, seed=a.seed, board=a.board)
    try:
        score = play_practice(world, a.level, params, not a.quiet)
    except BaseException:
        if not a.board:
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
