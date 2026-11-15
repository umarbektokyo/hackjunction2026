"""Competitor estimator, driver supply and quote pricing. Python port of source-exp/RoutePulse typescript/market.ts."""
from __future__ import annotations

import math
import json
from pathlib import Path
from functools import lru_cache

from .planner import DAY, HOUR, INF, MapGraph, SnowTracker, compute_option_plan, jceil, jround

PLACE_ALPHA_PICK = {
    "helsinki": -0.038, "espoo": -0.032, "vantaa": -0.041, "tampere": -0.018, "oulu": 0.022,
    "turku": -0.012, "jyvaskyla": 0.014, "lahti": -0.008, "vaasa": 0.028, "kuopio": 0.021,
    "lappeenranta": 0.018, "hameenlinna": -0.004, "seinajoki": 0.020, "hyvinkaa": -0.025, "joensuu": 0.035,
    "porvoo": -0.010, "mikkeli": 0.019, "kokkola": 0.034, "rovaniemi": 0.052, "pori": 0.016,
    "raisio": -0.010, "ylivieska": 0.036, "rauma": 0.018, "salo": -0.006, "kouvola": 0.015,
    "kotka": 0.022, "savonlinna": 0.038, "kajaani": 0.045, "lempaala": -0.014, "kemi": 0.048,
}
PLACE_ALPHA_DELIV = {
    "helsinki": -0.072, "espoo": -0.058, "vantaa": -0.068, "tampere": -0.024, "oulu": 0.034,
    "turku": -0.015, "jyvaskyla": 0.031, "lahti": -0.005, "vaasa": 0.058, "kuopio": 0.045,
    "lappeenranta": 0.038, "hameenlinna": 0.012, "seinajoki": 0.042, "hyvinkaa": -0.042, "joensuu": 0.074,
    "porvoo": -0.008, "mikkeli": 0.049, "kokkola": 0.078, "rovaniemi": 0.118, "pori": 0.041,
    "raisio": -0.009, "ylivieska": 0.082, "rauma": 0.044, "salo": 0.006, "kouvola": 0.052,
    "kotka": 0.066, "savonlinna": 0.089, "kajaani": 0.106, "lempaala": -0.016, "kemi": 0.112,
}
LOG_080, LOG_130 = math.log(0.80), math.log(1.30)


def sigmoid(z: float) -> float:
    return 1.0 if z > 30 else 0.0 if z < -30 else 1 / (1 + math.exp(-z))


def unrounded_list_price_cents(leg_kms, opt: str) -> float:
    opt_mult = 1.08 if opt == "same_day" else 0.93 if opt == "within_3_days" else 1.0
    leg_mult = 0.85 if len(leg_kms) == 2 else 1.0
    base = 0
    for km in leg_kms:
        base = base + (2000 + 25 * km)
    return base * leg_mult * opt_mult


def centered_log_km(leg_kms) -> float:
    total = 0
    for km in leg_kms:
        total = total + km
    return math.log(max(12, total) / 105)


def log_lane_factor(pick: str, deliv: str, leg_kms, ref_fee, ulp_next) -> float:
    a_p = PLACE_ALPHA_PICK.get(pick, 0)
    a_d = PLACE_ALPHA_DELIV.get(deliv, 0)
    total = 0
    for km in leg_kms:
        total = total + km
    hop = 0.13 * min(1, (48 - total) / 34) if total < 48 else 0
    return a_p + a_d + hop - 0.020 * (math.log(max(1, ref_fee) / max(1, ulp_next)) + 0.082)


@lru_cache(maxsize=1)
def empirical_lane_model():
    try:
        return json.loads((Path(__file__).resolve().parents[1] / "lane_effects.json").read_text())
    except (OSError, ValueError):
        return {}


def empirical_lane_delta(pick: str, deliv: str) -> float:
    """Difference between cross-world fitted lane effects and the legacy lane prior."""
    model = empirical_lane_model()
    return (model.get("pick", {}).get(pick, PLACE_ALPHA_PICK.get(pick, 0)) - PLACE_ALPHA_PICK.get(pick, 0)
            + model.get("deliv", {}).get(deliv, PLACE_ALPHA_DELIV.get(deliv, 0)) - PLACE_ALPHA_DELIV.get(deliv, 0))


