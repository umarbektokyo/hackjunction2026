"""Evil Club's desk with learned models (see ml_tables.py, ml_fit.py and NOTES.md). It is EvilDesk from bot.py with
two decisions replaced; each can be switched off to measure it:

1. quote() - "win_model": for each request, choose the prices that maximise
       sum over options k of  P(the dealer takes our option k | our prices) x (price_k - expected fee - expected late cost).
   P comes from a dealer-choice model fitted on our logged weeks. Its one unknown, today's market level, is learned
   online from each won and lost answer (a grid Bayes filter, ml_features.Market). The existing cutoffs stay: drives
   over max_minutes, pickups with fewer than min_drivers nearby and options with too little slack are declined.
2. fees_for() - "fee_model": the fee clock keeps its shape (flat opening fee, three raises in the last market hours),
   but the opening fee of each gig is the one with the lowest expected cost under the fitted booking model
   P(book before the raises start | opening fee, gig).

    python bot2.py --seed bench-1 --params '{"fee_model": 0}'
"""
from __future__ import annotations

import os

# One thread for the models: a prediction then takes about 2 ms; with sklearn's thread pool on a busy machine it took 50-100 ms.
os.environ.setdefault("OMP_NUM_THREADS", "1")

import argparse
import json
import math
import pickle
import sys
import time
import traceback
import warnings

import numpy as np

from bot import DEFAULTS as BASE_DEFAULTS, DAY, HOUR, WAKE, WEEKDAYS, EvilDesk, mkt_add, mkt_back, report
from ml_features import KINDS, OPTION_CODE, Market, gig_X, mkt, order_X, win_x
from spread.client import Client, SpreadError, Unreachable, World
from spread.starter import next_final

