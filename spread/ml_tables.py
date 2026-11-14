"""Builds the two training tables from the reveals in logs/reveal-*/:

    logs/ml_quotes.csv.gz   one row per request and option: price / list, won or lost, the option the dealer chose,
                            lane, dealer, day, hour, trust count, our win share at the dealer yesterday
    logs/ml_gigs.csv.gz     one row per gig: opening fee / typical, booked or not, minutes to booking, fee step,
                            drive minutes, drivers near the delivery and the pickup, hour, weekday, option, slack
    logs/ml_orders.csv.gz   one row per won order: its quote-time features and what it cost (fees, refunds, lateness)
    logs/ml_steps.csv.gz    one row per gig and fee step (the time a gig spent at one fee): the hazard data
                            behind P(book within t | fee / typical, features)

Run: ../.venv/bin/python ml_tables.py
"""
from __future__ import annotations

import glob
import json
import math
import os
from collections import defaultdict

import numpy as np
import pandas as pd

from ml_features import mkt

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
DAY = 1440
MKT_OPEN, MKT_CLOSE = 7 * 60 + 30, 20 * 60
KINDS = ["same_day", "next_day", "within_3_days"]


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def seeds():
    out = {}
    for line in open(os.path.join(LOGS, "bench.jsonl")):
        r = json.loads(line)
        for x in r["rows"]:
            if "world" in x:
                params = r["params"]
                if r.get("bot") == "bot2.py":   # bot2 plays the hand-tuned fee policy unless told otherwise
                    params = {"fee_open": 0.8, "fee_cap": 1.7, "fee_clock": 1, "past_saving": 1, **params}
                out[x["world"]] = (x["seed"], r["name"], json.dumps(params, sort_keys=True))
    return out


def supply(folder):
    """Drivers whose home is within 30 km of each place."""
    places = pd.read_csv(f"{folder}/places.csv")
    pos = {r.id: (r.lat, r.lon) for r in places.itertuples()}
    homes = pd.read_csv(f"{folder}/drivers.csv").homePlaceId.value_counts().to_dict()
    near = {p: sum(n for h, n in homes.items() if haversine(pos[p], pos[h]) <= 30) for p in pos}
    return near


