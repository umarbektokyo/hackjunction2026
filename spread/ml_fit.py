"""Fits the learned models from logs/ml_*.csv.gz (built by ml_tables.py), checks them on held-out seeds,
and saves them to models.pkl for bot2.py.

    "$SPREAD_PYTHON" ml_fit.py            fit, check on held-out seeds, save
    "$SPREAD_PYTHON" ml_fit.py --quick    skip the cross-validation
    "$SPREAD_PYTHON" ml_fit.py --out=models_v2.pkl   save elsewhere (benchmark with --params '{"models":"models_v2.pkl"}')

Models:
  win   P(the dealer takes our option k | our prices) - a multinomial logit: the dealer chooses among our offered
        options and the competitor's offer. One market level per world and day is fitted offline as a fixed
        effect; the bot learns it online with ml_features.Market.
  fee   P(a gig books within t market minutes | fee / typical, features) - gradient boosting, monotone in fee and t.
  cost  expected driver fee / typical of a won order, and P(late), from the quote-time features - gradient boosting.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from ml_features import (GIG_CAT, GIG_COLS, GIG_MONO, KINDS, OPTION_CODE, ORDER_CAT, ORDER_COLS, WIN_COLS, Market, gig_X,
                         order_X, win_x)

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
POLICY_DEFAULTS = {"fee_open": 1.25, "fee_clock": 0, "past_saving": 0}
HORIZONS = [5, 15, 30, 60, 120, 240, 480]


def policy(params_json: pd.Series) -> pd.DataFrame:
    p = params_json.map(json.loads)
    return pd.DataFrame([{k: d.get(k, v) for k, v in POLICY_DEFAULTS.items()} for d in p], index=params_json.index)


def folds(seeds, k=4):
    s = sorted(set(seeds))
    return [[x for i, x in enumerate(s) if i % k == f] for f in range(k)]


def calib(p, y, bins=10):
    df = pd.DataFrame({"p": p, "y": y})
    df["b"] = pd.qcut(df.p, bins, duplicates="drop")
    t = df.groupby("b", observed=True).agg(pred=("p", "mean"), real=("y", "mean"), n=("y", "size"))
    return t.round(3)


# ============================================================ win model
def win_data(q: pd.DataFrame) -> dict:
    q = q[q.option.isin(KINDS)].copy()
    q["off"] = q.ratio.notna() & (q.ratio < 4)
    keys = ["world", "request"]
    first = q.drop_duplicates(keys).set_index(keys)
    wide = q.pivot_table(index=keys, columns="option", values=["ratio", "list"], aggfunc="first")
    off = q.pivot_table(index=keys, columns="option", values="off", aggfunc="first")
    idx = first.index
    n = len(idx)
    avail = np.zeros((n, 3), bool)
    lr = np.zeros((n, 3))
    llist = np.zeros((n, 3))
    for j, k in enumerate(KINDS):
        if ("ratio", k) in wide.columns:
            r = wide[("ratio", k)].reindex(idx).values
            L = wide[("list", k)].reindex(idx).values
            a = off[k].reindex(idx).fillna(False).values.astype(bool) if k in off.columns else np.zeros(n, bool)
            avail[:, j] = a
            lr[:, j] = np.where(a, np.log(np.where(a, r, 1.0)), 0.0)
            llist[:, j] = np.where(np.isfinite(L), np.log(np.where(np.isfinite(L), L, 1.0) / first.ref.values), 0.0)
    y = np.full(n, -1)
    for j, k in enumerate(KINDS):
        y[(first.chosen.values == k) & (first.won.values == 1)] = j
    has_any = avail.any(1)
    f = first.reset_index()
    raw = {c: f[c].values for c in ["drive", "near_pick", "near_del", "hour", "legs", "note", "private", "premium", "electric", "trust", "prev_share", "n_options"]}
    raw["batch"] = f["batch"].fillna("").astype(str).ne("").values
    X = win_x(raw)
    d = dict(X=X, avail=avail, lr=lr, llist=llist, y=y, seed=f.seed.values, world=f.world.values, day=f.day.values,
             arrived=f.arrived.values, respond_by=f.respond_by.values, pickup=f.pickup.values, delivery=f.delivery.values,
             dealer=f.dealer.values)
    return {k: v[has_any] for k, v in d.items()}


class WinModel:
    """u_ik = alpha[seed-day] + A[k] + B[k] ln r_ik + C[k] ln(list_ik/ref_i) + X_i G[k] + P[pickup] + Q[delivery] + D[dealer]."""

    def __init__(self, lam_g=1.0, lam_place=10.0, lam_dealer=10.0, lam_alpha=0.01):
        self.lam = (lam_g, lam_place, lam_dealer, lam_alpha)

    def fit(self, d: dict):
        self.places = sorted(set(d["pickup"]) | set(d["delivery"]))
        self.dealers = sorted(set(d["dealer"]))
        pi = {p: i for i, p in enumerate(self.places)}
        di = {p: i for i, p in enumerate(self.dealers)}
        sd = np.array([f"{s}|{int(x)}" for s, x in zip(d["seed"], d["day"])])
        self.sd_keys, sd_idx = np.unique(sd, return_inverse=True)
        pick = np.array([pi[p] for p in d["pickup"]])
        dlv = np.array([pi[p] for p in d["delivery"]])
        dea = np.array([di[p] for p in d["dealer"]])
        X, avail, lr, llist, y = d["X"], d["avail"], d["lr"], d["llist"], d["y"]
        n, p = X.shape
        nP, nD, nS = len(self.places), len(self.dealers), len(self.sd_keys)
        sizes = [3, 3, 3, 3 * p, nP, nP, nD, nS]
        cuts = np.cumsum([0] + sizes)
        lam_g, lam_place, lam_dealer, lam_alpha = self.lam
        lam = np.concatenate([np.full(9, 1e-3), np.full(3 * p, lam_g), np.full(2 * nP, lam_place), np.full(nD, lam_dealer), np.full(nS, lam_alpha)])
        Y = np.zeros((n, 3))
        won = y >= 0
        Y[np.where(won)[0], y[won]] = 1

        def unpack(th):
            A, B, C, G, P, Q, D, S = (th[cuts[i]:cuts[i + 1]] for i in range(8))
            return A, B, C, G.reshape(3, p), P, Q, D, S

        def f(th):
            A, B, C, G, P, Q, D, S = unpack(th)
            base = S[sd_idx] + P[pick] + Q[dlv] + D[dea]
            u = base[:, None] + A + B * lr + C * llist + X @ G.T
            u = np.where(avail, u, -np.inf)
            m = np.maximum(0, u.max(1))
            ez = np.exp(u - m[:, None])
            Z = np.exp(-m) + ez.sum(1)
            P_ = ez / Z[:, None]
            nll = (np.log(Z) + m).sum() - np.where(won, np.where(Y > 0, u, 0).sum(1), 0.0).sum()
            g = P_ - Y
            g = np.where(avail, g, 0.0)
            gs = g.sum(1)
            grad = np.concatenate([g.sum(0), (g * lr).sum(0), (g * llist).sum(0), (g.T @ X).ravel(),
                                   np.bincount(pick, gs, nP), np.bincount(dlv, gs, nP), np.bincount(dea, gs, nD), np.bincount(sd_idx, gs, nS)])
            nll += 0.5 * (lam * th * th).sum()
            grad += lam * th
            return nll / n, grad / n

        th0 = np.zeros(cuts[-1])
        th0[3:6] = -5.0
        res = minimize(f, th0, jac=True, method="L-BFGS-B", options={"maxiter": 3000})
        self.res = res
        A, B, C, G, P, Q, D, S = unpack(res.x)
        self.A, self.B, self.C, self.G = A, B, C, G
        self.P = dict(zip(self.places, P))
        self.Q = dict(zip(self.places, Q))
        self.D = dict(zip(self.dealers, D))
        self.alpha = dict(zip(self.sd_keys, S))
        # the market prior: mean by weekday, spread, day-to-day persistence
        a = pd.DataFrame([(k.rsplit("|", 1)[0], int(k.rsplit("|", 1)[1]), v) for k, v in self.alpha.items()], columns=["seed", "day", "a"])
        a["wd"] = a.day % 7
        mu = a.groupby("wd").a.mean().reindex(range(7)).fillna(a.a.mean())
        a["e"] = a.a - mu[a.wd].values
        a = a.sort_values(["seed", "day"])
        a["prev"] = a.groupby("seed").e.shift()
        pair = a.dropna()
        sd_e = float(a.e.std())
        rho = float(np.corrcoef(pair.e, pair.prev)[0, 1]) if len(pair) > 5 else 0.5
        self.prior = {"mu_wd": [float(x) for x in mu.values], "sd": max(0.05, sd_e), "rho": max(0.0, min(0.95, rho))}
        return self

    def base_u(self, d: dict) -> np.ndarray:
        """Utilities without the market level; -inf where an option is not offered."""
        P = np.array([self.P.get(x, 0.0) for x in d["pickup"]])
        Q = np.array([self.Q.get(x, 0.0) for x in d["delivery"]])
        D = np.array([self.D.get(x, 0.0) for x in d["dealer"]])
        u = (P + Q + D)[:, None] + self.A + self.B * d["lr"] + self.C * d["llist"] + d["X"] @ self.G.T
        return np.where(d["avail"], u, -np.inf)

    def export(self) -> dict:
        return {"A": self.A.tolist(), "B": self.B.tolist(), "C": self.C.tolist(), "G": self.G.tolist(), "cols": WIN_COLS,
                "P": self.P, "Q": self.Q, "D": self.D, "prior": self.prior}


def online_eval(model: WinModel, d: dict, prior: dict):
    """Predicts each held-out request before its answer, learning the market from earlier answers in the same world."""
    u = model.base_u(d)
    out = np.zeros((len(u), 3))
    order = np.lexsort((d["arrived"], d["world"]))
    for w in np.unique(d["world"]):
        rows = order[d["world"][order] == w]
        m = Market(prior, int(d["arrived"][rows[0]]))
        pend = []  # (answer time, row) - the answer comes by respondBy
        for i in rows:
            t = int(d["arrived"][i])
            pend.sort()
            while pend and pend[0][0] <= t:
                _, j = pend.pop(0)
                m.advance(int(d["respond_by"][j]))
                m.update(u[j], int(d["y"][j]))
            m.advance(t)
            out[i] = m.probs(u[i])
            pend.append((int(d["respond_by"][i]), i))
    return out


def static_pred(model: WinModel, d: dict, prior: dict):
    u = model.base_u(d)
    lvl = np.array([prior["mu_wd"][int(x) % 7] for x in d["day"]])
    z = u + lvl[:, None]
    ez = np.exp(np.minimum(z, 50))
    return ez / (1 + ez.sum(1, keepdims=True))


def nll(P, y):
    p = np.where(y >= 0, P[np.arange(len(y)), np.maximum(y, 0)], 1 - P.sum(1))
    return float(-np.log(np.clip(p, 1e-9, 1)).mean())


def fit_win(q: pd.DataFrame, quick: bool):
    d = win_data(q)
    print(f"win: {len(d['y'])} requests, {len(set(d['world']))} worlds, {len(set(d['seed']))} seeds, won {np.mean(d['y'] >= 0):.3f}")
    if not quick:
        rows, cal = [], []
        for fold in folds(d["seed"]):
            te = np.isin(d["seed"], fold)
            tr = {k: v[~te] for k, v in d.items()}
            ts = {k: v[te] for k, v in d.items()}
            m = WinModel().fit(tr)
            base = np.mean(tr["y"][:, None] == np.arange(3), 0)
            P0 = np.tile(base, (te.sum(), 1))
            Ps = static_pred(m, ts, m.prior)
            res = {"fold": fold, "n": int(te.sum()), "constant": nll(P0, ts["y"]), "static": nll(Ps, ts["y"])}
            for hs in (0.0, 0.03, 0.06):
                pr = dict(m.prior, hour_sd=hs)
                Po = online_eval(m, ts, pr)
                res[f"online h{hs}"] = nll(Po, ts["y"])
                if hs == 0.03:
                    cal.append(pd.DataFrame({"p": Po.sum(1), "y": (ts["y"] >= 0).astype(int), "pk": Po[np.arange(len(Po)), np.maximum(ts["y"], 0)]}))
            rows.append(res)
            print("  ", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in res.items()}, flush=True)
        r = pd.DataFrame(rows)
        print("win held-out log loss (mean over folds):", r.drop(columns=["fold", "n"]).mean().round(4).to_dict())
        c = pd.concat(cal)
        print("win calibration, P(win any) online h0.03, held-out seeds:\n", calib(c.p, c.y).to_string())
    m = WinModel().fit(d)
    print("win coefficients: A", m.A.round(2), "B (price slope)", m.B.round(2), "C (list/ref)", m.C.round(2))
    print("  G:", {c: m.G[:, i].round(2).tolist() for i, c in enumerate(WIN_COLS)})
    print("  market prior:", {k: (np.round(v, 3).tolist() if isinstance(v, list) else round(v, 3)) for k, v in m.prior.items()})
    return m


# ============================================================ fee model
def fee_rows(steps: pd.DataFrame, gigs: pd.DataFrame) -> pd.DataFrame:
    s = steps.copy()
    g = gigs.set_index(["world", "gig"])
    s["open_ratio"] = g.open_ratio.reindex(pd.MultiIndex.from_frame(s[["world", "gig"]])).values
    # drivers' learned expectation of a raise: mean booked fee / opening fee of this world's gigs booked earlier
    bk = gigs[gigs.booked == 1].assign(t=lambda x: x.posted + x.minutes_to_book, x=lambda x: x.book_ratio / x.open_ratio).sort_values("t")
    s["raise_hist"] = 1.0
    for w, grp in s.groupby("world"):
        b = bk[bk.world == w]
        if len(b) == 0:
            continue
        cm = b.x.expanding().mean().values
        i = np.searchsorted(b.t.values, grp.start.values, side="right") - 1
        s.loc[grp.index, "raise_hist"] = np.where(i >= 0, cm[np.maximum(i, 0)], 1.0)
    s = s[s.ratio.notna() & (s.ratio > 0) & s.open_ratio.notna() & (s.open_ratio > 0)]
    expo = np.where(s.booked == 1, s.t_book, s.dur)
    parts = []
    for t in HORIZONS:
        y = (s.booked == 1) & (s.t_book <= t)
        keep = y | (expo >= t)
        parts.append(s[keep].assign(t=t, y=y[keep].astype(int)))
    r = pd.concat(parts, ignore_index=True)
    r["option"] = r.option.map(OPTION_CODE)
    r["experienced"] = r.experienced.astype(float)
    r["urgent"] = r.urgent.astype(float)
    return r


def gig_matrix(r: pd.DataFrame) -> np.ndarray:
    return gig_X({c: r[c].values for c in ["ratio", "t", "age", "drive", "near_pick", "near_del", "hour", "weekday", "option",
                                           "slack_mkt", "cars", "experienced", "urgent", "open_ratio", "raise_hist"]})


def new_fee_model():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_leaf_nodes=31, min_samples_leaf=100,
                                          monotonic_cst=GIG_MONO, categorical_features=GIG_CAT, l2_regularization=1.0)


def fit_fee(steps, gigs, quick):
    r = fee_rows(steps, gigs)
    print(f"fee: {len(r)} rows from {r.gig.nunique()} gigs in {r.world.nunique()} worlds, booked share {r.y.mean():.3f}")
    X, y = gig_matrix(r), r.y.values
    if not quick:
        P = np.zeros(len(r))
        for fold in folds(r.seed):
            te = r.seed.isin(fold).values
            m = new_fee_model().fit(X[~te], y[~te])
            P[te] = m.predict_proba(X[te])[:, 1]
        ll = -np.mean(y * np.log(np.clip(P, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - P, 1e-9, 1)))
        base = y.mean()
        ll0 = -np.mean(y * np.log(base) + (1 - y) * np.log(1 - base))
        print(f"fee held-out log loss {ll:.4f} (constant {ll0:.4f})")
        print("fee calibration, held-out seeds:\n", calib(P, y).to_string())
        for t in (30, 120):
            sel = r.t.values == t
            print(f"  t={t}: by fee/typical bin, predicted vs real")
            df = pd.DataFrame({"b": pd.cut(r.ratio[sel], [0, .7, .85, 1, 1.2, 1.5, 9]), "p": P[sel], "y": y[sel]})
            print(df.groupby("b", observed=True).agg(pred=("p", "mean"), real=("y", "mean"), n=("y", "size")).round(3).T.to_string())
    m = new_fee_model().fit(X, y)
    return m


# ============================================================ order cost and lateness
def order_matrix(o: pd.DataFrame) -> np.ndarray:
    pol = policy(o.params)
    d = {c: o[c].values for c in ["list", "ref", "drive", "near_pick", "near_del", "hour", "slack_mkt", "legs"]}
    d.update(option=o.option.map(OPTION_CODE).values, weekday=(o.day % 7).values, premium=o.premium.astype(float).values,
             electric=o.electric.astype(float).values, private=o.private.astype(float).values, note=o.note.astype(float).values,
             batch=o.batch.fillna("").astype(str).ne("").astype(float).values, **{k: pol[k].values for k in POLICY_DEFAULTS})
    return order_X(d)


def fit_cost(o: pd.DataFrame, quick: bool):
    o = o[o.ref > 0].copy()
    X = order_matrix(o)
    yfee = np.clip(o.driver_fee / o.ref, 0, 6).values
    ylate = o.late.values
    other = float((o.other_cost / o.ref).clip(0, 6).mean())
    print(f"cost: {len(o)} orders, mean fee/typical {yfee.mean():.3f}, late {ylate.mean():.3f}, other costs/typical {other:.3f}")
    mk_r = lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=50, categorical_features=ORDER_CAT, l2_regularization=1.0)
    mk_c = lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=50, categorical_features=ORDER_CAT, l2_regularization=1.0)
    if not quick:
        Pf, Pl = np.zeros(len(o)), np.zeros(len(o))
        for fold in folds(o.seed):
            te = o.seed.isin(fold).values
            Pf[te] = mk_r().fit(X[~te], yfee[~te]).predict(X[te])
            Pl[te] = mk_c().fit(X[~te], ylate[~te]).predict_proba(X[te])[:, 1]
        r2 = 1 - np.mean((yfee - Pf) ** 2) / np.var(yfee)
        print(f"cost held-out R2 of fee/typical {r2:.3f}; calibration by decile:\n", calib(Pf, yfee).to_string())
        print("late calibration, held-out seeds:\n", calib(Pl, ylate).to_string())
    return mk_r().fit(X, yfee), mk_c().fit(X, ylate), other


def main():
    quick = "--quick" in sys.argv
    t0 = time.time()
    q = pd.read_csv(os.path.join(LOGS, "ml_quotes.csv.gz"), low_memory=False)
    steps = pd.read_csv(os.path.join(LOGS, "ml_steps.csv.gz"), low_memory=False)
    gigs = pd.read_csv(os.path.join(LOGS, "ml_gigs.csv.gz"), low_memory=False)
    orders = pd.read_csv(os.path.join(LOGS, "ml_orders.csv.gz"), low_memory=False)
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = {}
    path = os.path.join(HERE, next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--out=")), "models.pkl"))
    if only and os.path.exists(path):
        out = pickle.load(open(path, "rb"))
    if not only or "win" in only:
        out["win"] = fit_win(q, quick).export()
    if not only or "fee" in only:
        out["fee"] = fit_fee(steps, gigs, quick)
    if not only or "cost" in only:
        out["cost"], out["late"], out["other_cost"] = fit_cost(orders, quick)
    out["meta"] = {"worlds": int(q.world.nunique()), "seeds": sorted(q.seed.unique().tolist()), "fitted": time.strftime("%Y-%m-%d %H:%M")}
    with open(path, "wb") as f:
        pickle.dump(out, f)
    print(f"saved {path} in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
