"""Feature columns shared by the training script (ml_fit.py) and the bot (bot2.py), so both compute them alike.
Every function takes a dict of equal-length numpy arrays (or lists) of raw fields and returns a 2-D array."""
from __future__ import annotations

import numpy as np

OPTION_CODE = {"same_day": 0, "next_day": 1, "within_3_days": 2}
KINDS = ["same_day", "next_day", "within_3_days"]


def _a(d, k):
    return np.asarray(d[k], dtype=float)


# ---- fee model: P(a gig books within t market minutes at fee / typical = ratio) ----
GIG_COLS = ["lratio", "lt", "lage", "ldrive", "lnear_pick", "lnear_del", "hour", "weekday", "option", "lslack",
            "cars", "experienced", "urgent", "lraise", "raise_hist"]
GIG_CAT = [GIG_COLS.index("option")]
GIG_MONO = [1 if c in ("lratio", "lt") else 0 for c in GIG_COLS]


def gig_X(d) -> np.ndarray:
    """d: ratio (fee / typical now), t (horizon, market minutes), age (market minutes since post), drive, near_pick,
    near_del, hour, weekday, option (code), slack_mkt (market minutes to lastPickupAt), cars, experienced, urgent,
    open_ratio (opening fee / typical), raise_hist (this world's mean booked fee / opening fee so far)."""
    return np.column_stack([
        np.log(_a(d, "ratio")), np.log1p(_a(d, "t")), np.log1p(_a(d, "age")), np.log1p(_a(d, "drive")),
        np.log1p(_a(d, "near_pick")), np.log1p(_a(d, "near_del")), _a(d, "hour"), _a(d, "weekday"), _a(d, "option"),
        np.sign(_a(d, "slack_mkt")) * np.log1p(np.abs(_a(d, "slack_mkt"))), _a(d, "cars"), _a(d, "experienced"),
        _a(d, "urgent"), np.log(_a(d, "ratio") / _a(d, "open_ratio")), _a(d, "raise_hist"),
    ])


# ---- order cost and lateness at quote time ----
ORDER_COLS = ["option", "llist", "ldrive", "lnear_pick", "lnear_del", "hour", "weekday", "lslack", "legs",
              "premium", "electric", "private", "note", "batch", "fee_open", "fee_clock", "past_saving"]
ORDER_CAT = [ORDER_COLS.index("option")]


def order_X(d) -> np.ndarray:
    """d: option (code), list, ref, drive, near_pick, near_del, hour, weekday, slack_mkt (market minutes from the
    answer to the deadline, less the drive), legs, premium, electric, private, note, batch (0/1), and the fee policy:
    fee_open, fee_clock, past_saving."""
    return np.column_stack([
        _a(d, "option"), np.log(_a(d, "list") / _a(d, "ref")), np.log1p(_a(d, "drive")), np.log1p(_a(d, "near_pick")),
        np.log1p(_a(d, "near_del")), _a(d, "hour"), _a(d, "weekday"),
        np.sign(_a(d, "slack_mkt")) * np.log1p(np.abs(_a(d, "slack_mkt"))), _a(d, "legs"), _a(d, "premium"),
        _a(d, "electric"), _a(d, "private"), _a(d, "note"), _a(d, "batch"), _a(d, "fee_open"), _a(d, "fee_clock"),
        _a(d, "past_saving"),
    ])


# ---- win model: the dealer chooses among our offered options and the competitor (multinomial logit) ----
# Utility of our option k for request i:
#   u_ik = market + A[k] + B[k] * ln(price/list) + C[k] * ln(list/ref) + sum_j G[k][j] * x_ij + P[pickup] + Q[delivery] + D[dealer]
# and the competitor's offer has utility 0. `market` is one number per world and day, learned online by the bot.
WIN_COLS = ["ldrive", "lnear_pick", "lnear_del", "h_early", "h_morning", "h_midday", "h_afternoon", "legs2",
            "batch", "note", "private", "premium", "electric", "ltrust", "prev_share", "has_prev", "three_opts"]