warnings.filterwarnings("ignore", category=UserWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
BEST = {"fee_open": 0.8, "fee_cap": 1.7, "target_win": 0.4, "max_minutes": 180, "min_drivers": 20, "fee_clock": 1, "past_saving": 1}
DEFAULTS = {**BASE_DEFAULTS, **BEST,
            "models": "models.pkl",
            "win_model": 1,          # 1 = expected-profit pricing from the win model
            "r_min": 1.0, "r_max": 2.4, "r_step": 0.025,   # price grid, times the list price
            "late_refund": 0.35,     # share of the price refunded when late (25% typical, more when very late)
            "late_pen": 5000,        # extra cost of a late order, cents (trust halved, ranking risk)
            "cost_mult": 1.0,        # scales the expected fee, a safety margin
            "hour_sd": 0.15,         # how far the market level may drift each hour
            "fee_model": 0,          # 1 = opening fee of each gig from the booking model (adds nothing measurable: off)
            "fm_min": 0.7, "fm_max": 1.3, "fm_step": 0.05,
            "fm_after": 0.25,        # extra cost (times typical) of a gig still open when the raises start
            # direct offers (RULES: 3 a driver a day, 3 open a gig, 10 minutes to answer, none read 23:00-07:00)
            "offer_raise": 0,        # 1 = shortly before each fee raise, offer the gig at about the current fee to its recent viewers
            "offer_lead": 15,        # minutes before the raise
            "offer_bump": 0.0,       # offer fee = current + bump x (next step - current)
            "chain_offers": 0,       # 1 = offer an open gig to a driver finishing one of our gigs within 30 km of its pickup
            "chain_disc": 1.0,       # chain offer fee, times the current app fee
            "chain_before": 60,      # minutes before that driver's expected delivery
            }


class EvilDesk2(EvilDesk):
    def __init__(self, world, level, now, params, world_map, roster):
        super().__init__(world, level, now, {**BEST, **params}, world_map, roster)
        self.p = {**DEFAULTS, **params}
        with open(os.path.join(HERE, self.p["models"]), "rb") as f:
            m = pickle.load(f)
        w = m["win"]
        self.wA, self.wB, self.wC = np.array(w["A"]), np.array(w["B"]), np.array(w["C"])
        self.wG = np.array(w["G"])
        self.wP, self.wQ, self.wD = w["P"], w["Q"], w["D"]
        self.market = Market({**w["prior"], "hour_sd": self.p["hour_sd"]}, now)
        self.fee_m, self.cost_m, self.late_m, self.other = m["fee"], m["cost"], m["late"], m["other_cost"]
        self.grid = np.arange(self.p["r_min"], self.p["r_max"] + 1e-9, self.p["r_step"])
        self.lgrid = np.log(self.grid)
        self.wu: dict[str, np.ndarray] = {}           # request id -> utilities of our quote (without the market)
        self.dealer_day: dict[tuple, list] = {}       # (dealer, day) -> [won, decided]
        self.raise_sum, self.raise_n = 0.0, 0         # booked fee / opening fee of our gigs, drivers' learned raise
        self.fm_log: list[float] = []
        self.stats = {"quotes": 0, "declined": 0, "ev": 0.0, "pred_win": 0.0, "q_ms": [], "f_ms": []}
        self.drivers = {d["id"]: d for d in roster}
        self.viewers: dict[str, list] = {}            # gig -> drivers who viewed it, oldest first
        self.offer_day: dict[tuple, int] = {}         # (driver, day) -> offers sent
        self.open_offers: dict[str, set] = {}         # gig -> drivers with an open offer
        self.offer_fee: dict[tuple, int] = {}         # (gig, driver) -> fee offered
        self.offer_done: set = set()                  # (gig, step minute) already offered before that raise
        self.sched: dict[str, list] = {}              # gig -> its schedule after a reprice
        self.working: dict[str, tuple] = {}           # driver -> (delivery place, expected delivery minute) of our gig
        self.ostats = {"sent": 0, "accepted": 0, "declined": 0, "expired": 0, "chain": 0, "saved": 0}

    # ---- quoting ---------------------------------------------------------------------------
    def quote(self, request) -> None:
        t0 = time.perf_counter()
        try:
            self._quote(request)
        finally:
            self.stats["q_ms"].append(1000 * (time.perf_counter() - t0))

    def _quote(self, request) -> None:
        if not self.p["win_model"]:
            return super().quote(request)
        self.requests[request["id"]] = request
        p, legs = self.p, request["legs"]
        a, b = legs[0]["pickup"]["placeId"], legs[-1]["delivery"]["placeId"]
        drive = sum(self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in legs)
        ref = request["referenceFeeCents"]
        day = request["arrivedAt"] // DAY
        ends_ok = all(self.near.get(l["pickup"]["placeId"], 0) >= p["min_drivers"]
                      and self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) <= p["max_minutes"] for l in legs)
        won_n = self.dealer_day.get((request["dealerId"], day - 1))
        raw = dict(drive=[drive], near_pick=[self.near.get(a, 0)], near_del=[self.near.get(b, 0)], hour=[(request["arrivedAt"] % DAY) / 60],
                   legs=[len(legs)], batch=[float(bool(request.get("batchId")))], note=[float(bool(request.get("note")))],
                   private=[float(any(l["pickup"]["privateAddress"] or l["delivery"]["privateAddress"] for l in legs))],
                   premium=[float(any(l["car"]["premium"] for l in legs))], electric=[float(any(l["car"]["electric"] for l in legs))],
                   trust=[self.trust.get(request["dealerId"], 0)],
                   prev_share=[won_n[0] / won_n[1] if won_n and won_n[1] else float("nan")], n_options=[len(request["options"])])
        x = win_x(raw)[0]
        common = self.wP.get(a, 0.0) + self.wQ.get(b, 0.0) + self.wD.get(request["dealerId"], 0.0)
        # cost of each option: expected fee and other costs, P(late), congestion
        opts = {o["kind"]: o for o in request["options"]}
        kinds = [k for k in KINDS if k in opts]
        pick_from = min(l["pickup"]["window"]["from"] for l in legs)
        start = max(request["respondBy"], pick_from)
        orow = {c: [] for c in ["option", "list", "ref", "drive", "near_pick", "near_del", "hour", "weekday", "slack_mkt", "legs", "premium",
                                "electric", "private", "note", "batch", "fee_open", "fee_clock", "past_saving"]}
        for k in kinds:
            o = opts[k]
            for c, v in dict(option=OPTION_CODE[k], list=o["listPriceCents"], ref=ref, drive=drive, near_pick=raw["near_pick"][0],
                             near_del=raw["near_del"][0], hour=raw["hour"][0], weekday=day % 7,
                             slack_mkt=float(mkt(o["deadline"]) - mkt(start)) - drive, legs=len(legs), premium=raw["premium"][0],
                             electric=raw["electric"][0], private=raw["private"][0], note=raw["note"][0], batch=raw["batch"][0],
                             fee_open=BEST["fee_open"], fee_clock=1, past_saving=1).items():
                orow[c].append(v)
        X = order_X(orow)
        fee_hat = self.cost_m.predict(X) * p["cost_mult"]
        p_late = self.late_m.predict_proba(X)[:, 1]
        surcharge = p["backlog_k"] * max(0, self.backlog() - p["backlog_free"])
        # utilities u_k(r) = c_k + B_k ln r, margins m_k(r) = r L (1 - pl refund) - cost
        c = np.full(3, -np.inf)
        L = np.zeros(3)
        cost = np.zeros(3)
        refund = np.zeros(3)
        allowed = np.zeros(3, bool)
        for i, k in enumerate(kinds):
            j = KINDS.index(k)
            o = opts[k]
            L[j] = o["listPriceCents"]
            slack = o["deadline"] - max(self.now, request["respondBy"]) - drive
            allowed[j] = ends_ok and slack >= p["min_slack"]
            c[j] = common + self.wA[j] + self.wC[j] * math.log(L[j] / ref) + x @ self.wG[j]
            cost[j] = ref * (fee_hat[i] + self.other) + p_late[i] * p["late_pen"] + surcharge * L[j]
            refund[j] = p_late[i] * p["late_refund"]
        self.market.advance(self.now)
        r_idx = self._optimise(c, L, cost, refund, allowed)
        prices, u = {}, np.full(3, -np.inf)
        for k in kinds:
            j = KINDS.index(k)
            if r_idx[j] < 0:
                prices[k] = max(1, int(L[j] * p["decline_mult"] + 0.5))
            else:
                prices[k] = max(1, int(L[j] * self.grid[r_idx[j]] + 0.5))
                u[j] = c[j] + self.wB[j] * math.log(prices[k] / L[j])
        self.stats["quotes"] += 1
        if np.isfinite(u).any():
            self.wu[request["id"]] = u
            self.pending[request["id"]] = a
            pw = self.market.probs(u)
            self.stats["pred_win"] += float(pw.sum())
        else:
            self.stats["declined"] += 1
        self.quoted[request["id"]] = prices
        self.outbox.append({"type": "quote", "requestId": request["id"], "prices": prices})

    def _optimise(self, c, L, cost, refund, allowed):
        """Coordinate ascent over the options on the price grid; -1 = decline. Returns grid indices."""
        n = len(self.grid)
        idx = np.full(3, -1)
        if not allowed.any():
            return idx
        U = c[None, :] + self.wB[None, :] * self.lgrid[:, None]                      # (grid, 3)
        M = self.grid[:, None] * L[None, :] * (1 - refund[None, :]) - cost[None, :]  # (grid, 3)
        best_ev = 0.0
        for _ in range(3):
            changed = False
            for j in range(3):
                if not allowed[j]:
                    continue
                u = np.full((n + 1, 3), -np.inf)
                m = np.zeros((n + 1, 3))
                for i in range(3):
                    if i != j and idx[i] >= 0:
                        u[:, i] = U[idx[i], i]
                        m[:, i] = M[idx[i], i]
                u[:n, j] = U[:, j]
                m[:n, j] = M[:, j]                                                   # row n = decline j
                P = self.market.probs(u)
                ev = (np.nan_to_num(P) * m).sum(1)
                k = int(np.argmax(ev))
                new = k if k < n else -1
                if new != idx[j]:
                    idx[j], changed = new, True
                best_ev = float(ev[k])
            if not changed:
                break
        self.stats["ev"] += best_ev
        return idx

    def learn(self, won: bool, request_id: str, option: str | None = None) -> None:
        option = option or (getattr(self, "_won_option", None) if won else None)
        self._won_option = None
        super().learn(won, request_id)
        req = self.requests.get(request_id)
        if req:
            key = (req["dealerId"], req["arrivedAt"] // DAY)
            s = self.dealer_day.setdefault(key, [0, 0])
            s[0] += int(won)
            s[1] += 1
        u = self.wu.pop(request_id, None)
        if u is None:
            return
        self.market.advance(self.now)
        self.market.update(u, KINDS.index(option) if won and option in KINDS else -1)

    # ---- fees ------------------------------------------------------------------------------
    def fees_for(self, order, cars):
        p = self.p
        if (not p["fee_model"] or not p["fee_clock"] or order["id"] in self.urgent
                or (p["past_saving"] and self.now >= order["lastPickupAt"])):
            return super().fees_for(order, cars)
        t0 = time.perf_counter()
        f0 = self.opening_fee(order, cars)
        self.stats["f_ms"].append(1000 * (time.perf_counter() - t0))
        saved, self.fee_open = self.fee_open, f0
        try:
            return super().fees_for(order, cars)
        finally:
            self.fee_open = saved

    def opening_fee(self, order, cars) -> float:
        p = self.p
        T = order["lastPickupAt"] - 3 * HOUR
        climb = int(p["climb_h"] * HOUR)
        start = max(mkt_add(self.now, 45), mkt_back(T, climb))
        H = max(5.0, float(mkt(start) - mkt(self.now)))
        legs = order["legs"]
        a, b = legs[0]["pickup"]["placeId"], legs[-1]["delivery"]["placeId"]
        drive = sum(self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in legs)
        f = np.arange(p["fm_min"], p["fm_max"] + 1e-9, p["fm_step"])
        n = len(f)
        rh = self.raise_sum / self.raise_n if self.raise_n else 1.0
        d = dict(ratio=f, t=np.full(n, H), age=np.zeros(n), drive=np.full(n, drive), near_pick=np.full(n, self.near.get(a, 0)),
                 near_del=np.full(n, self.near.get(b, 0)), hour=np.full(n, (self.now % DAY) / 60), weekday=np.full(n, self.now // DAY % 7),
                 option=np.full(n, OPTION_CODE.get(order["option"], 1)), slack_mkt=np.full(n, float(mkt(order["lastPickupAt"]) - mkt(self.now))),
                 cars=np.full(n, cars), experienced=np.full(n, float(any(l["car"]["premium"] for l in legs))), urgent=np.zeros(n),
                 open_ratio=f, raise_hist=np.full(n, rh))
        P = self.fee_m.predict_proba(gig_X(d))[:, 1]
        cap = max(p["fee_cap"], f[0])
        after = f + (cap - f) * 2 / 3 + p["fm_after"]           # mean raised fee plus the risk of a late rescue
        cost = f * P + (1 - P) * after
        f0 = float(f[int(np.argmin(cost))])
        self.fm_log.append(f0)
        return f0

    # ---- direct offers ---------------------------------------------------------------------
    def offers_on(self) -> bool:
        return bool(self.p["offer_raise"] or self.p["chain_offers"])

    def read_results(self, actions, results) -> None:
        super().read_results(actions, results)
        for action, result in zip(actions, results):
            if action["type"] == "reprice" and result["ok"] is True:
                self.sched[action["gigId"]] = action["schedule"]

    def open_gigs(self):
        seen = set()
        for legs in self.leg_gigs.values():
            for gig in legs.values():
                if gig not in seen and gig not in self.booked and gig in self.posts:
                    seen.add(gig)
                    yield gig

    def fits(self, driver: str, gig: str) -> bool:
        d = self.drivers.get(driver)
        aud = self.posts[gig].get("audience", {})
        if d is None or (gig, driver) in self.offer_fee or self.offer_day.get((driver, self.now // DAY), 0) >= 3:
            return False
        if aud.get("manualLicence") and d["licence"] != "manual":
            return False
        return not aud.get("experienced") or (d["rating"] >= 4.8 and d["completedGigs"] >= 50)

    def offer(self, gig: str, driver: str, fee: int) -> None:
        self.outbox.append({"type": "offer", "gigId": gig, "driverId": driver, "feeCents": max(1, int(fee))})
        self.offer_fee[(gig, driver)] = max(1, int(fee))
        self.open_offers.setdefault(gig, set()).add(driver)
        key = (driver, self.now // DAY)
        self.offer_day[key] = self.offer_day.get(key, 0) + 1
        self.ostats["sent"] += 1

    def steps_now(self, gig: str):
        sch = self.sched.get(gig) or self.posts[gig]["schedule"]
        cur = max([s["feeCents"] for s in sch if s["at"] <= self.now] or [sch[0]["feeCents"]])
        nxt = next((s for s in sch if s["at"] > self.now and s["feeCents"] > cur), None)
        return cur, nxt

    def tick(self) -> None:
        """Timed offers. Called before each advance in practice and after each event or idle second live."""
        if not self.offers_on():
            return
        p, tod = self.p, self.now % DAY
        if tod < 7 * 60 or tod >= 23 * 60 - 10:
            return
        for gig in list(self.open_gigs()):
            room = 3 - len(self.open_offers.get(gig, ()))
            if room <= 0:
                continue
            cur, nxt = self.steps_now(gig)
            if p["offer_raise"] and nxt is not None and nxt["at"] - self.now <= p["offer_lead"] and (gig, nxt["at"]) not in self.offer_done:
                self.offer_done.add((gig, nxt["at"]))
                fee = cur + p["offer_bump"] * (nxt["feeCents"] - cur)
                for d in [d for d in reversed(self.viewers.get(gig, [])) if self.fits(d, gig)][:room]:
                    self.offer(gig, d, fee)
                    room -= 1
            if p["chain_offers"] and room > 0 and self.working:
                stop = self.posts[gig]["stops"][0]
                order = self.orders.get(stop["orderId"])
                if order is None:
                    continue
                p0 = order["legs"][stop["leg"]]["pickup"]["placeId"]
                near = self.close.get(p0, {p0})
                for d, (place, eta) in list(self.working.items()):
                    if (place in near and eta - p["chain_before"] <= self.now <= eta + 30
                            and eta + 30 <= order["lastPickupAt"] and self.fits(d, gig)):
                        self.offer(gig, d, cur * p["chain_disc"])
                        self.ostats["chain"] += 1
                        break

    def next_timer(self) -> int:
        """The next minute at which tick() may act (practice worlds stop there)."""
        if not self.offers_on():
            return 1 << 40
        t = 1 << 40
        if self.p["offer_raise"]:
            for gig in self.open_gigs():
                if gig in self.viewers:
                    _, nxt = self.steps_now(gig)
                    if nxt is not None and (gig, nxt["at"]) not in self.offer_done:
                        t = min(t, nxt["at"] - self.p["offer_lead"])
        if self.p["chain_offers"] and self.working:
            t = min(t, self.now + 30)
        day0 = self.now // DAY * DAY
        if self.now % DAY < 7 * 60:
            t = max(t, day0 + 7 * 60)
        return max(self.now + 1, t)

    def track_offers(self, event) -> None:
        k = event["kind"]
        if k == "gig_viewed":
            v = self.viewers.setdefault(event["gigId"], [])
            if event["driverId"] in v:
                v.remove(event["driverId"])
            v.append(event["driverId"])
        elif k == "offer_answered":
            self.open_offers.get(event["gigId"], set()).discard(event["driverId"])
            self.ostats[event["answer"]] = self.ostats.get(event["answer"], 0) + 1
        elif k == "gig_booked":
            fee = self.offer_fee.get((event["gigId"], event["driverId"]))
            if fee is not None and event["feeCents"] <= fee and event["gigId"] in self.posts:
                _, nxt = self.steps_now(event["gigId"])
                self.ostats["saved"] += (nxt["feeCents"] - fee) if nxt else 0
        elif k == "gig_started" and event["gigId"] in self.posts:
            stops = self.posts[event["gigId"]]["stops"]
            order = self.orders.get(stops[-1]["orderId"])
            if order is not None:
                legs = [order["legs"][s["leg"]] for s in stops if s.get("kind", "delivery") == "delivery"] or [order["legs"][stops[-1]["leg"]]]
                drive = sum(self.minutes.get((l["pickup"]["placeId"], l["delivery"]["placeId"]), 0) for l in legs)
                self.working[event["driverId"]] = (legs[-1]["delivery"]["placeId"], self.now + drive + 30)
        if self.working and k in ("gig_started", "delivered"):
            self.working = {d: v for d, v in self.working.items() if v[1] + 60 >= self.now}

    def handle(self, event) -> None:
        if event["kind"] == "order_won":
            self._won_option = event["order"]["option"]    # EvilDesk.handle calls learn(True, id) without it
        elif event["kind"] == "gig_booked":
            post = self.posts.get(event["gigId"])
            if post and post["schedule"]:
                self.raise_sum += event["feeCents"] / max(1, post["schedule"][0]["feeCents"])
                self.raise_n += 1
        if self.offers_on():
            self.track_offers(event)
        super().handle(event)


def play_practice(world: World, level: int, params: dict, verbose: bool) -> dict:
    client = world.client
    snapshot = world.snapshot()
    desk = EvilDesk2(world, level, snapshot["now"], params, client.map(), world.roster())
    ends_at = snapshot["endsAt"]
    while desk.now < ends_at:
        day, midnight = desk.now // DAY, (desk.now // DAY + 1) * DAY
        cap = min(ends_at, midnight)
        if desk.offers_on():
            desk.tick()
            cap = min(cap, desk.next_timer())
        actions, desk.outbox = desk.outbox, []
        step = world.advance(until=WAKE, max=cap, actions=actions)
        desk.read_results(actions, step["results"])
        desk.now = step["now"]
        for event in step["events"]:
            desk.handle(event)
        if verbose and desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
            s = desk.stats
            fm = np.mean(desk.fm_log) if desk.fm_log else float("nan")
            print(f"           market {desk.market.mean():+.2f}  quotes {s['quotes']}  declined {s['declined']}  "
                  f"pred wins {s['pred_win']:.0f}  mean opening fee {fm:.2f}  backlog {desk.backlog()}", flush=True)
    score = world.score()
    s = desk.stats
    score["bot2"] = {"pred_wins": round(s["pred_win"], 1), "quotes": s["quotes"], "declined": s["declined"],
                     "mean_open_fee": round(float(np.mean(desk.fm_log)), 3) if desk.fm_log else None,
                     "quote_ms_mean": round(float(np.mean(s["q_ms"])), 2) if s["q_ms"] else None,
                     "quote_ms_max": round(float(np.max(s["q_ms"])), 1) if s["q_ms"] else None,
                     "fee_ms_mean": round(float(np.mean(s["f_ms"])), 2) if s["f_ms"] else None, "offers": desk.ostats}
    return score


# ---- live play: the final (and a paced practice world for rehearsals) --------------------------------------------
STATE_KEYS = ["market", "trust", "dealer_day", "raise_sum", "raise_n", "results", "mult", "counted", "wu", "quoted", "fee_open",
              "fm_log", "pending", "surcharged", "stats", "viewers", "offer_day", "open_offers", "offer_fee", "offer_done", "sched",
              "working", "ostats"]


class LiveDesk(EvilDesk2):
    """EvilDesk2 for a world that runs by itself. Adds three things:
    - its learned state (market filter, dealer trust, ...) is saved to disk every few seconds, so a restart keeps it;
      without a saved state, rejoin rebuilds trust and dealer shares from the event history;
    - quotes leave the outbox first (the rate limit is 20 actions a second, and a quote has a deadline);
    - the time of every decision and every send is measured."""

    def __init__(self, *a, state_path: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.state_path, self.saved_at = state_path, 0.0
        self.send_ms: list[float] = []
        self.errors = 0
        self.rejected: dict[str, int] = {}

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
        data = {k: getattr(self, k) for k in STATE_KEYS if hasattr(self, k)}
        tmp = self.state_path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(data, f)
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
        """Rebuilds the learned state that the event history holds: dealer answers per day, dealer trust, drivers' raises."""
        requests = {e["request"]["id"]: e["request"] for e in history if e["kind"] == "price_request"}
        for e in history:
            rid = e["order"]["id"] if e["kind"] == "order_won" else e.get("requestId") if e["kind"] == "order_lost" else None
            req = requests.get(rid)
            if req:
                s = self.dealer_day.setdefault((req["dealerId"], req["arrivedAt"] // DAY), [0, 0])
                s[0] += int(e["kind"] == "order_won")
                s[1] += 1
        done = [o for o in snapshot["orders"] if o["id"] in requests and o["deliveredAt"] and all(x is not None for x in o["deliveredAt"])]
        for o in sorted(done, key=lambda o: max(o["deliveredAt"])):
            self.counted.add(o["id"])
            d = o["dealerId"]
            self.trust[d] = self.trust.get(d, 0) + 1 if max(o["deliveredAt"]) <= o["deadline"] else self.trust.get(d, 0) // 2
        opening = {g["id"]: g["schedule"][0]["feeCents"] for g in snapshot["gigs"] if g.get("schedule")}
        for e in history:
            if e["kind"] == "gig_booked" and e["gigId"] in opening:
                self.raise_sum += e["feeCents"] / max(1, opening[e["gigId"]])
                self.raise_n += 1

    def rejoin(self, snapshot, history) -> None:
        if self.load_state():
            print("learned state restored from " + str(self.state_path), flush=True)
        else:
            self.replay(snapshot, history)
        super().rejoin(snapshot, history)

    def send(self) -> None:
        if not self.outbox:
            return
        # Quotes have a deadline (15 world minutes, 1.5-4.5 real seconds): they go alone in a first request, the rest after.
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


def ms(xs, q):
    return float(np.percentile(xs, q)) if xs else float("nan")


def play_live(world: World, params: dict, clock, state_path: str | None, use_state: bool = True) -> dict:
    """Rebuilds the books from the snapshot and the event history, then answers the events of the stream as they come.
    After a second without an event it reads the clock. `clock()` gives the world's current minute."""
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
    handle_ms: dict[str, list] = {}
    lag: list[float] = []           # world minutes between an event and the end of our answer to it
    for event in world.stream(after=history[-1]["seq"] if history else -1, idle=1.0):
        day = desk.now // DAY
        t0 = time.perf_counter()
        if event is None:
            desk.now = max(desk.now, clock())
            try:
                desk.tick()
            except Exception:
                desk.errors += 1
                print(f"error in tick:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        else:
            desk.now = max(desk.now, event["at"])
            try:
                desk.handle(event)
                desk.tick()
            except Exception:
                desk.errors += 1
                print(f"error handling {event['kind']} (seq {event['seq']}):\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        try:
            desk.send()
        except SpreadError as error:
            if isinstance(error, Unreachable):
                raise
            desk.errors += 1
            print(f"send failed: {error}", file=sys.stderr, flush=True)
        dt = 1000 * (time.perf_counter() - t0)
        if event is not None:
            handle_ms.setdefault(event["kind"], []).append(dt)
            if event["kind"] == "price_request" and dt > 1500:
                print(f"SLOW quote: {dt:.0f} ms for {event['request']['id']}", flush=True)
        desk.save_state()
        if desk.now // DAY > day:
            report(WEEKDAYS[day % 7], world.score())
            q = handle_ms.get("price_request", [])
            print(f"           market {desk.market.mean():+.2f}  quotes {desk.stats['quotes']}  quote+send ms p50 {ms(q, 50):.0f} "
                  f"p99 {ms(q, 99):.0f} max {max(q) if q else float('nan'):.0f}  model ms max {max(desk.stats['q_ms'] or [0]):.0f}  "
                  f"send ms max {max(desk.send_ms or [0]):.0f}  errors {desk.errors}  rejected {desk.rejected}  backlog {desk.backlog()}", flush=True)
            if desk.offers_on():
                print(f"           offers {desk.ostats}", flush=True)
        if desk.now >= ends_at:
            break
    desk.save_state(force=True)
    score = world.score()
    q = handle_ms.get("price_request", [])
    score["live"] = {"quote_ms_p50": round(ms(q, 50), 1), "quote_ms_p99": round(ms(q, 99), 1), "quote_ms_max": round(max(q), 1) if q else None,
                     "model_ms_max": round(max(desk.stats["q_ms"] or [0]), 1), "send_ms_max": round(max(desk.send_ms or [0]), 1),
                     "errors": desk.errors, "rejected": desk.rejected, "offers": desk.ostats}
    return score


def play_board(client: Client, world: World, params: dict) -> dict:
    """A ranking run (or any practice world) stepped with advance, like play_practice, but after a lost connection
    or an error it rebuilds the desk from the snapshot and the events (as in the final) and goes on."""
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
                cap = min(ends_at, midnight)
                if desk.offers_on():
                    desk.tick()
                    cap = min(cap, desk.next_timer())
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
            return world.score()
        except KeyboardInterrupt:
            raise
        except Exception as error:
            failures += 1
            print(f"error #{failures} ({error!r}); rebuilding in 5 seconds", file=sys.stderr, flush=True)
            time.sleep(5)


def run_live(client: Client, params: dict, world_id: str | None) -> dict:
    """The final (world_id None) or a paced practice world: plays it, and after a lost connection or an error
    rebuilds from the server and goes on. Ctrl-C stops only this program; the world runs on."""
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
        print(f"bot2 live, params {json.dumps(params)}, OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}", flush=True)
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
        if not a.board:   # a ranking run plays on without us and counts anyway; never delete it
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
