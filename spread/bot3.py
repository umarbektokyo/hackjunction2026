"""Evil Club's third desk, written from scratch after reading the public Spread repos of Junction 2026
(expires/spreadbahn-junction, source-exp/RoutePulse, marta-chlebek/hackjunction-2026, KasperiBlomberg/EX-ACTUM-BAHN).
Ideas are theirs where noted; the code is ours. One idea runs through it: every decision is an expected-value
trade-off, with the 90% on-time rule priced in as a cost (lambda, the price of a late order).

Parts, each behind a switch in DEFAULTS so bench.py can measure it with and without:
  1. quote():   price x*list per option that maximises P(win|x) * (price - E[fee] - P(late) * (refund + lambda)).
  2. Market:    competitor level = world level + day offset + lane effects (+ dealer trust, from the rules), learnt online
                by logistic SGD from our wins and losses, only where we offered the dealer's fastest option.
  3. p_late():  slack table + driver-supply model (roster, road minutes) + congestion at the yard + snow.
  4. fees:      opening fee by place and car, fixed steps before lastPickupAt, posted 36 h before the last pickup.
  5. pairs:     a return trip in one gig at 0.75 x the two typical fees.
  6. SLA:       projected late share raises lambda and the margin bar during the week.

    python bot3.py --seed bench-1                      one practice week, level 8
    python bot3.py --board --quiet                     our next ranking run
    python bot3.py --final                             our copy of the final (waits until it is set)
    ./ml_bench.sh 'name|bot3.py|1|{"pairs":0}'        8 seeds with an override
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import time
import traceback

from spread.client import Client, SpreadError, Unreachable, World
from spread.starter import DAY, HOUR, WAKE_ON, WEEKDAYS, Desk, Retry, next_final, report, stops_for, undelivered, without_windows

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("same_day", "next_day", "within_3_days")
WAKE = list(WAKE_ON) + ["order_lost", "gig_booked"]

DEFAULTS = {
    # 1. pricing
    "x_min": 0.90, "x_max": 2.20, "x_step": 0.02,  # price grid, times the list price
    "slope": 10.0,            # P(win) = sigmoid(slope * (log comp - log x))
    "refund": 0.45,           # share of the price lost when late: refund (10-100%) and the dealer's trust
    "lam": 80.0,              # euros: the price of a late order under the 90% rule (expires: 80)
    "bar": 8.0,               # euros of expected margin needed to quote an option at all
    "decline_mult": 4.0,      # a declined option is quoted at this x list
    "max_km": 520,            # decline longer lanes outright
    # 2. competitor model
    "comp0": 1.40, "comp_lo": 1.22, "comp_hi": 1.60,   # level 8 range 1.26-1.54 x list, with day factors around it
    "lr_world": 0.02, "lr_day": 0.03, "lr_lane": 0.03, "lane_decay": 0.002,
    "day_lo": -0.25, "day_hi": 0.15,   # a day's offset: the price war is -20%, day factors a few percent
    "short_hop": 0.13,        # competitor lift on lanes under 48 km (RoutePulse: fixed overhead)
    "trust": 1,               # dealer trust from the rules: +1% accepted price per on-time order, up to 25
    # 3. lateness
    "pl_scale": 0.6,          # calibration of the modelled P(late)
    "slack_tab": [[4, 0.60], [8, 0.30], [16, 0.12], [30, 0.06], [1e9, 0.03]],   # slack hours -> P(late)
    "sup_b": [4.23, -0.816, -0.469, -0.425],   # logit = b0 + b1 log1p(S_pick) + b2 log1p(S_del) + b3 km/100
    "sup_base": 0.045,        # the supply model's typical P(late), already in the slack table
    "sup_fee": 0.6,           # expected-fee uplift per unit of extra supply risk
    "cap_per_supply": 0.12, "cap_min": 3.0, "cong_late": 0.35,   # yard congestion: cars per day per unit of supply
    "snow_late": 0.15, "snow_fee": 0.15,
    # 4. fees
    "fee_open": 0.85,         # opening fee, times the typical fee, before the uplifts below
    "fee_place": 1,           # 1 = uplifts by driver pools, route, private, trade-in, experienced, evening
    "fee_steps": [[24, 1.05], [16, 1.25], [10, 1.55], [6, 2.0]],   # (hours before lastPickupAt, x typical)
    "hold_hours": 36,         # post an order only this many hours before its last pickup
    "raise0": 1.15,           # prior: booked fee / opening fee
    "urgent": [[0, 2.0], [30, 2.5], [60, 3.0]],   # after the deadline warning: (minutes from now, x typical)
    "past": [[0, 1.2], [720, 1.5], [1440, 1.9]],  # once the car cannot be on time: modest fees, no rescue
    # 5. pairs
    "pairs": 1, "pair_alpha": 0.75, "pair_hop": 45, "pair_return": 45, "pair_chain_alpha": 0.0,   # 0 = return trips only
    # 6. SLA controller
    "sla_target": 0.94, "sla_gain": 2.0, "sla_prior_n": 120,
}


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z > -30 else 0.0


def haversine(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def step_lookup(table, x: float) -> float:
    for limit, value in table:
        if x < limit:
            return value
    return table[-1][1]


def daytime(t: int) -> int:
    """A fee step at night is wasted: move it to 07:00."""
    tod = t % DAY
    if tod >= 21 * HOUR:
        return t - tod + DAY + 7 * HOUR
    if tod < 7 * HOUR:
        return t - tod + 7 * HOUR
    return t


class Market:
    """The competitor's price level, as log(price / list): a world level, today's offset, and an effect per pickup
    and delivery place. Learnt by one SGD step of the logistic likelihood on each resolved quote."""

    def __init__(self, p: dict):
        self.p = p
        self.world = math.log(p["comp0"])
        self.day_off, self.day = 0.0, -1
        self.pick: dict[str, float] = {}
        self.deliv: dict[str, float] = {}
        self.n_obs = 0

    def new_day(self, day: int) -> None:
        if day != self.day:
            self.day, self.day_off = day, 0.0      # the competitor's day factor is new each day; a price war lasts one day

    def level(self, pick: str, deliv: str, km: float) -> float:
        hop = self.p["short_hop"] * min(1.0, (48 - km) / 34) if km < 48 else 0.0
        return self.world + self.day_off + self.pick.get(pick, 0.0) + self.deliv.get(deliv, 0.0) + hop

    def p_win(self, log_x: float, level: float) -> float:
        return sigmoid(self.p["slope"] * (level - log_x))

    def observe(self, won: bool, log_x: float, level: float, pick: str, deliv: str) -> None:
        r = (1.0 if won else 0.0) - self.p_win(log_x, level)
        self.world = min(math.log(self.p["comp_hi"]), max(math.log(self.p["comp_lo"]), self.world + self.p["lr_world"] * r))
        self.day_off = max(self.p["day_lo"], min(self.p["day_hi"], self.day_off + self.p["lr_day"] * r))
        for d, k in ((self.pick, pick), (self.deliv, deliv)):
            v = d.get(k, 0.0) * (1 - self.p["lane_decay"]) + self.p["lr_lane"] * r
            d[k] = max(-0.3, min(0.3, v))
        self.n_obs += 1

    def mean(self) -> float:
        return math.exp(self.world + self.day_off)


class Desk3(Desk):
    def __init__(self, world: World, level: int, now: int, params: dict, world_map: dict, roster: list):
        super().__init__(world, level, now)
        self.p = {**DEFAULTS, **params}
        p = self.p
        self.places = {pl["id"]: pl for pl in world_map["places"]}
        self.minutes = {(r["from"], r["to"]): r["minutes"] for r in world_map["roads"]}
        self.km = {(r["from"], r["to"]): r["km"] for r in world_map["roads"]}
        self.set_roster(roster)
        self.market = Market(p)
        self.trust: dict[str, int] = {}
        self.counted: set[str] = set()
        self.quoted: dict[str, tuple] = {}     # request id -> (log x of the fastest quoted option, level, pick, deliv)
        self.pending: dict[str, tuple] = {}    # request id -> (load key, weight) while the dealer decides
        self.load: dict[tuple, float] = {}     # (pickup place, day) -> cars we move from there that day
        self.raise_sum, self.raise_n = p["raise0"] * 5, 5   # booked fee / opening fee, with a prior
        self.opening: dict[str, int] = {}      # gig id -> opening fee
        self.timers: list[tuple[int, str]] = []   # (post at, order id): orders held before posting
        self.snow: list[tuple[int, int, set]] = []
        self.flu_day = -1
        self.stats = {"quoted": 0, "declined": 0, "d_km": 0, "d_bar": 0, "pairs": 0, "pair_refused": 0, "m0_sum": 0.0, "m0_n": 0}

    # ---- geography and drivers --------------------------------------------------------------
    def set_roster(self, roster: list) -> None:
        homes: dict[str, int] = {}
        exp_homes: dict[str, int] = {}
        for d in roster:
            homes[d["homePlaceId"]] = homes.get(d["homePlaceId"], 0) + 1
            if d["rating"] >= 4.8 and d["completedGigs"] >= 50:
                exp_homes[d["homePlaceId"]] = exp_homes.get(d["homePlaceId"], 0) + 1
        # supply index: resident drivers around a place, weighted by road time (expires' S)
        self.supply = {pid: sum(n * math.exp(-self.minutes.get((h, pid), 600) / 60) for h, n in homes.items()) for pid in self.places}
        # drivers whose app notifies them of a gig starting at a place: home within 30 km, straight line
        self.near = {pid: sum(n for h, n in homes.items() if haversine(self.places[pid], self.places[h]) <= 30) for pid in self.places}
        self.near_exp = {pid: sum(n for h, n in exp_homes.items() if haversine(self.places[pid], self.places[h]) <= 30) for pid in self.places}

    def drive(self, legs) -> tuple[int, float]:
        mins = sum(self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in legs)
        kms = sum(self.km.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in legs)
        return mins, kms

    def snowed(self, place: str, start: int, end: int) -> bool:
        return any(place in places and f <= end and t >= start for f, t, places in self.snow)

    # ---- lateness ---------------------------------------------------------------------------
    def supply_risk(self, legs, km: float) -> float:
        """Extra P(late) from thin driver supply at the ends of the lane, above the model's typical value."""
        b = self.p["sup_b"]
        risk = 0.0
        for l in legs:
            z = b[0] + b[1] * math.log1p(self.supply[l["pickup"]["placeId"]]) + b[2] * math.log1p(self.supply[l["delivery"]["placeId"]]) + b[3] * km / 100
            risk = max(risk, sigmoid(z))
        return max(0.0, risk - self.p["sup_base"])

    def congestion(self, legs, day: int) -> float:
        key = (legs[0]["pickup"]["placeId"], day)
        cap = max(self.p["cap_min"], self.p["cap_per_supply"] * self.supply[key[0]])
        return self.p["cong_late"] * max(0.0, self.load.get(key, 0.0) / cap - 1)

    def p_late(self, request, deadline: int, drive_min: int, km: float) -> tuple[float, float]:
        """(P(late), supply risk) for one option."""
        legs = request["legs"]
        start = max(self.now, request["respondBy"], min(l["pickup"]["window"]["from"] for l in legs))
        charge = 40 if any(l["car"]["electric"] and (l["car"]["chargePercent"] or 100) < 30 for l in legs) and km > 200 else 0
        slack_h = (deadline - start - drive_min - charge) / 60
        if slack_h < 0.5:
            return 0.95, 0.0
        sup = self.supply_risk(legs, km)
        pl = step_lookup(self.p["slack_tab"], slack_h) + sup + self.congestion(legs, start // DAY)
        if any(self.snowed(l["pickup"]["placeId"], start, deadline) or self.snowed(l["delivery"]["placeId"], start, deadline) for l in legs):
            pl += self.p["snow_late"]
        return min(0.95, self.p["pl_scale"] * pl), sup

    def sla_pressure(self) -> float:
        """Projected late share above the allowance: late orders plus a share of the orders now at risk."""
        n = max(len(self.orders), self.p["sla_prior_n"])
        late = risk = 0.0
        held = {oid for _, oid in self.timers}
        for o in self.orders.values():
            if o["status"] == "cancelled":
                continue
            done = all(t is not None for t in o["deliveredAt"])
            if any(t is not None and t > o["deadline"] for t in o["deliveredAt"]) or (not done and self.now > o["deadline"]):
                late += 1
            elif not done and o["id"] not in held and not any(g in self.booked for g in self.gigs_of(o["id"])):
                left_h = (o["lastPickupAt"] - self.now) / 60
                risk += 0.8 if o["id"] in self.urgent else 0.3 if left_h < 4 else 0.0
        return max(0.0, (late + risk) / n - (1 - self.p["sla_target"]))

    # ---- fees --------------------------------------------------------------------------------
    def open_mult(self, legs, now: int, experienced: bool, charging: bool, plates: bool = False) -> float:
        """The opening fee, times the typical fee, by place and car (uplifts after RoutePulse's fee model)."""
        p = self.p
        m = p["fee_open"]
        if not p["fee_place"]:
            return m
        pick, deliv = legs[0]["pickup"]["placeId"], legs[-1]["delivery"]["placeId"]
        q = self.near_exp[pick] if experienced else self.near[pick]
        d_pool = self.near[deliv]
        same = haversine(self.places[pick], self.places[deliv]) <= 30
        _, km = self.drive(legs)
        private_p = any(l["pickup"]["privateAddress"] for l in legs)
        private_d = any(l["delivery"]["privateAddress"] for l in legs)
        trade_in = len(legs) > 1
        extras = private_p or private_d or trade_in or experienced or charging or plates
        if d_pool >= 95 and q >= 40 and not extras and km <= 220:
            m -= 0.04
        if d_pool <= 5 and not same:
            m += 0.08
        elif d_pool <= 14 and not same:
            m += 0.05
        if q == 0:
            m += 0.12
        elif q <= 5:
            m += 0.07
        elif q <= 15:
            m += 0.03
        if km > 260:
            m += 0.07
        if km > 400:
            m += 0.06
        if private_p and not trade_in:
            m += 0.14
        if private_d and not trade_in:
            m += 0.16
        if trade_in:
            m += 0.14
        if experienced:
            m += 0.18
        if charging:
            m += 0.08
        if plates:
            m += 0.04
        wd, tod = (now // DAY) % 7, now % DAY
        if wd == 5 or tod >= 17 * HOUR:
            m += 0.06
        start = min(l["pickup"]["window"]["from"] for l in legs)
        if any(self.snowed(l["pickup"]["placeId"], start, start + DAY) for l in legs):
            m += p["snow_fee"]
        return m

    def schedule(self, ref: float, m0: float, last_pickup: int) -> list[dict]:
        steps = [(self.now, m0)]
        for hours, mult in self.p["fee_steps"]:
            at = daytime(last_pickup - int(hours * HOUR))
            if at <= self.now:
                steps[0] = (self.now, max(steps[0][1], mult))
            else:
                steps.append((at, mult))
        return self._steps(ref, steps)

    @staticmethod
    def _steps(ref: float, steps) -> list[dict]:
        out, last = [], 0
        for at, m in sorted(steps):
            fee = max(last, int(ref * m + 0.5), 1)
            if out and at <= out[-1]["at"]:
                out[-1] = {"at": out[-1]["at"], "feeCents": fee}
            elif fee > last or not out:
                out.append({"at": int(at), "feeCents": fee})
            last = fee
        return out[:48]

    def fees_for(self, order, cars: int) -> list[dict]:
        ref = self.requests[order["id"]]["referenceFeeCents"] * cars / len(order["legs"])
        if self.now >= order["lastPickupAt"]:
            self.urgent.discard(order["id"])
            return self._steps(ref, [(daytime(self.now + m), x) for m, x in self.p["past"]])
        if order["id"] in self.urgent:
            return self._steps(ref, [(self.now + m, x) for m, x in self.p["urgent"]])
        legs = undelivered(order) or list(range(len(order["legs"])))
        exp = any(order["legs"][i]["car"]["premium"] for i in legs)
        charge = any(order["legs"][i]["car"]["electric"] and (order["legs"][i]["car"]["chargePercent"] or 100) < 30 for i in legs)
        m0 = self.open_mult([order["legs"][i] for i in legs], self.now, exp, charge)
        self.stats["m0_sum"] += m0
        self.stats["m0_n"] += 1
        return self.schedule(ref, m0, order["lastPickupAt"])

    def raise_ratio(self) -> float:
        return self.raise_sum / self.raise_n

    # ---- quoting ------------------------------------------------------------------------------
    def quote(self, request) -> None:
        self.requests[request["id"]] = request
        p = self.p
        legs = request["legs"]
        pick, deliv = legs[0]["pickup"]["placeId"], legs[-1]["delivery"]["placeId"]
        drive_min, km = self.drive(legs)
        decline = {o["kind"]: int(o["listPriceCents"] * p["decline_mult"]) for o in request["options"]}
        if km > p["max_km"]:
            self.stats["declined"] += 1
            self.stats["d_km"] += 1
            self.outbox.append({"type": "quote", "requestId": request["id"], "prices": decline})
            return
        self.market.new_day(self.now // DAY)
        pressure = self.sla_pressure()
        lam = p["lam"] * (1 + p["sla_gain"] * pressure * 10)
        bar = p["bar"] * (1 + p["sla_gain"] * pressure * 10)
        boost = math.log(1 + 0.01 * min(25, self.trust.get(request["dealerId"], 0))) if p["trust"] and self.level >= 8 else 0.0
        level = self.market.level(pick, deliv, km) + boost
        ref = request["referenceFeeCents"] / 100
        exp = any(l["car"]["premium"] for l in legs)
        charge = any(l["car"]["electric"] and (l["car"]["chargePercent"] or 100) < 30 for l in legs) and km > 200
        m0 = self.open_mult(legs, max(self.now, min(l["pickup"]["window"]["from"] for l in legs)), exp, charge)
        prices, best_lx = dict(decline), None
        xs = [p["x_min"] + i * p["x_step"] for i in range(int((p["x_max"] - p["x_min"]) / p["x_step"]) + 1)]
        for o in request["options"]:
            lst = o["listPriceCents"] / 100
            pl, sup = self.p_late(request, o["deadline"], drive_min, km)
            fee = ref * m0 * self.raise_ratio() * (1 + p["sup_fee"] * sup) * (1.1 if request.get("note") else 1.0)
            best, best_x, best_m = -1e9, None, 0.0
            for x in xs:
                win = self.market.p_win(math.log(x), level)
                margin = x * lst * (1 - pl * p["refund"]) - fee - pl * lam
                if margin * win > best:
                    best, best_x, best_m = margin * win, x, margin
            if best_x is not None and best_m >= bar:
                prices[o["kind"]] = int(lst * best_x * 100)
                lx = math.log(best_x)
                best_lx = lx if best_lx is None else min(best_lx, lx)
        if best_lx is None:
            self.stats["declined"] += 1
            self.stats["d_bar"] += 1
        else:
            self.stats["quoted"] += 1
            key = (pick, max(self.now, min(l["pickup"]["window"]["from"] for l in legs)) // DAY)
            w = 0.6 * len(legs)
            self.pending[request["id"]] = (key, w)
            self.load[key] = self.load.get(key, 0.0) + w
            fastest = request["options"][0]
            if prices[fastest["kind"]] < fastest["listPriceCents"] * 3:
                # learn the competitor only where we offered the fastest option: a dealer that wants speed
                # and does not get it buys from the competitor at any price, which would sink the estimate
                self.quoted[request["id"]] = (math.log(prices[fastest["kind"]] / fastest["listPriceCents"]), level, pick, deliv)
        self.outbox.append({"type": "quote", "requestId": request["id"], "prices": prices})

    def resolve(self, request_id: str, won: bool) -> None:
        key_w = self.pending.pop(request_id, None)
        if key_w:
            key, w = key_w
            self.load[key] = self.load.get(key, 0.0) - w + (len(self.requests[request_id]["legs"]) if won else 0.0)
        q = self.quoted.pop(request_id, None)
        if q:
            lx, level, pick, deliv = q
            self.market.observe(won, lx, level, pick, deliv)

    # ---- orders, timers, pairs -----------------------------------------------------------------
    def win(self, order) -> None:
        if order["id"] not in self.requests or order["id"] in self.orders:
            return
        self.orders[order["id"]] = order
        post_at = order["lastPickupAt"] - int(self.p["hold_hours"] * HOUR)
        if post_at > self.now + 30:
            self.timers.append((post_at, order["id"]))
        else:
            self.post(order, undelivered(order))

    def held(self) -> set[str]:
        return {oid for _, oid in self.timers}

    def next_timer(self) -> int:
        return min((t for t, _ in self.timers), default=10 ** 9)

    def tick(self) -> None:
        due = [x for x in self.timers if x[0] <= self.now]
        if due:
            self.timers = [x for x in self.timers if x[0] > self.now]
            for _, oid in due:
                o = self.orders.get(oid)
                if o is not None and o["status"] == "waiting" and not self.gigs_of(oid):
                    self.post(o, undelivered(o))

    def pairable(self, o) -> bool:
        if len(o["legs"]) != 1 or o["deliveredAt"][0] is not None or o["id"] in self.urgent:
            return False
        leg = o["legs"][0]
        return not (leg["pickup"]["privateAddress"] or leg["delivery"]["privateAddress"]) and not leg["car"]["premium"]

    def pair_plan(self, x, y):
        """(score, alpha) when one driver can take x then y on time, by road minutes with buffers."""
        X, Y = x["legs"][0], y["legs"][0]
        xp, xd, yp, yd = X["pickup"]["placeId"], X["delivery"]["placeId"], Y["pickup"]["placeId"], Y["delivery"]["placeId"]
        hop = self.minutes.get((xd, yp), 10 ** 6)
        if hop > self.p["pair_hop"]:
            return None
        xdrive, ydrive = self.minutes[(xp, xd)], self.minutes[(yp, yd)]
        if xdrive + hop + ydrive > 12 * HOUR - 30:
            return None
        start = max(self.now + 120, X["pickup"]["window"]["from"])
        if start > x["lastPickupAt"] - 60:
            return None
        xdel = start + xdrive
        if xdel > x["deadline"] - 60:
            return None
        ypick = max(xdel + hop, Y["pickup"]["window"]["from"])
        if ypick > y["lastPickupAt"] - 60 or ypick + ydrive > y["deadline"] - 60:
            return None
        back = self.minutes.get((yd, xp), 10 ** 6)
        if back <= self.p["pair_return"]:
            return (back + hop, self.p["pair_alpha"])
        if self.p["pair_chain_alpha"]:
            return (back + hop + 1000, self.p["pair_chain_alpha"])
        return None

    def find_partner(self, a):
        best, held = None, self.held()
        for b in self.orders.values():
            if b["id"] == a["id"] or not self.pairable(b):
                continue
            gigs = self.gigs_of(b["id"])
            if gigs and (any(g in self.booked for g in gigs) or any(len(self.posts.get(g, {}).get("stops", [])) != 2 for g in gigs)):
                continue   # booked, or already in a pair
            if not gigs and b["id"] not in held and b["status"] != "waiting":
                continue
            for x, y in ((a, b), (b, a)):
                plan = self.pair_plan(x, y)
                if plan and (best is None or plan[0] < best[0]):
                    best = (plan[0], x, y, plan[1])
        return None if best is None else best[1:]

    def post(self, order, legs, retry: Retry = Retry()) -> None:
        if self.p["pairs"] and len(legs) == 1 and retry == Retry() and self.pairable(order):
            partner = self.find_partner(order)
            if partner:
                self.post_pair(*partner)
                return
        super().post(order, legs, retry)

    def post_pair(self, x, y, alpha: float) -> None:
        ids = {x["id"], y["id"]}
        # a single post of either order still in the outbox must not go out beside the pair
        self.outbox = [a for a in self.outbox if not (a["type"] == "post" and any(s["orderId"] in ids for s in a["stops"]))]
        for o in (x, y):   # take an open single gig of either order out of the app first
            for g in self.gigs_of(o["id"]):
                self.outbox.append({"type": "withdraw", "gigId": g})
            self.leg_gigs.pop(o["id"], None)
        self.timers = [t for t in self.timers if t[1] not in (x["id"], y["id"])]
        stops = []
        for o in (x, y):
            stops += without_windows(stops_for(o, [0], self.requests[o["id"]]["note"], Retry()), self.now)
        ref = alpha * (self.requests[x["id"]]["referenceFeeCents"] + self.requests[y["id"]]["referenceFeeCents"])
        legs = [x["legs"][0], y["legs"][0]]
        m0 = self.open_mult(legs, self.now, False, any(l["car"]["electric"] and (l["car"]["chargePercent"] or 100) < 30 for l in legs))
        sched = self.schedule(ref, m0, min(x["lastPickupAt"], y["lastPickupAt"]))
        self.outbox.append({"type": "post", "stops": stops, "audience": {"experienced": False, "manualLicence": False}, "schedule": sched})
        self.send()
        if not self.gigs_of(x["id"]):
            self.stats["pair_refused"] += 1
            for o in (x, y):
                super().post(o, [0])
        else:
            self.stats["pairs"] += 1

    def partners_of(self, gig_ids: list[str], order_id: str) -> list:
        """The other orders whose undelivered legs ride in these gigs."""
        others = []
        for g in gig_ids:
            for s in self.posts.get(g, {}).get("stops", []):
                if s["orderId"] != order_id and s["orderId"] in self.orders and s["orderId"] not in others:
                    others.append(s["orderId"])
        return others

    def withdraw(self, order_id: str) -> bool:
        gigs = self.gigs_of(order_id)
        others = self.partners_of(gigs, order_id)
        ok = super().withdraw(order_id)
        if ok:
            for oid in others:   # the partner lost its gig with the withdrawn pair: post it again on its own
                self.leg_gigs.pop(oid, None)
                o = self.orders[oid]
                super().post(o, undelivered(o))
        return ok

    def repost(self, gig_id: str) -> None:
        action = self.posts.get(gig_id)
        if action and len({s["orderId"] for s in action["stops"]}) > 1:
            for oid in {s["orderId"] for s in action["stops"]}:
                if self.leg_gigs.get(oid, {}) and gig_id in self.leg_gigs[oid].values():
                    self.leg_gigs.pop(oid, None)
                    o = self.orders.get(oid)
                    if o is not None:
                        super().post(o, undelivered(o))
            return
        super().repost(gig_id)

    def send_post_of(self, order_id: str) -> None:
        if any(a["type"] == "post" and any(s["orderId"] == order_id for s in a["stops"]) for a in self.outbox):
            self.send()

    # ---- events -------------------------------------------------------------------------------
    def handle(self, event) -> None:
        k = event["kind"]
        if k == "order_won":
            self.resolve(event["order"]["id"], True)
        elif k == "order_lost":
            self.resolve(event["requestId"], False)
        elif k == "order_cancelled":
            for g in event.get("gigs", []):
                if g.get("status") == "withdrawn":
                    for oid in self.partners_of([g["gigId"]], event["orderId"]):
                        self.leg_gigs.pop(oid, None)
                        super().post(self.orders[oid], undelivered(self.orders[oid]))
            self.timers = [t for t in self.timers if t[1] != event["orderId"]]
        elif k == "gig_booked":
            op = self.opening.get(event["gigId"])
            if op:
                self.raise_sum += event["feeCents"] / op
                self.raise_n += 1
        elif k == "forecast":
            self.snow.append((event["from"], event["to"], set(event["placeIds"])))
        super().handle(event)
        if k == "delivered":
            o = self.orders.get(event["orderId"])
            if o and o["id"] not in self.counted and all(x is not None for x in o["deliveredAt"]):
                self.counted.add(o["id"])
                d = o["dealerId"]
                self.trust[d] = min(25, self.trust.get(d, 0) + 1) if max(o["deliveredAt"]) <= o["deadline"] else self.trust.get(d, 0) // 2

    def read_results(self, actions, results) -> None:
        super().read_results(actions, results)
        for action, result in zip(actions, results):
            if action["type"] == "post" and result.get("ok") is True:
                self.opening[result["id"]] = action["schedule"][0]["feeCents"]

    def summary(self) -> dict:
        s = self.stats
        return {"quoted": s["quoted"], "declined": s["declined"], "d_km": s["d_km"], "d_bar": s["d_bar"], "pairs": s["pairs"],
                "pair_refused": s["pair_refused"], "mean_m0": round(s["m0_sum"] / max(1, s["m0_n"]), 3),
                "raise_ratio": round(self.raise_ratio(), 3), "comp": round(self.market.mean(), 3), "obs": self.market.n_obs}


# ---- live play: state file, quotes first, timing -------------------------------------------------
STATE_KEYS = ["trust", "counted", "quoted", "pending", "load", "raise_sum", "raise_n", "opening", "timers", "snow", "stats", "market"]


class LiveDesk(Desk3):
    def __init__(self, *a, state_path: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.state_path, self.saved_at = state_path, 0.0
        self.errors, self.rejected = 0, {}
        self.send_ms: list[float] = []

    def read_results(self, actions, results) -> None:
        super().read_results(actions, results)
        for action, result in zip(actions, results):
            if result.get("ok") is not True:
                n = self.rejected.get(action["type"], 0)
                self.rejected[action["type"]] = n + 1
                if n < 5:
                    print(f"rejected {action['type']}: {json.dumps(result)[:200]}", flush=True)

    def save_state(self, force: bool = False) -> None:
        if not self.state_path or (not force and time.monotonic() - self.saved_at < 5):
            return
        self.saved_at = time.monotonic()
        tmp = self.state_path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({k: getattr(self, k) for k in STATE_KEYS}, f)
        os.replace(tmp, self.state_path)

    def load_state(self) -> bool:
        if not self.state_path or not os.path.exists(self.state_path):
            return False
        try:
            with open(self.state_path, "rb") as f:
                data = pickle.load(f)
        except Exception as error:
            print(f"state file unreadable ({error}); rebuilding from events", flush=True)
            return False
        for k, v in data.items():
            setattr(self, k, v)
        return True

    def replay(self, snapshot, history) -> None:
        """Without a state file: dealer trust from the delivered orders, the raise ratio from the bookings."""
        requests = {e["request"]["id"]: e["request"] for e in history if e["kind"] == "price_request"}
        done = [o for o in snapshot["orders"] if o["id"] in requests and o["deliveredAt"] and all(x is not None for x in o["deliveredAt"])]
        for o in sorted(done, key=lambda o: max(o["deliveredAt"])):
            self.counted.add(o["id"])
            d = o["dealerId"]
            self.trust[d] = min(25, self.trust.get(d, 0) + 1) if max(o["deliveredAt"]) <= o["deadline"] else self.trust.get(d, 0) // 2
        opening = {g["id"]: g["schedule"][0]["feeCents"] for g in snapshot["gigs"] if g.get("schedule")}
        for e in history:
            if e["kind"] == "gig_booked" and e["gigId"] in opening:
                self.raise_sum += e["feeCents"] / max(1, opening[e["gigId"]])
                self.raise_n += 1
            elif e["kind"] == "forecast":
                self.snow.append((e["from"], e["to"], set(e["placeIds"])))

    def rejoin(self, snapshot, history) -> None:
        if self.load_state():
            print("learned state restored from " + str(self.state_path), flush=True)
        else:
            self.replay(snapshot, history)
        super().rejoin(snapshot, history)

    def send(self) -> None:
        if not self.outbox:
            return
        quotes = [a for a in self.outbox if a["type"] == "quote"]
        rest = [a for a in self.outbox if a["type"] != "quote"]
        t0 = time.perf_counter()
        try:
            for batch in (quotes, rest):
                if batch:
                    self.outbox = batch
                    super().send()
        finally:
            self.outbox = []
            self.send_ms.append(1000 * (time.perf_counter() - t0))


def pct(xs, q):
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(q / 100 * len(s)))]


def play_practice(world: World, level: int, params: dict, verbose: bool) -> dict:
    client = world.client
    snapshot = world.snapshot()
    desk = Desk3(world, level, snapshot["now"], params, client.map(), world.roster())
    ends_at = snapshot["endsAt"]
    while desk.now < ends_at:
        day, midnight = desk.now // DAY, (desk.now // DAY + 1) * DAY
        desk.tick()
        cap = min(ends_at, midnight, max(desk.now + 1, desk.next_timer()))
        desk.outbox.sort(key=lambda a: a["type"] != "quote")
        actions, desk.outbox = desk.outbox, []
        step = world.advance(until=WAKE, max=cap, actions=actions)
        desk.read_results(actions, step["results"])
        desk.now = step["now"]
        for event in step["events"]:
            desk.handle(event)
        if verbose and desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
            print(f"           {desk.summary()}", flush=True)
    score = world.score()
    score["bot3"] = desk.summary()
    return score


def play_board(client: Client, world: World, params: dict) -> dict:
    """A ranking run stepped with advance; after a lost connection or an error it rebuilds from the server and goes on."""
    state = os.path.join(HERE, "logs", f"live-state-{world.id}.pkl")
    failures = 0
    while True:
        try:
            history = world.events()
            snapshot = world.snapshot()
            ends_at = snapshot["endsAt"]
            if snapshot["now"] >= ends_at:
                return world.score()
            desk = LiveDesk(world, 8, snapshot["now"], params, client.map(), world.roster(), state_path=state)
            desk.rejoin(snapshot, history)
            world._last_seq = history[-1]["seq"] if history else -1
            if failures:
                print(f"rejoined at minute {snapshot['now']} after error #{failures}", flush=True)
            while desk.now < ends_at:
                day, midnight = desk.now // DAY, (desk.now // DAY + 1) * DAY
                desk.tick()
                cap = min(ends_at, midnight, max(desk.now + 1, desk.next_timer()))
                desk.outbox.sort(key=lambda a: a["type"] != "quote")
                actions, desk.outbox = desk.outbox, []
                step = world.advance(until=WAKE, max=cap, actions=actions)
                desk.read_results(actions, step["results"])
                desk.now = step["now"]
                for event in step["events"]:
                    desk.handle(event)
                desk.save_state()
                if desk.now // DAY > day:
                    report(WEEKDAYS[day % 7], world.score())
                    print(f"           {desk.summary()}", flush=True)
            score = world.score()
            score["bot3"] = desk.summary()
            return score
        except KeyboardInterrupt:
            raise
        except Exception as error:
            failures += 1
            print(f"error #{failures} ({error!r}); rebuilding in 5 seconds", file=sys.stderr, flush=True)
            time.sleep(5)


def play_live(world: World, params: dict, clock, state_path: str | None, use_state: bool = True) -> dict:
    """The final: rebuilds the books from the snapshot and the events, then answers the stream as it comes."""
    client = world.client
    t_start = time.perf_counter()
    history = world.events()
    snapshot = world.snapshot()
    if snapshot["now"] >= snapshot["endsAt"]:
        return world.score()
    level = next((w["level"] for w in client.worlds() if w["worldId"] == world.id), 8)
    if not use_state and state_path and os.path.exists(state_path):
        os.remove(state_path)
    desk = LiveDesk(world, level, snapshot["now"], params, client.map(), world.roster(), state_path=state_path)
    desk.rejoin(snapshot, history)
    desk.send()
    ends_at = snapshot["endsAt"]
    print(f"rejoined at minute {snapshot['now']} with {len(history)} events, {len(desk.orders)} orders, "
          f"{len(snapshot['openRequests'])} open requests in {time.perf_counter() - t_start:.2f} s", flush=True)
    q_ms: list[float] = []
    for event in world.stream(after=history[-1]["seq"] if history else -1, idle=1.0):
        day = desk.now // DAY
        t0 = time.perf_counter()
        try:
            if event is None:
                desk.now = max(desk.now, clock())
            else:
                desk.now = max(desk.now, event["at"])
                desk.handle(event)
            desk.tick()
        except Exception:
            desk.errors += 1
            print(f"error handling {event and event['kind']}:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        try:
            desk.send()
        except SpreadError as error:
            if isinstance(error, Unreachable):
                raise
            desk.errors += 1
            print(f"send failed: {error}", file=sys.stderr, flush=True)
        if event is not None and event["kind"] == "price_request":
            dt = 1000 * (time.perf_counter() - t0)
            q_ms.append(dt)
            if dt > 1500:
                print(f"SLOW quote: {dt:.0f} ms", flush=True)
        desk.save_state()
        if desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
            print(f"           {desk.summary()}  quote+send ms p50 {pct(q_ms, 50):.0f} p99 {pct(q_ms, 99):.0f}  "
                  f"errors {desk.errors}  rejected {desk.rejected}", flush=True)
        if desk.now >= ends_at:
            break
    desk.save_state(force=True)
    score = world.score()
    score["live"] = {"quote_ms_p50": round(pct(q_ms, 50), 1), "quote_ms_p99": round(pct(q_ms, 99), 1), "errors": desk.errors,
                     "rejected": desk.rejected, **desk.summary()}
    return score


def run_live(client: Client, params: dict, world_id: str | None) -> dict:
    world, failures = None, 0
    while True:
        try:
            if world is None:
                world = client.world(world_id) if world_id else next_final(client)
                print(f"{'Final' if not world_id else 'Live'} world {world.id}.", flush=True)
            clock = (lambda: client.final()["now"]) if not world_id else (lambda: world.snapshot()["now"])
            state = os.path.join(HERE, "logs", f"live-state-{world.id}.pkl")
            return play_live(world, params, clock, state, use_state=failures < 3)
        except KeyboardInterrupt:
            raise
        except SpreadError as error:
            if not isinstance(error, Unreachable) and error.status in (403, 404):
                print(f"spread: {error}. The world is gone or closed; stopping.", file=sys.stderr, flush=True)
                return world.score() if world is not None and error.status == 403 else {"marginCents": 0, "revenueCents": 0, "wonOrders": 0,
                        "onTimeShare": 0.0, "undeliveredShare": 0.0, "ranked": False}
            print(f"spread: {error}. Trying again in 5 seconds.", file=sys.stderr, flush=True)
            time.sleep(5)
        except Exception:
            failures += 1
            print(f"error #{failures}, rebuilding in 2 seconds:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            time.sleep(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, default=8)
    ap.add_argument("--seed")
    ap.add_argument("--params", default="{}", help="JSON overrides of DEFAULTS")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true", help="print the final score as one JSON line")
    ap.add_argument("--final", action="store_true", help="play our copy of the final (or test final) from the live stream")
    ap.add_argument("--board", action="store_true", help="play our next ranking run (counts in the practice rankings)")
    ap.add_argument("--world", help="play this world live from the stream (a practice world paced by pace.py)")
    a = ap.parse_args()
    params = json.loads(a.params)
    client = Client()
    if a.final or a.world:
        print(f"bot3 live, params {json.dumps(params)}", flush=True)
        try:
            score = run_live(client, params, a.world)
        except KeyboardInterrupt:
            sys.exit("Stopped. The world keeps running without us; start again with the same command to rejoin.")
        report("End", score)
        print(json.dumps({"world": a.world or "final", "ranked": score["ranked"], **score.get("live", {})}), flush=True)
        return
    world = client.create(level=a.level, seed=a.seed, board=a.board)
    print(f"{'Ranking run' if a.board else 'Practice world'} {world.id}", flush=True)
    if a.board:
        score = play_board(client, world, params)
        report("End", score)
        print(json.dumps({"world": world.id, "board": True, **score}), flush=True)
        return
    try:
        score = play_practice(world, a.level, params, not a.quiet)
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