def win_x(d) -> np.ndarray:
    """d: drive, near_pick, near_del, hour, legs, batch, note, private, premium, electric, trust, prev_share (NaN when
    unknown), n_options. One row per request."""
    h = _a(d, "hour")
    ps = _a(d, "prev_share")
    has = ~np.isnan(ps)
    return np.column_stack([
        np.log1p(_a(d, "drive") / 60), np.log1p(_a(d, "near_pick")) / 5, np.log1p(_a(d, "near_del")) / 5,
        h < 9, (h >= 9) & (h < 12), (h >= 12) & (h < 15), (h >= 15) & (h < 18),
        _a(d, "legs") > 1, _a(d, "batch"), _a(d, "note"), _a(d, "private"), _a(d, "premium"), _a(d, "electric"),
        np.log1p(0.01 * _a(d, "trust")), np.where(has, ps - 0.5, 0.0), has, _a(d, "n_options") > 2,
    ]).astype(float)


# ---- time ----
DAY = 1440
MKT_OPEN, MKT_CLOSE = 7 * 60 + 30, 20 * 60


def mkt(t):
    """Market minutes (07:30-20:00, Monday to Saturday) from minute 0 to t. Works on numbers and arrays."""
    t = np.asarray(t, dtype=float)
    day, tod = np.floor(t / DAY), np.mod(t, DAY)
    full = 6 * np.floor(day / 7) * 750 + np.minimum(np.mod(day, 7), 6) * 750
    part = np.where(np.mod(day, 7) < 6, np.clip(tod, MKT_OPEN, MKT_CLOSE) - MKT_OPEN, 0)
    return full + part


# ---- the market level: a grid filter over today's offset, shared by the evaluation and the bot ----
class Market:
    """Posterior over e = market - mean[weekday] on a grid. Each answer from a dealer multiplies it by the
    likelihood of that answer. At midnight e follows an AR(1) step (a world level that persists plus a day
    part that does not); within the day it can drift a little each hour."""

    def __init__(self, prior: dict, now: int = 0):
        self.mu = prior["mu_wd"]                     # mean market level by weekday (list of 7)
        self.rho, self.sd = prior["rho"], prior["sd"]  # day-to-day persistence and stationary spread
        self.hour_sd = prior.get("hour_sd", 0.0)
        self.e = np.linspace(-4 * self.sd, 4 * self.sd, 81)
        self.w = np.exp(-0.5 * (self.e / self.sd) ** 2)
        self.w /= self.w.sum()
        self.day, self.hour = now // DAY, now // 60
        innov = self.sd * np.sqrt(max(1e-6, 1 - self.rho ** 2))
        self.T_day = np.exp(-0.5 * ((self.e[None, :] - self.rho * self.e[:, None]) / innov) ** 2)
        self.T_day /= self.T_day.sum(1, keepdims=True)
        if self.hour_sd > 0:
            k = np.exp(-0.5 * ((self.e[None, :] - self.e[:, None]) / self.hour_sd) ** 2)
            self.T_hour = k / k.sum(1, keepdims=True)

    def advance(self, now: int) -> None:
        while self.day < now // DAY:
            self.w = self.w @ self.T_day
            self.day += 1
        if self.hour_sd > 0:
            steps = min(24, now // 60 - self.hour)
            for _ in range(max(0, steps)):
                self.w = self.w @ self.T_hour
        self.hour = max(self.hour, now // 60)

    def level(self) -> np.ndarray:
        """Market levels on the grid for the current day."""
        return self.mu[self.day % 7] + self.e

    def mean(self) -> float:
        return float(self.mu[self.day % 7] + self.w @ self.e)

    def probs(self, u: np.ndarray) -> np.ndarray:
        """u: utilities without the market, shape (..., k) with -inf for options not offered. Returns P(win via k),
        averaged over the posterior, shape (..., k)."""
        z = u[..., None, :] + self.level()[:, None]            # (..., grid, k)
        ez = np.exp(np.minimum(z, 50))
        p = ez / (1 + ez.sum(-1, keepdims=True))
        return np.tensordot(self.w, p, axes=([0], [-2])) if p.ndim == 2 else np.einsum("g,...gk->...k", self.w, p)

    def update(self, u: np.ndarray, chosen: int) -> None:
        """chosen: index of the option won, or -1 when lost."""
        z = u[None, :] + self.level()[:, None]
        ez = np.exp(np.minimum(z, 50))
        den = 1 + ez.sum(1)
        like = (ez[:, chosen] if chosen >= 0 else 1.0) / den
        w = self.w * like
        s = w.sum()
        if s > 0 and np.isfinite(s):
            self.w = w / s