def win_probability(x: float, faster_unquoted: bool):
    s1 = 13.0 if x >= 0 else 9.8
    p1 = sigmoid(-s1 * x)
    p = p1
    dp = -s1 * p1 * (1 - p1)
    if faster_unquoted:
        p2 = sigmoid(-0.080 - 4.50 * x)
        dp2 = -4.50 * p2 * (1 - p2)
        dp = dp * p2 + p * dp2
        p *= p2
    return p, dp


class RosterSupplyModel:
    def __init__(self, m: MapGraph, roster=()):
        self.map = m
        self.drivers: list = []
        self.by_id: dict = {}
        self.home: dict = {}
        self.p30: dict = {}
        self.p65: dict = {}
        self.update_roster(list(roster))

    def update_roster(self, roster) -> None:
        self.drivers = roster
        self.by_id = {}
        self.home = {pid: [0, 0, 0, 0] for pid in self.map.places_by_id}
        self.p30 = {pid: [0, 0, 0, 0] for pid in self.map.places_by_id}
        self.p65 = {pid: [0, 0, 0, 0] for pid in self.map.places_by_id}
        for d in roster:
            self.by_id[d["id"]] = d
            is_exp = d["rating"] >= 4.8 and d["completedGigs"] >= 50
            is_man = d["licence"] == "manual"
            h = self.home.get(d["homePlaceId"])
            if h is not None:
                h[0] += 1
                if is_exp:
                    h[1] += 1
                if is_man:
                    h[2] += 1
                if is_exp and is_man:
                    h[3] += 1
        for pid, near in self.map.within30km.items():
            c = self.p30[pid]
            for q in near:
                h = self.home.get(q)
                if h is None:
                    continue
                for k in range(4):
                    c[k] += h[k]
        for pid, near in self.map.within65km.items():
            c = self.p65[pid]
            for q in near:
                h = self.home.get(q)
                if h is None:
                    continue
                for k in range(4):
                    c[k] += h[k]

    @property
    def total_drivers(self) -> int:
        return len(self.drivers) or 782

    def home_drivers(self, pid: str) -> int:
        h = self.home.get(pid)
        return h[0] if h else 0

    @staticmethod
    def _pick(c, exp, man) -> int:
        if c is None:
            return 0
        if exp and man:
            return c[3]
        if exp:
            return c[1]
        if man:
            return c[2]
        return c[0]

    def pool30(self, pid: str, exp=False, man=False) -> int:
        return self._pick(self.p30.get(pid), exp, man)

    def pool65(self, pid: str, exp=False, man=False) -> int:
        return self._pick(self.p65.get(pid), exp, man)


def new_dealer() -> dict:
    return {"trust": 0, "lateCount": 0, "unquotedCount": 0, "totalRequestsSeen": 0, "priorOutcomes": [],
            "morningRetalLog": 0, "latentLogOffset": 0, "obsInfo": 25}


