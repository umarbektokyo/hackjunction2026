"""Fits the part of the competitor's price that is the same in every world: an effect per pickup place and per
delivery place, from our own quotes in the exported reveals (logs/reveal-*/requests.csv and legs.csv).

Model, on requests where we quoted the dealer's fastest option and nothing faster was left out:
    P(won) = sigmoid(s * (w_world,day + a_pickup + b_delivery + hop(km) - log x)),  x = our price / list price
The world-day terms soak up each week's level and day factor (they are new in every world); a and b carry over.
Writes lane_effects.json: {"slope": s, "pick": {place: a}, "deliv": {place: b}}, in log price units.

    . ./env.sh && "$SPREAD_PYTHON" fit_lanes.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import argparse

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ("same_day", "next_day", "within_3_days")


def rows(exclude=()):
    out = []
    for folder in glob.glob(os.path.join(HERE, "logs", "reveal-*")):
        try:
            req = pd.read_csv(os.path.join(folder, "requests.csv"))
            legs = pd.read_csv(os.path.join(folder, "legs.csv"))
            roads = pd.read_csv(os.path.join(folder, "roads.csv"))
        except (FileNotFoundError, pd.errors.EmptyDataError):
            continue
        km = {(r["from"], r["to"]): r["km"] for _, r in roads.iterrows()}
        first = legs[legs["leg"] == 0].set_index("requestId")
        last = legs.sort_values("leg").groupby("requestId").tail(1).set_index("requestId")
        nlegs = legs.groupby("requestId").size()
        wid = os.path.basename(folder)[len("reveal-"):]
        if wid in exclude:
            continue
        for _, r in req.iterrows():
            if r["outcome"] not in ("won", "lost") or r["id"] not in first.index:
                continue
            offered = [k for k in KINDS if not pd.isna(r.get(f"{k}.listPriceCents"))]
            if not offered:
                continue
            fast = offered[0]
            q, lst = r.get(f"{fast}.quoteCents"), r[f"{fast}.listPriceCents"]
            if pd.isna(q) or q <= 0 or q / lst > 2.5:
                continue       # the fastest option not quoted, or declined: the dealer's speed preference decides, not price
            pick, deliv = first.loc[r["id"], "pickup.placeId"], last.loc[r["id"], "delivery.placeId"]
            lane_km = sum(km.get((a, b), 0) for a, b in zip(legs[legs.requestId == r["id"]]["pickup.placeId"],
                                                           legs[legs.requestId == r["id"]]["delivery.placeId"])) if nlegs[r["id"]] > 1 else km.get((pick, deliv), 0)
            out.append({"wd": f"{wid}:{int(r['arrivedAt']) // 1440}", "pick": pick, "deliv": deliv, "km": lane_km,
                        "lx": math.log(q / lst), "won": int(r["outcome"] == "won")})
    return pd.DataFrame(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", default="", help="comma-separated world ids to leave out")
    ap.add_argument("--out", default="lane_effects.json")
    a = ap.parse_args()
    df = rows(set(filter(None, a.exclude.split(","))))
    print(f"{len(df)} quotes from {df['wd'].str.split(':').str[0].nunique()} worlds, win rate {df['won'].mean():.2f}")
    cats = []
    for col in ("wd", "pick", "deliv"):
        codes, uniq = pd.factorize(df[col])
        cats.append((col, codes, list(uniq)))
    n = len(df)
    blocks = [sparse.csr_matrix(-df[["lx"]].to_numpy())]   # coefficient on -log x is the slope s
    hop = np.where(df["km"] < 48, np.minimum(1.0, (48 - df["km"]) / 34), 0.0)
    blocks.append(sparse.csr_matrix(hop[:, None]))
    for _, codes, uniq in cats:
        blocks.append(sparse.csr_matrix((np.ones(n), (np.arange(n), codes)), shape=(n, len(uniq))))
    X = sparse.hstack(blocks).tocsr()
    m = LogisticRegression(C=2.0, fit_intercept=False, max_iter=2000)
    m.fit(X, df["won"])
    w = m.coef_[0]
    s = w[0]
    out = {"slope": round(float(s), 3), "short_hop": round(float(w[1] / s), 4), "pick": {}, "deliv": {}}
    i = 2
    for col, _, uniq in cats:
        vals = w[i:i + len(uniq)] / s
        i += len(uniq)
        if col == "wd":
            out["world_day_mean"] = round(float(np.mean(vals)), 4)
            out["world_day_sd"] = round(float(np.std(vals)), 4)
            continue
        vals = vals - vals.mean()      # the world-day terms hold the level; places are relative to the average place
        out[col] = {k: round(float(v), 4) for k, v in zip(uniq, vals)}
    pred = m.predict_proba(X)[:, 1]
    print(f"slope {s:.2f}  short hop {out['short_hop']:+.3f}  world-day mean {math.exp(out['world_day_mean']):.3f}x sd {out['world_day_sd']:.3f}"
          f"  log loss {-np.mean(df['won'] * np.log(pred) + (1 - df['won']) * np.log(1 - pred)):.4f}")
    for col in ("pick", "deliv"):
        top = sorted(out[col].items(), key=lambda kv: kv[1])
        print(col, "lowest", top[:4], "highest", top[-4:])
    with open(os.path.join(HERE, a.out), "w") as f:
        json.dump(out, f, indent=1)
    print("wrote lane_effects.json")


if __name__ == "__main__":
    main()