def world_tables(folder, meta):
    wid = folder.rsplit("reveal-", 1)[1]
    seed, name, params = meta.get(wid, (f"other-{wid}", "other", "{}"))
    req = pd.read_csv(f"{folder}/requests.csv")
    legs = pd.read_csv(f"{folder}/legs.csv")
    ev = pd.read_csv(f"{folder}/events.csv", low_memory=False)
    gigs = pd.read_csv(f"{folder}/gigs.csv")
    views = pd.read_csv(f"{folder}/views.csv")
    roads = pd.read_csv(f"{folder}/roads.csv")
    minutes = {(r["from"], r["to"]): r["minutes"] for _, r in roads.iterrows()}
    km = {(r["from"], r["to"]): r["km"] for _, r in roads.iterrows()}
    near = supply(folder)
    end = int(ev["at"].max())

    # ---- per request: lane and drive ----
    lg = legs.sort_values(["requestId", "leg"])
    lane = {}
    for rid, g in lg.groupby("requestId"):
        a, b = g["pickup.placeId"].iloc[0], g["delivery.placeId"].iloc[-1]
        drive = sum(minutes.get((x, y), 0) for x, y in zip(g["pickup.placeId"], g["delivery.placeId"]))
        dist = sum(km.get((x, y), 0) for x, y in zip(g["pickup.placeId"], g["delivery.placeId"]))
        lane[rid] = dict(pickup=a, delivery=b, drive=drive, km=dist, premium=bool(g["car.premium"].any()),
                         electric=bool(g["car.electric"].any()), private=bool(g["pickup.privateAddress"].any() or g["delivery.privateAddress"].any()),
                         pick_from=int(g["pickup.window.from"].min()))

    # ---- orders: deadline, completion, on time ----
    won = ev[ev.kind == "order_won"]
    orders = {}
    for _, e in won.iterrows():
        orders[e["order.id"]] = dict(deadline=e["order.deadline"], last_pickup=e["order.lastPickupAt"], dealer=e["order.dealerId"],
                                     option=e["order.option"], won_at=e["at"], legs=len(json.loads(e["order.legs"])))
    for _, e in ev[ev.kind == "order_changed"].iterrows():
        if e["order.id"] in orders:
            orders[e["order.id"]].update(deadline=e["order.deadline"], last_pickup=e["order.lastPickupAt"])
    delivered = ev[ev.kind == "delivered"].groupby("orderId")["at"].agg(["max", "count"])
    cancelled = set(ev[ev.kind == "order_cancelled"]["orderId"])

    # trust timeline per dealer: +1 per on-time order, halved per late one, at the completion minute
    done = []
    for oid, o in orders.items():
        if oid in delivered.index and delivered.loc[oid, "count"] >= o["legs"]:
            t = delivered.loc[oid, "max"]
            done.append((t, o["dealer"], t <= o["deadline"]))
    done.sort()
    trust_events = defaultdict(list)  # dealer -> [(t, trust after)]
    tr = defaultdict(int)
    for t, d, ok in done:
        tr[d] = tr[d] + 1 if ok else tr[d] // 2
        trust_events[d].append((t, tr[d]))

    def trust_at(d, t):
        v = 0
        for tt, x in trust_events.get(d, []):
            if tt > t:
                break
            v = x
        return v

    # our win share at the dealer on the previous day (the competitor reacts to it next morning)
    req["day"] = req["arrivedAt"] // DAY
    dec = req[req.outcome.isin(["won", "lost"])]
    share = dec.assign(w=dec.outcome.eq("won")).groupby(["dealerId", "day"])["w"].agg(["mean", "count"])

    # ---- quotes table ----
    qrows = []
    for rd in req.to_dict("records"):
        r = pd.Series(rd)
        L = lane[r.id]
        opts = {k: (rd.get(f"{k}.listPriceCents"), rd.get(f"{k}.quoteCents"), rd.get(f"{k}.deadline")) for k in KINDS}
        opts = {k: v for k, v in opts.items() if v[0] == v[0] and v[0] is not None}
        ratios = {k: (v[1] / v[0] if v[1] == v[1] and v[1] is not None else np.nan) for k, v in opts.items()}
        offered = {k: x for k, x in ratios.items() if x == x and x < 4.0}
        prev = share.loc[(r.dealerId, r.day - 1)] if (r.dealerId, r.day - 1) in share.index else None
        for k, (lst, q, dl) in opts.items():
            qrows.append(dict(
                world=wid, seed=seed, run=name, params=params, request=r.id, dealer=r.dealerId, batch=r.batchId if r.batchId == r.batchId else "",
                arrived=r.arrivedAt, respond_by=r.respondBy, day=int(r.arrivedAt // DAY), hour=(r.arrivedAt % DAY) / 60,
                ref=r.referenceFeeCents, legs=r.legs, note=isinstance(r.note, str), language=r.language if isinstance(r.language, str) else "",
                option=k, list=lst, quote=q, ratio=ratios[k], deadline=dl, slack=dl - r.respondBy - L["drive"],
                slack_mkt=float(mkt(dl) - mkt(max(r.respondBy, L["pick_from"]))) - L["drive"],
                n_options=len(opts), n_offered=len(offered), min_ratio=min(offered.values()) if offered else np.nan,
                outcome=r.outcome, chosen=r.option if isinstance(r.option, str) else "",
                won=int(r.outcome == "won"), won_this=int(r.outcome == "won" and r.option == k),
                trust=trust_at(r.dealerId, r.arrivedAt),
                prev_share=prev["mean"] if prev is not None else np.nan, prev_n=prev["count"] if prev is not None else 0,
                near_pick=near[L["pickup"]], near_del=near[L["delivery"]], **L))
    quotes = pd.DataFrame(qrows)

    # ---- gigs ----
    booked = ev[ev.kind == "gig_booked"].sort_values("at").groupby("gigId").first()
    expired = ev[ev.kind == "gig_expired"].groupby("gigId")["at"].min()
    urgent_at = ev[ev.kind == "deadline_close"].groupby("orderId")["at"].min()
    vfirst = views.sort_values("at").groupby("gigId").first()
    vlast = views.groupby("gigId")["at"].max()
    nview = views.groupby("gigId")["driverId"].nunique()
    gigs["order"] = gigs["orders"].str.split(" ").str[0]
    gigs = gigs.sort_values("postedAt")
    later_post = {}
    for oid, g in gigs.groupby("order"):
        p = list(g["postedAt"])
        for i, gid in enumerate(g["id"]):
            later_post[gid] = next((x for x in p[i + 1:] if x > p[i]), None)

    grows, srows = [], []
    for g in gigs.itertuples(index=False):
        oid = g.order
        if oid not in orders or oid not in lane:
            continue
        o, L = orders[oid], lane[oid]
        stops = json.loads(g.stops)
        cars = sum(1 for s in stops if s["kind"] == "pickup")
        ref = req.set_index("id").loc[oid, "referenceFeeCents"] * cars / o["legs"]
        sched = json.loads(g.schedule)
        post = int(g.postedAt)
        b = booked.loc[g.id] if g.id in booked.index else None
        b_at = int(b["at"]) if b is not None else None
        # gig end without booking: expiry, a later post of the same order (withdraw and repost), or the last view
        if b_at is not None:
            stop = b_at
        elif g.id in expired.index:
            stop = int(expired.loc[g.id])
        elif later_post.get(g.id):
            stop = int(later_post[g.id])
        else:
            stop = int(vlast.get(g.id, post))
        stop = min(stop, end)
        # fee path: the snapshot keeps the last schedule; before a reprice, the fee drivers saw first stands in
        path = []
        if sched[0]["at"] > post:
            f0 = vfirst.loc[g.id, "feeCents"] if g.id in vfirst.index else None
            if f0 is not None:
                path.append((post, f0))
        path += [(s["at"], s["feeCents"]) for s in sched]
        path = [(max(a, post), f) for a, f in path]
        open_fee = path[0][1] if path else np.nan
        step_no = None
        segs = []
        for i, (a, f) in enumerate(path):
            z = path[i + 1][0] if i + 1 < len(path) else end
            if a >= stop and not (b_at is not None and a == stop):
                break
            hit = b_at is not None and a <= b_at < z
            segs.append((a, min(z, stop), f, hit))
            if hit:
                step_no = i
                break
        drive = L["drive"]
        base = dict(world=wid, seed=seed, run=name, params=params, gig=g.id, order=oid, cars=cars, ref=ref,
                    option=o["option"], drive=drive, km=L["km"], pickup=L["pickup"], delivery=L["delivery"],
                    near_pick=near[L["pickup"]], near_del=near[L["delivery"]], premium=L["premium"],
                    experienced=bool(g._2), manual=bool(g._3),
                    private=L["private"], urgent=bool(oid in urgent_at.index and urgent_at.loc[oid] <= post),
                    last_pickup=o["last_pickup"], deadline=o["deadline"], status=g.status)
        grows.append(dict(base, posted=post, hour=(post % DAY) / 60, weekday=int(post // DAY % 7),
                          open_ratio=open_fee / ref, booked=int(b_at is not None),
                          minutes_to_book=(b_at - post) if b_at is not None else np.nan,
                          mkt_to_book=float(mkt(b_at) - mkt(post)) if b_at is not None else np.nan,
                          book_ratio=(b["feeCents"] / ref) if b is not None else np.nan, fee_step=step_no,
                          slack=o["last_pickup"] - post, slack_mkt=float(mkt(o["last_pickup"]) - mkt(post)),
                          viewers=int(nview.get(g.id, 0)), censor_at=stop))
        for i, (a, z, f, hit) in enumerate(segs):
            srows.append(dict(base, start=a, hour=(a % DAY) / 60, weekday=int(a // DAY % 7), step=i, ratio=f / ref,
                              age=float(mkt(a) - mkt(post)), dur=float(mkt(z) - mkt(a)), clock_dur=z - a, booked=int(hit),
                              t_book=float(mkt(b_at) - mkt(a)) if hit else np.nan,
                              slack=o["last_pickup"] - a, slack_mkt=float(mkt(o["last_pickup"]) - mkt(a))))
    # ---- won orders: the quote-time features of the chosen option, and what the order cost in the end ----
    led = ev[ev.kind == "ledger"]
    per = led.pivot_table(index="line.orderId", columns="line.kind", values="line.cents", aggfunc="sum").fillna(0)
    chosen = quotes[quotes.won_this == 1].set_index("request")
    orows = []
    for oid, o in orders.items():
        if oid not in chosen.index or oid in cancelled:
            continue
        c = chosen.loc[oid]
        lines = per.loc[oid] if oid in per.index else pd.Series(dtype=float)
        n_del = delivered.loc[oid, "count"] if oid in delivered.index else 0
        t_done = delivered.loc[oid, "max"] if n_del >= o["legs"] else np.nan
        orows.append({**{k: c[k] for k in ["world", "seed", "run", "params", "dealer", "batch", "arrived", "day", "hour", "ref", "legs", "note",
                                           "option", "list", "quote", "ratio", "deadline", "slack", "slack_mkt", "n_offered", "trust",
                                           "pickup", "delivery", "drive", "km", "premium", "electric", "private", "near_pick", "near_del"]},
                      "order": oid, "won_at": o["won_at"], "last_pickup": o["last_pickup"],
                      "revenue": lines.get("revenue", 0), "driver_fee": -lines.get("driver_fee", 0), "late_refund": -lines.get("late_refund", 0),
                      "other_cost": -sum(lines.get(k, 0) for k in lines.index if k not in ("revenue", "driver_fee", "late_refund")),
                      "delivered": int(n_del >= o["legs"]), "late": int(not (t_done <= o["deadline"])),
                      "late_min": (t_done - o["deadline"]) if t_done == t_done else np.nan})
    return quotes, pd.DataFrame(grows), pd.DataFrame(srows), pd.DataFrame(orows)


def main():
    meta = seeds()
    Q, G, S, O = [], [], [], []
    folders = sorted(f for f in glob.glob(os.path.join(LOGS, "reveal-*")) if os.path.exists(f"{f}/roads.csv"))
    for i, f in enumerate(folders):
        try:
            q, g, s, o = world_tables(f, meta)
        except Exception as e:  # a broken export should not stop the rest
            print("skip", f, repr(e))
            continue
        Q.append(q), G.append(g), S.append(s), O.append(o)
        if (i + 1) % 20 == 0:
            print(i + 1, "worlds", flush=True)
    for name, parts in (("quotes", Q), ("gigs", G), ("steps", S), ("orders", O)):
        df = pd.concat(parts, ignore_index=True)
        df.to_csv(os.path.join(LOGS, f"ml_{name}.csv.gz"), index=False)
        print(name, df.shape, "worlds", df.world.nunique(), "seeds", df.seed.nunique())


if __name__ == "__main__":
    main()