class CompetitorMarketEstimator:
    def __init__(self, level: int, within80_list: dict, within80_set: dict, params=None):
        self.level = level
        self.within80_list = within80_list
        self.within80_set = within80_set
        self.online_learning = (params or {}).get("online_learning", 1)
        self.lane_fit_mult = (params or {}).get("lane_fit_mult", 0.0)
        if level >= 8:
            self.world_log_mean, self.min_world_log, self.max_world_log = math.log(1.42), math.log(1.24), math.log(1.58)
            self.world_precision = 1 / (0.065 ** 2)
        elif level == 7:
            self.world_log_mean, self.min_world_log, self.max_world_log = math.log(1.25), math.log(1.10), math.log(1.42)
            self.world_precision = 1 / (0.060 ** 2)
        else:
            self.world_log_mean, self.min_world_log, self.max_world_log = math.log(1.00), math.log(0.88), math.log(1.14)
            self.world_precision = 1 / (0.055 ** 2)
        self.day_log_offset = 0
        self.day_precision = 1 / (0.055 ** 2)
        self.distance_slope = -0.03
        self.distance_slope_info = 90
        self.current_day = 0
        self.price_war_used = False
        self.outage_used = False
        self.price_war_today = False
        self.outage_center_today = None
        self.today_quotes = 0
        self.today_pw_llr = 0
        self.today_res_window: list = []
        self.region_out_stats: dict = {}
        self.dealers: dict = {}

    def get_dealer(self, dealer_id: str) -> dict:
        d = self.dealers.get(dealer_id)
        if d is None:
            d = new_dealer()
            self.dealers[dealer_id] = d
        return d

    def in_outage(self, pick: str) -> bool:
        return bool(self.outage_center_today) and pick in self.within80_set.get(self.outage_center_today, ())

    def on_new_day(self, day: int) -> None:
        if day <= self.current_day:
            return
        if (self.level == 8 and self.current_day == 0 and not self.price_war_used and self.today_quotes >= 15
                and (math.exp(self.world_log_mean + self.day_log_offset) < 1.24 or self.day_log_offset <= -0.095)):
            self.price_war_used = True
            self.world_log_mean = min(self.max_world_log, max(self.min_world_log, self.world_log_mean + self.day_log_offset - LOG_080))
        if self.price_war_today:
            self.price_war_used = True
        if self.outage_center_today:
            st = self.region_out_stats.get(self.outage_center_today)
            if st and (st["llr"] >= 1.5 or st["sumResIn"] / max(1, st["nIn"]) >= 0.14):
                self.outage_used = True
        self.current_day = day
        self.day_log_offset = 0
        self.day_precision = 1 / (0.055 ** 2)
        self.distance_slope_info = max(70, self.distance_slope_info * 0.55)
        self.price_war_today = False
        self.outage_center_today = None
        self.today_quotes = 0
        self.today_pw_llr = 0
        self.today_res_window = []
        self.region_out_stats = {}
        for d in self.dealers.values():
            last10 = d["priorOutcomes"][-10:]
            if len(last10) >= 4:
                wr = sum(last10) / len(last10)
                d["morningRetalLog"] = max(-0.030, min(0.025, -0.045 * (wr - 0.35)))

    def on_order_delivered(self, dealer_id: str, on_time: bool) -> None:
        d = self.get_dealer(dealer_id)
        if self.level == 8:
            d["trust"] = min(25, d["trust"] + 1) if on_time else math.floor(d["trust"] / 2)
        if not on_time:
            d["lateCount"] += 1

    def eff_mult(self, d) -> float:
        trust_mult = 1 + 0.01 * d["trust"] if self.level == 8 else 1.0
        return trust_mult * math.exp(-0.0405 * min(d["lateCount"], 6) - 0.0016 * min(d["unquotedCount"], 20))

    def predict_option(self, arrived_at, dealer_id, pick, deliv, leg_kms, ref_fee, opt, faster_unquoted, quote_cents):
        self.on_new_day(math.floor(arrived_at / DAY))
        tod = arrived_at % DAY
        in_hours = 8 * HOUR <= tod <= 18 * HOUR
        ulp = unrounded_list_price_cents(leg_kms, opt)
        ulp_next = unrounded_list_price_cents(leg_kms, "next_day")
        z_km = centered_log_km(leg_kms)
        d = self.get_dealer(dealer_id)
        event_log = 0
        if in_hours and self.level == 8 and self.price_war_today:
            event_log += LOG_080
        elif in_hours and self.level >= 6 and self.in_outage(pick):
            event_log += LOG_130
        log_c = (self.world_log_mean + self.day_log_offset + self.distance_slope * z_km + event_log
                 + log_lane_factor(pick, deliv, leg_kms, ref_fee, ulp_next)
                 + self.lane_fit_mult * empirical_lane_delta(pick, deliv) + d["morningRetalLog"] + d["latentLogOffset"])
        comp = ulp * math.exp(log_c)
        eff = self.eff_mult(d)
        x = math.log(max(1, quote_cents) / max(1, eff * comp))
        p, _ = win_probability(x, faster_unquoted)
        return comp, eff, p

    def on_quote_resolved(self, meta, won_option) -> None:
        if not self.online_learning:
            return
        req = meta["request"]
        self.on_new_day(math.floor(req["arrivedAt"] / DAY))
        y = 1 if won_option is not None else 0
        d = self.get_dealer(req["dealerId"])
        d["priorOutcomes"].append(y)
        comp_opts = meta["competitiveOptions"]
        if not comp_opts and won_option is None:
            return
        kms, prices = meta["legRoadKms"], meta["prices"]
        if won_option is not None:
            eval_opt = won_option
        else:
            eval_opt = comp_opts[0]
            for cur in comp_opts:
                r_best = prices.get(eval_opt, INF) / unrounded_list_price_cents(kms, eval_opt)
                r_cur = prices.get(cur, INF) / unrounded_list_price_cents(kms, cur)
                if r_cur < r_best:
                    eval_opt = cur
        quote = prices.get(eval_opt)
        if not quote:
            return
        pick = req["legs"][0]["pickup"]["placeId"]
        deliv = req["legs"][-1]["delivery"]["placeId"]
        tod = req["arrivedAt"] % DAY
        in_hours = 8 * HOUR <= tod <= 18 * HOUR
        ulp = unrounded_list_price_cents(kms, eval_opt)
        ulp_next = unrounded_list_price_cents(kms, "next_day")
        z_km = centered_log_km(kms)
        if quote >= 2.45 * ulp and won_option is None:
            return
        eff = self.eff_mult(d)
        base_log_c = (self.world_log_mean + self.day_log_offset + self.distance_slope * z_km
                      + log_lane_factor(pick, deliv, kms, req["referenceFeeCents"], ulp_next)
                      + self.lane_fit_mult * empirical_lane_delta(pick, deliv) + d["morningRetalLog"] + d["latentLogOffset"])
        x_base = math.log(quote / (eff * ulp)) - base_log_c
        faster = meta["fasterOptionUnquoted"]
        base_p, _ = win_probability(x_base, faster)
        res_base = y - base_p

        if in_hours:
            self.today_quotes += 1
            self.today_res_window.append(res_base)
            if len(self.today_res_window) > 18:
                self.today_res_window.pop(0)
            if self.level == 8 and not self.price_war_used and not self.outage_center_today:
                pw_p, _ = win_probability(x_base - LOG_080, faster)
                ll_base = math.log(base_p + 1e-9) if y else math.log(1 - base_p + 1e-9)
                ll_pw = math.log(pw_p + 1e-9) if y else math.log(1 - pw_p + 1e-9)
                self.today_pw_llr = max(0, self.today_pw_llr + (ll_pw - ll_base))
                mean_res = sum_js(self.today_res_window) / len(self.today_res_window)
                if not self.price_war_today and self.today_quotes >= 16 and self.today_pw_llr >= 3.8 and mean_res <= -0.24:
                    self.price_war_today = True
                elif self.price_war_today and self.today_pw_llr < 0.8:
                    self.price_war_today = False
            if self.level >= 6 and not self.outage_used and not self.price_war_today:
                out_p, _ = win_probability(x_base - LOG_130, faster)
                d_ll = ((math.log(out_p + 1e-9) if y else math.log(1 - out_p + 1e-9))
                        - (math.log(base_p + 1e-9) if y else math.log(1 - base_p + 1e-9)))
                for center, places in self.within80_list.items():
                    cur = self.region_out_stats.get(center)
                    if cur is None:
                        cur = {"nIn": 0, "llr": 0, "sumResIn": 0, "nOut": 0, "sumResOut": 0}
                        self.region_out_stats[center] = cur
                    if pick in self.within80_set[center]:
                        cur["nIn"] += 1
                        cur["llr"] = max(0, cur["llr"] + d_ll)
                        cur["sumResIn"] += res_base
                    else:
                        cur["nOut"] += 1
                        cur["sumResOut"] += res_base
                best_center, best_llr = None, 3.6
                for center, st in self.region_out_stats.items():
                    mean_in = st["sumResIn"] / st["nIn"] if st["nIn"] > 0 else 0
                    mean_out = st["sumResOut"] / st["nOut"] if st["nOut"] >= 5 else 0
                    if st["nIn"] >= 8 and st["llr"] >= best_llr and mean_in >= 0.24 and mean_out < 0.12:
                        best_llr = st["llr"]
                        best_center = center
                if best_center:
                    self.outage_center_today = best_center
                elif self.outage_center_today:
                    st = self.region_out_stats.get(self.outage_center_today)
                    if st and st["nIn"] >= 22 and st["llr"] <= 0.25 and st["sumResIn"] / st["nIn"] < 0.10:
                        self.outage_center_today = None

        active = 0
        if in_hours and self.level == 8 and self.price_war_today:
            active = LOG_080
        elif in_hours and self.level >= 6 and self.in_outage(pick):
            active = LOG_130
        p, dp_dx = win_probability(x_base - active, faster)
        dp_dt = -dp_dx
        denom = max(1e-4, p * (1 - p))
        grad = ((y - p) * dp_dt) / denom
        info = (dp_dt * dp_dt) / denom
        if not self.price_war_today and not self.in_outage(pick):
            v_w = 1 / self.world_precision
            v_d = 1 / self.day_precision
            share_w = v_w / (v_w + v_d)
            share_d = v_d / (v_w + v_d)
            self.world_log_mean = min(self.max_world_log, max(self.min_world_log, self.world_log_mean + share_w * (grad / (self.world_precision + info))))
            self.day_log_offset = max(-0.16, min(0.16, self.day_log_offset + share_d * (grad / (self.day_precision + info))))
            self.world_precision += 0.45 * info
            self.day_precision += 0.55 * info
            grad_slope = grad * z_km
            info_slope = info * z_km * z_km
            self.distance_slope_info += info_slope
            self.distance_slope = max(-0.22, min(0.22, self.distance_slope + grad_slope / self.distance_slope_info))
        d["obsInfo"] += info
        d["latentLogOffset"] = max(-0.06, min(0.06, d["latentLogOffset"] + (0.25 * grad) / d["obsInfo"]))


def sum_js(xs) -> float:
    """Left-to-right sum, as JavaScript's reduce((a, b) => a + b, 0)."""
    s = 0
    for x in xs:
        s = s + x
    return s


def request_progress_fraction(now: int) -> float:
    work_per_day = 10 * HOUR
    total = 5 * work_per_day
    day = min(5, max(0, math.floor(now / DAY)))
    if day >= 5:
        return 1.0
    tod = now % DAY
    today = max(0, min(work_per_day, tod - 8 * HOUR))
    return min(1.0, (day * work_per_day + today) / total)


class PricingEngine:
    def __init__(self, level: int, m: MapGraph, snow: SnowTracker, supply: RosterSupplyModel, params=None):
        self.level, self.map, self.snow, self.supply = level, m, snow, supply
        self.params = params or {}
        self.estimator = CompetitorMarketEstimator(level, m.within80km_list, m.within80km_set, self.params)

    def evaluate_option(self, request, option, notes, ctx):
        plan = compute_option_plan(self.map, self.snow, request["legs"], notes, option["deadline"], ctx["now"])
        if not plan:
            return None
        if len(request["legs"]) > 1 and not plan["canSingleGig"]:
            return None
        pick = request["legs"][0]["pickup"]["placeId"]
        deliv = request["legs"][-1]["delivery"]["placeId"]
        q30 = self.supply.pool30(pick, plan["premiumAny"], plan["manualRequired"])
        q65 = self.supply.pool65(pick, plan["premiumAny"], plan["manualRequired"])
        d_home = self.supply.home_drivers(deliv)
        same30 = 1 if self.map.is_same_cluster30(pick, deliv) else 0
        open30 = ctx["openPickupsInCluster30"](pick)

        road_h = plan["totalRoadMinutes"] / HOUR
        over4 = max(0, road_h - 4)
        lead_h = max(0.5, (plan["effectiveLastPickupAt"] - ctx["now"]) / HOUR)
        pick_wd = math.floor(plan["earliestPickupAt"] / DAY) % 7
        is_fri = 1 if pick_wd == 4 else 0
        is_sat = 1 if pick_wd == 5 else 0

        dl_day = math.floor(plan["effectiveDeadline"] / DAY)
        dl_wd = dl_day % 7
        day_cap = max(40, jround(self.supply.total_drivers * (0.064 if dl_wd == 4 else 0.096)))
        day_orders = ctx["activeOrdersOnDeadlineDay"](dl_day)
        day_load = day_orders / day_cap
        if dl_wd == 4 and day_load >= 0.92 and option["kind"] == "same_day":
            return None
        if day_load >= 1.05 and option["kind"] == "same_day":
            return None
        if day_load >= 1.20:
            return None
        if plan["premiumAny"] and q30 == 0 and (q65 < 10 or lead_h < 12):
            return None
        if plan["privateDeliveryCount"] > 0 and len(request["legs"]) == 1 and (q65 < 6 or lead_h < 3.5):
            return None
        if lead_h < 2.0 and q30 < 25:
            return None

        eta = (2.55 - 0.82 * math.log(q30 + 1) + (0.85 if q30 == 0 else 0) - 0.14 * math.log(d_home + 1) + 0.75 * same30
               + 0.12 * road_h + 0.48 * over4 - 1.42 * math.log(lead_h) + 0.28 * is_fri + 0.55 * is_sat
               + (0.60 if len(request["legs"]) == 1 and plan["privateDeliveryCount"] > 0 else 0)
               + (0.50 if plan["needsChargingAny"] else 0) + (0.38 if plan["snowOverlap"] else 0)
               + (0.35 if ctx["fluActiveToday"] else 0) + 0.85 * math.log(open30 + 1)
               + (1.4 * (day_load - 0.80) if day_load > 0.80 else 0))
        p_late = sigmoid(eta)
        cur_on_time = (ctx["deliveredOnTimeTotal"] + 38) / (ctx["deliveredOrdersTotal"] + 40)
        max_pl = 0.018 if cur_on_time < 0.912 else 0.048 if cur_on_time < 0.924 else 0.095 if cur_on_time < 0.940 else 0.135
        max_pl = min(0.35, max_pl * self.params.get("late_threshold_mult", 1.0))
        if p_late > max_pl:
            return None

        fee_mult = 0.89
        if (d_home >= 80 and q30 >= 40 and not plan["premiumAny"] and plan["privatePickupCount"] == 0
                and plan["privateDeliveryCount"] == 0 and plan["totalRoadKm"] <= 240):
            fee_mult -= 0.04
        if d_home <= 5 and not same30:
            fee_mult += 0.08
        elif d_home <= 15 and not same30:
            fee_mult += 0.04
        if q30 == 0:
            fee_mult += 0.12
        elif q30 <= 5:
            fee_mult += 0.07
        elif q30 <= 15:
            fee_mult += 0.03
        if plan["totalRoadKm"] > 260:
            fee_mult += 0.07
        if plan["privatePickupCount"] > 0 and len(request["legs"]) == 1:
            fee_mult += 0.15
        if plan["privateDeliveryCount"] > 0 and len(request["legs"]) == 1:
            fee_mult += 0.17
        if len(request["legs"]) == 2:
            fee_mult += 0.15
        if plan["premiumAny"]:
            fee_mult += 0.19
        if plan["needsChargingAny"]:
            fee_mult += 0.08
        if plan["needsPlatesAny"] or plan["manualRequired"]:
            fee_mult += 0.04
        if is_fri or is_sat:
            fee_mult += 0.07
        if over4 > 0:
            fee_mult += 0.04 * over4
        if plan["snowOverlap"]:
            fee_mult += 0.14
        if ctx["fluActiveToday"]:
            fee_mult += 0.12
        fee_mult += sigmoid(eta + 1.10) * 0.34
        if ctx["hasArrivingDriverSynergy"](pick, deliv, plan["earliestPickupAt"] - 60, plan["effectiveLastPickupAt"]):
            fee_mult -= 0.14
        elif (len(request["legs"]) == 1 and not plan["premiumAny"] and plan["privatePickupCount"] == 0
              and plan["privateDeliveryCount"] == 0 and ctx["hasOpenRoundTripPartner"](pick, deliv)):
            fee_mult -= 0.12
        fee_mult = max(0.74, fee_mult)
        exp_fee = request["referenceFeeCents"] * fee_mult

        dealer = self.estimator.get_dealer(request["dealerId"])
        trust_pen = dealer["trust"] * 160 if self.level == 8 and dealer["trust"] >= 4 else 0
        risk = p_late * (0.35 * option["listPriceCents"] * 1.45 + trust_pen)
        true_cost = exp_fee + risk

        progress = request_progress_fraction(ctx["now"])
        target = (max(270, min(365, jround(self.supply.total_drivers * 0.41))) if self.level >= 7
                  else max(450, min(620, jround(self.supply.total_drivers * 0.25))))
        target = max(1, jround(target * self.params.get("target_mult", 1.0)))
        pace = (ctx["wonOrdersTotal"] + 14) / (target * progress + 14)
        soft_backlog = max(10, self.supply.total_drivers * 0.028)
        backlog_excess = max(0, (ctx["unbookedOrdersCount"] - soft_backlog) / 18)
        local_sat = open30 / max(2.0, q30 * 0.26)
        day_sat = max(0, day_load - 0.62)
        shadow = (0.18 * max(0, pace - 0.58) + 0.20 * backlog_excess * backlog_excess + 0.20 * local_sat * local_sat
                  + 0.48 * day_sat * day_sat)
        if ctx["fluActiveToday"]:
            shadow += 0.10
        if lead_h < 5:
            shadow *= 1.20
        ref_shadow = request["referenceFeeCents"] * min(0.85, shadow)

        trust_bonus = 0
        if (self.level == 8 and not self.estimator.price_war_today and dealer["trust"] < 25 and p_late <= 0.028
                and progress < 0.65 and pace < 1.02):
            obs_rate = dealer["totalRequestsSeen"] / progress if progress > 0.04 else 20
            rem = max(0, (1 - progress) * obs_rate * 0.34)
            trust_bonus = min(260, request["referenceFeeCents"] * 0.04, jround(rem * 18))
        base_eff = max(request["referenceFeeCents"] * 0.78, true_cost + ref_shadow - trust_bonus)
        return {"option": option, "plan": plan, "trueCostCents": true_cost, "baseEffectiveCostCents": base_eff,
                "paceRatio": pace, "dayLoad": day_load, "pLate": p_late}

    def optimize_option_price(self, request, ev, leg_kms, faster_unquoted):
        pick = request["legs"][0]["pickup"]["placeId"]
        deliv = request["legs"][-1]["delivery"]["placeId"]
        est = self.estimator
        args = (request["arrivedAt"], request["dealerId"], pick, deliv, leg_kms, request["referenceFeeCents"], ev["option"]["kind"], faster_unquoted)
        comp, eff, _ = est.predict_option(*args, ev["option"]["listPriceCents"])
        target_scale = eff * comp
        tod = request["arrivedAt"] % DAY
        in_hours = 8 * HOUR <= tod <= 18 * HOUR
        normal_scale = target_scale / 0.80 if (in_hours and self.level == 8 and est.price_war_today) else target_scale
        d = est.get_dealer(request["dealerId"])
        last12 = d["priorOutcomes"][-12:]
        recent_wr = sum_js(last12) / len(last12) if len(last12) >= 8 else 0.40
        anti_retal = jround(normal_scale * 0.032) if recent_wr > 0.65 else 0
        surplus_frac = (min(0.50, max(0, 0.35 * (ev["paceRatio"] - 0.64) + (0.28 * (ev["dayLoad"] - 0.72) if ev["dayLoad"] > 0.72 else 0)))
                        if self.level >= 7 else 0)
        surplus = surplus_frac * max(0, normal_scale - ev["trueCostCents"])
        eff_cost = ev["baseEffectiveCostCents"] + surplus + anti_retal
        normal_floor = max(0, jround(self.params.get("min_quote_floor_cents", 450)))
        floor = (max(650, jround(request["referenceFeeCents"] * 0.16)) if (in_hours and self.level == 8 and est.price_war_today) else normal_floor)
        min_hard = jceil(max(ev["trueCostCents"] + floor, eff_cost + 120))
        max_search = max(min_hard + 500, jround(target_scale * 1.42))
        best_price, best_obj, best_wp = 0, -1, 0
        steps = 48
        for s in range(steps + 1):
            frac = s / steps
            cand = jround(min_hard + frac * (max_search - min_hard))
            _, _, wp = est.predict_option(*args, cand)
            obj = wp * (cand - eff_cost)
            if obj > best_obj:
                best_obj, best_price, best_wp = obj, cand, wp
        if best_price <= 0:
            return None
        cheap_lane_discount = self.params.get("cheap_lane_discount", 0.0)
        if (cheap_lane_discount > 0
                and ev["trueCostCents"] <= request["referenceFeeCents"] * self.params.get("cheap_lane_cost_cap", 0.55)):
            best_price = max(min_hard, jround(best_price * (1 - cheap_lane_discount)))
        pace_discount = self.params.get("pace_discount", 0.0)
        if pace_discount > 0 and ev["paceRatio"] < 0.90:
            best_price = max(min_hard, jround(best_price * (1 - pace_discount)))
        best_price = max(min_hard, jround(best_price * self.params.get("quote_mult", 1.0)))
        _, _, best_wp = est.predict_option(*args, best_price)
        best_obj = best_wp * (best_price - eff_cost)
        return {"priceCents": best_price, "expectedMargin": max(1, best_obj), "winProb": best_wp}

    def quote_request(self, request, notes, ctx):
        d = self.estimator.get_dealer(request["dealerId"])
        d["totalRequestsSeen"] += 1
        kms = [self.map.road_km(l["pickup"]["placeId"], l["delivery"]["placeId"]) for l in request["legs"]]
        if self.level <= 3:
            first = request["options"][0] if request["options"] else None
            if not first:
                return None
            ev = self.evaluate_option(request, first, notes, ctx)
            if not ev or first["listPriceCents"] <= ev["trueCostCents"] + 200:
                return None
            return {"request": request, "legRoadKms": kms, "prices": {first["kind"]: first["listPriceCents"]},
                    "competitiveOptions": [first["kind"]], "fasterOptionUnquoted": False}
        evals = {}
        for opt in request["options"]:
            ev = self.evaluate_option(request, opt, notes, ctx)
            if ev:
                evals[opt["kind"]] = ev
        has_sd = any(o["kind"] == "same_day" for o in request["options"])
        has_nd = any(o["kind"] == "next_day" for o in request["options"])
        prices: dict = {}
        comp_opts: list = []
        sd_ev, nd_ev, d3_ev = evals.get("same_day"), evals.get("next_day"), evals.get("within_3_days")
        sd_opt = self.optimize_option_price(request, sd_ev, kms, False) if sd_ev else None
        nd_opt = self.optimize_option_price(request, nd_ev, kms, has_sd and not sd_opt) if nd_ev else None
        d3_opt = self.optimize_option_price(request, d3_ev, kms, (has_sd and not sd_opt) or (has_nd and not nd_opt)) if d3_ev else None
        if nd_opt and nd_ev:
            prices["next_day"] = nd_opt["priceCents"]
            comp_opts.append("next_day")
        if sd_opt and sd_ev:
            sd_price = sd_opt["priceCents"]
            if "next_day" in prices and nd_ev:
                min_spread = max(450, jround(sd_ev["trueCostCents"] - nd_ev["trueCostCents"] + 250))
                sd_price = max(jround(sd_opt["priceCents"] * 1.04), jround(prices["next_day"] * 1.13), prices["next_day"] + min_spread)
            prices["same_day"] = sd_price
            comp_opts.append("same_day")
        if d3_opt and d3_ev:
            if "next_day" not in prices:
                prices["within_3_days"] = d3_opt["priceCents"]
                comp_opts.append("within_3_days")
            elif nd_ev:
                equal_margin = jround(prices["next_day"] - max(150, nd_ev["trueCostCents"] - d3_ev["trueCostCents"] + 150))
                capped = min(max(d3_opt["priceCents"], equal_margin), prices["next_day"] - 200)
                d3_disc = self.params.get("d3_discount", 0.0)
                if d3_disc > 0:
                    # steer the dealer to the slow option, which is cheaper to serve (bundles, cheaper drivers)
                    capped = min(capped, max(jround(prices["next_day"] * (1 - d3_disc)),
                                             jceil(d3_ev["trueCostCents"] + 500)))
                if ((d3_disc > 0 or capped - d3_ev["trueCostCents"] >= prices["next_day"] - nd_ev["trueCostCents"] - 200)
                        and capped - d3_ev["trueCostCents"] >= 500):
                    prices["within_3_days"] = capped
                    comp_opts.append("within_3_days")
        if not comp_opts:
            decline = request["options"][-1]
            prices[decline["kind"]] = jround(decline["listPriceCents"] * 5.0)
            return {"request": request, "legRoadKms": kms, "prices": prices, "competitiveOptions": [], "fasterOptionUnquoted": False}
        fastest = request["options"][0]["kind"]
        return {"request": request, "legRoadKms": kms, "prices": prices, "competitiveOptions": comp_opts,
                "fasterOptionUnquoted": fastest not in comp_opts}
