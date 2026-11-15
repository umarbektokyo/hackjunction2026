"""Competitor market estimator. Python port of RoutePulse v21e estimator.ts (exact replay)."""
from __future__ import annotations

import math

from .js import INF, co, jfloor
from .rptime import DAY, HOUR, day_of

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


def sigmoid(z: float) -> float:
    # estimator.ts's own sigmoid (clamped at +-30), distinct from js.sigmoid
    return 1 if z > 30 else 0 if z < -30 else 1 / (1 + math.exp(-z))


def option_multiplier(opt: str) -> float:
    return 1.08 if opt == "same_day" else 0.93 if opt == "within_3_days" else 1.0


def unrounded_list_price_cents(leg_road_kms, opt: str) -> float:
    leg_mult = 0.85 if len(leg_road_kms) == 2 else 1.0
    base = 0
    for km in leg_road_kms:
        base = base + (2000 + 25 * km)
    return base * leg_mult * option_multiplier(opt)


def centered_log_km(leg_road_kms) -> float:
    total = 0
    for km in leg_road_kms:
        total = total + km
    return math.log(max(12, total) / 105)


def log_lane_factor(pickup_id, delivery_id, leg_road_kms, ref_fee_cents, ulp_next_day_cents) -> float:
    a_p = PLACE_ALPHA_PICK.get(pickup_id, 0)
    a_d = PLACE_ALPHA_DELIV.get(delivery_id, 0)
    total_km = 0
    for km in leg_road_kms:
        total_km = total_km + km
    short_hop_lift = 0.13 * min(1, (48 - total_km) / 34) if total_km < 48 else 0
    return a_p + a_d + short_hop_lift - 0.020 * (math.log(max(1, ref_fee_cents) / max(1, ulp_next_day_cents)) + 0.082)


def win_probability(x: float, faster_option_unquoted: bool) -> dict:
    """Returns {"p": ..., "dp_dx": ...}."""
    s1 = 13.0 if x >= 0 else 9.8
    p1 = sigmoid(-s1 * x)
    p = p1
    dp_dx = -s1 * p1 * (1 - p1)
    if faster_option_unquoted:
        p2 = sigmoid(-0.080 - 4.50 * x)
        dp2 = -4.50 * p2 * (1 - p2)
        dp_dx = dp_dx * p2 + p * dp2
        p *= p2
    return {"p": p, "dp_dx": dp_dx}


DEFAULT_DAY_PRECISION = 1 / (0.055 ** 2)


def is_in_business_quote_hours(minute) -> bool:
    tod = minute % DAY
    return tod >= 8 * HOUR and tod <= 18 * HOUR


def _ll(y, p):
    return math.log(p + 1e-9) if y else math.log(1 - p + 1e-9)


class CompetitorMarketEstimator:
    def __init__(self, level: int, within80_map: dict, params=None):
        self.level = level
        self.within80_map = within80_map  # Map<string, Set<string>>: dict center -> collection supporting `in`/len
        if level >= 8:
            self.world_log_mean = math.log(1.42)
            self.min_world_log = math.log(1.24)
            self.max_world_log = math.log(1.58)
            self.world_precision = 1 / (0.065 ** 2)
        elif level == 7:
            self.world_log_mean = math.log(1.25)
            self.min_world_log = math.log(1.10)
            self.max_world_log = math.log(1.42)
            self.world_precision = 1 / (0.060 ** 2)
        else:
            self.world_log_mean = math.log(1.00)
            self.min_world_log = math.log(0.88)
            self.max_world_log = math.log(1.14)
            self.world_precision = DEFAULT_DAY_PRECISION
        self.day_log_offset = 0
        self.day_precision = DEFAULT_DAY_PRECISION
        self.distance_slope = -0.03
        self.distance_slope_info = 90
        self.current_day = 0

        self.price_war_used_this_week = False
        self.outage_used_this_week = False
        self.price_war_today = False
        self.outage_center_today = None

        self.day_start_world_log_mean = self.world_log_mean
        self.day_start_world_precision = self.world_precision
        self.day_start_distance_slope = self.distance_slope
        self.day_start_distance_slope_info = self.distance_slope_info

        self.mon_had_pw_signal = False
        self.mon_implied_log = 0
        self.tue_verified_mon = False

        self.today_quotes = 0
        self.today_full_pw_llr = 0
        self.today_sum_res_start = 0
        self.today_history: list = []
        self.region_out_stats: dict = {}
        self.dealers: dict = {}

    def get_dealer(self, dealer_id: str) -> dict:
        d = self.dealers.get(dealer_id)
        if d is None:
            d = {
                "trust": 0,
                "lateCount": 0,
                "unquotedCount": 0,
                "totalRequestsSeen": 0,
                "priorOutcomes": [],
                "morningRetalLog": 0,
                "latentLogOffset": 0,
                "obsInfo": 25,
            }
            self.dealers[dealer_id] = d
        return d

    def dealer_effective_multiplier(self, d) -> float:
        trust_mult = 1 + 0.01 * d["trust"] if self.level == 8 else 1.0
        return trust_mult * math.exp(-0.0405 * min(d["lateCount"], 6) - 0.0016 * min(d["unquotedCount"], 20))

    def _in_outage_set(self, pickup_id) -> bool:
        c = self.outage_center_today
        if not c:
            return False
        s = self.within80_map.get(c)
        return s is not None and pickup_id in s

    def active_event_log(self, in_hours: bool, pickup_id: str) -> float:
        if in_hours and self.level == 8 and self.price_war_today:
            return math.log(0.80)
        if in_hours and self.level >= 6 and self._in_outage_set(pickup_id):
            return math.log(1.30)
        return 0

    def apply_normal_quote_step(self, grad, info, z_km) -> None:
        v_w = 1 / self.world_precision
        v_d = 1 / self.day_precision
        share_w = v_w / (v_w + v_d)
        share_d = v_d / (v_w + v_d)
        self.world_log_mean = min(
            self.max_world_log,
            max(self.min_world_log, self.world_log_mean + share_w * (grad / (self.world_precision + info))),
        )
        self.day_log_offset = max(-0.16, min(0.16, self.day_log_offset + share_d * (grad / (self.day_precision + info))))
        self.world_precision += 0.45 * info
        self.day_precision += 0.55 * info

        grad_slope = grad * z_km
        info_slope = info * z_km * z_km
        self.distance_slope_info += info_slope
        self.distance_slope = max(-0.22, min(0.22, self.distance_slope + grad_slope / self.distance_slope_info))

    def replay_non_event_quotes(self) -> None:
        self.world_log_mean = self.day_start_world_log_mean
        self.world_precision = self.day_start_world_precision
        self.distance_slope = self.day_start_distance_slope
        self.distance_slope_info = self.day_start_distance_slope_info
        self.day_log_offset = 0
        self.day_precision = DEFAULT_DAY_PRECISION

        if self.price_war_today:
            return
        out_set = self.within80_map.get(self.outage_center_today) if self.outage_center_today else None
        for h in self.today_history:
            if out_set is not None and h["pickupId"] in out_set:
                continue
            x_act = h["xRaw"] - (self.world_log_mean + self.day_log_offset + self.distance_slope * h["zKm"])
            wp = win_probability(x_act, h["fasterOptionUnquoted"])
            p, dp_dx = wp["p"], wp["dp_dx"]
            dp_d_theta = -dp_dx
            denom = max(1e-4, p * (1 - p))
            grad = ((h["y"] - p) * dp_d_theta) / denom
            info = (dp_d_theta * dp_d_theta) / denom
            self.apply_normal_quote_step(grad, info, h["zKm"])

    def estimate_day_implied_log(self) -> float:
        th = self.day_start_world_log_mean
        for _ in range(6):
            g = 0
            h_info = 8.0
            for q in self.today_history:
                x = q["xRaw"] - (th + self.day_start_distance_slope * q["zKm"])
                wp = win_probability(x, q["fasterOptionUnquoted"])
                p, dp_dx = wp["p"], wp["dp_dx"]
                dp = -dp_dx
                den = max(1e-4, p * (1 - p))
                g += ((q["y"] - p) * dp) / den
                h_info += (dp * dp) / den
            th = max(math.log(0.95), min(math.log(1.75), th + g / h_info))
        return th

    def on_new_day(self, day: int) -> None:
        if day <= self.current_day:
            return

        if self.level == 8 and self.current_day == 0 and self.today_quotes >= 15:
            mon_imp = self.estimate_day_implied_log()
            if self.price_war_today or mon_imp <= math.log(1.29):
                self.mon_had_pw_signal = True
                self.mon_implied_log = mon_imp
                if math.exp(mon_imp) < 1.16:
                    self.price_war_used_this_week = True
                    implied_normal = min(self.max_world_log, max(self.min_world_log, mon_imp - math.log(0.80)))
                    self.world_log_mean = 0.65 * self.day_start_world_log_mean + 0.35 * implied_normal
                else:
                    self.world_log_mean = min(self.max_world_log, max(self.min_world_log, mon_imp - math.log(0.80)))
                    self.world_precision = 300
        elif self.price_war_today:
            self.price_war_used_this_week = True
        elif (
            self.level == 8
            and self.current_day >= 1
            and self.current_day <= 3
            and not self.price_war_used_this_week
            and self.today_quotes >= 20
            and self.today_full_pw_llr >= 5.0
            and self.today_sum_res_start / self.today_quotes <= -0.15
        ):
            self.price_war_used_this_week = True
            self.world_log_mean = self.day_start_world_log_mean
            self.world_precision = self.day_start_world_precision
            self.distance_slope = self.day_start_distance_slope
            self.distance_slope_info = self.day_start_distance_slope_info

        if self.outage_center_today:
            end_st = self.region_out_stats.get(self.outage_center_today)
            end_mean_in = end_st["sumResIn"] / max(1, end_st["nIn"]) if end_st else 0
            end_mean_out = end_st["sumResOut"] / end_st["nOut"] if end_st and end_st["nOut"] >= 5 else 0
            if end_st and end_st["nIn"] >= 14 and end_st["llr"] >= 8.5 and end_mean_in - end_mean_out >= 0.22:
                self.outage_used_this_week = True

        self.current_day = day
        self.day_log_offset = 0
        self.day_precision = DEFAULT_DAY_PRECISION
        self.distance_slope_info = max(70, self.distance_slope_info * 0.55)
        self.price_war_today = False
        self.outage_center_today = None
        self.today_quotes = 0
        self.today_full_pw_llr = 0
        self.today_sum_res_start = 0
        self.region_out_stats.clear()
        self.today_history = []

        self.day_start_world_log_mean = self.world_log_mean
        self.day_start_world_precision = self.world_precision
        self.day_start_distance_slope = self.distance_slope
        self.day_start_distance_slope_info = self.distance_slope_info

        for d in self.dealers.values():
            last10 = d["priorOutcomes"][-10:]
            if len(last10) >= 4:
                s = 0
                for v in last10:
                    s = s + v
                wr = s / len(last10)
                d["morningRetalLog"] = max(-0.030, min(0.025, -0.045 * (wr - 0.35)))

    def on_order_delivered(self, dealer_id: str, on_time: bool) -> None:
        d = self.get_dealer(dealer_id)
        if self.level == 8:
            if on_time:
                d["trust"] = min(25, d["trust"] + 1)
            else:
                d["trust"] = jfloor(d["trust"] / 2)
        if on_time:
            d["lateCount"] = max(0, d["lateCount"] - 0.125)
        else:
            d["lateCount"] = min(6, d["lateCount"] + 1)

    def predict_option(self, params: dict) -> dict:
        """params keys: arrivedAt, dealerId, pickupId, deliveryId, legRoadKms, refFeeCents, opt,
        fasterOptionUnquoted, quoteCents. Returns {"compCents", "effMult", "winProb"}."""
        self.on_new_day(day_of(params["arrivedAt"]))
        in_hours = is_in_business_quote_hours(params["arrivedAt"])

        ulp = unrounded_list_price_cents(params["legRoadKms"], params["opt"])
        ulp_next = unrounded_list_price_cents(params["legRoadKms"], "next_day")
        z_km = centered_log_km(params["legRoadKms"])
        d = self.get_dealer(params["dealerId"])
        event_log = self.active_event_log(in_hours, params["pickupId"])
        eff_day_offset = max(-0.03, self.day_log_offset) if event_log > 0 else self.day_log_offset

        log_c = (
            self.world_log_mean
            + eff_day_offset
            + self.distance_slope * z_km
            + event_log
            + log_lane_factor(params["pickupId"], params["deliveryId"], params["legRoadKms"], params["refFeeCents"], ulp_next)
            + d["morningRetalLog"]
            + d["latentLogOffset"]
        )

        comp_cents = ulp * math.exp(log_c)
        eff_mult = self.dealer_effective_multiplier(d)
        x = math.log(max(1, params["quoteCents"]) / max(1, eff_mult * comp_cents))
        p = win_probability(x, params["fasterOptionUnquoted"])["p"]
        return {"compCents": comp_cents, "effMult": eff_mult, "winProb": p}

    def update_price_war_detector(self, x_raw, z_km, faster_option_unquoted, y) -> None:
        if self.level != 8 or self.price_war_used_this_week:
            return
        anchor_w = self.day_start_world_log_mean
        pw_w = anchor_w + math.log(0.80)
        base_a = win_probability(x_raw - (anchor_w + self.day_start_distance_slope * z_km), faster_option_unquoted)
        pw_a = win_probability(x_raw - (pw_w + self.day_start_distance_slope * z_km), faster_option_unquoted)

        ll_base = _ll(y, base_a["p"])
        ll_pw = _ll(y, pw_a["p"])
        self.today_full_pw_llr += ll_pw - ll_base
        self.today_sum_res_start += y - base_a["p"]

        mean_res_start = self.today_sum_res_start / self.today_quotes
        req_pw_quotes = 18 if self.current_day == 0 else 15
        req_pw_llr = 4.8 if self.current_day == 0 else 3.8
        if (
            not self.price_war_today
            and self.today_quotes >= req_pw_quotes
            and self.today_quotes <= 65
            and self.today_full_pw_llr >= req_pw_llr
            and mean_res_start <= -0.22
        ):
            self.price_war_today = True
            self.outage_center_today = None
            self.replay_non_event_quotes()
        elif self.price_war_today and self.today_full_pw_llr < 0.8:
            self.price_war_today = False
            self.replay_non_event_quotes()

    def update_regional_outage_detector(self, pickup_id, x_raw, z_km, faster_option_unquoted, y) -> None:
        if self.level < 6 or self.outage_used_this_week or self.price_war_today:
            return

        for center, st_set in self.within80_map.items():
            cur = self.region_out_stats.get(center)
            if cur is None:
                cur = {
                    "nIn": 0,
                    "llr": 0,
                    "sumResIn": 0,
                    "nOut": 0,
                    "sumResOut": 0,
                    "outDayOff": 0,
                    "outDayPrec": 1 / (0.085 ** 2) if self.current_day == 0 else DEFAULT_DAY_PRECISION,
                }
                self.region_out_stats[center] = cur
            safe_out_off = max(-0.035, min(0.16, cur["outDayOff"]))
            theta_out = self.day_start_world_log_mean + safe_out_off + self.day_start_distance_slope * z_km
            x_c = x_raw - theta_out
            base_c = win_probability(x_c, faster_option_unquoted)

            if pickup_id in st_set:
                out_c = win_probability(x_c - math.log(1.30), faster_option_unquoted)
                d_ll = _ll(y, out_c["p"]) - _ll(y, base_c["p"])
                cur["nIn"] += 1
                cur["llr"] += d_ll
                cur["sumResIn"] += y - base_c["p"]
            else:
                cur["nOut"] += 1
                cur["sumResOut"] += y - base_c["p"]
                dp_theta = -base_c["dp_dx"]
                denom_c = max(1e-4, base_c["p"] * (1 - base_c["p"]))
                grad_c = ((y - base_c["p"]) * dp_theta) / denom_c
                info_c = (dp_theta * dp_theta) / denom_c
                cur["outDayOff"] = max(-0.16, min(0.16, cur["outDayOff"] + grad_c / (cur["outDayPrec"] + info_c)))
                cur["outDayPrec"] += 0.65 * info_c

        prev_center = self.outage_center_today
        best_center = None
        best_score = -INF
        min_n_out = 14 if self.current_day == 0 else 8
        min_n_in = 8 if self.current_day == 0 else 6
        for center, st in self.region_out_stats.items():
            if st["nOut"] < min_n_out or st["nIn"] < min_n_in:
                continue
            mean_in = st["sumResIn"] / st["nIn"]
            mean_out = st["sumResOut"] / st["nOut"]
            contrast = mean_in - mean_out
            req_llr = 4.8 if st["nIn"] < 8 else 3.6
            req_contrast = 0.32 if st["nIn"] < 8 else 0.22
            if st["llr"] >= req_llr and mean_in >= 0.16 and contrast >= req_contrast and mean_out < 0.12:
                s = self.within80_map.get(center)
                set_size = len(s) if s is not None else 5
                score = st["llr"] - 0.55 * set_size
                if score > best_score:
                    best_score = score
                    best_center = center

        if best_center:
            self.outage_center_today = best_center
            if not prev_center:
                self.replay_non_event_quotes()
        elif self.outage_center_today:
            cur_st = self.region_out_stats.get(self.outage_center_today)
            if cur_st and cur_st["llr"] < 1.2:
                self.outage_center_today = None
                self.replay_non_event_quotes()

    def on_quote_resolved(self, meta: dict, won_option) -> None:
        req = meta["request"]
        self.on_new_day(day_of(req["arrivedAt"]))
        y = 1 if won_option is not None else 0
        d = self.get_dealer(req["dealerId"])
        d["priorOutcomes"].append(y)

        if len(meta["competitiveOptions"]) == 0 and won_option is None:
            return

        kms = meta["legRoadKms"]
        prices = meta["prices"]
        eval_opt = meta["competitiveOptions"][0]
        for cur in meta["competitiveOptions"]:
            r_best = co(prices.get(eval_opt), INF) / unrounded_list_price_cents(kms, eval_opt)
            r_cur = co(prices.get(cur), INF) / unrounded_list_price_cents(kms, cur)
            if r_cur < r_best:
                eval_opt = cur

        quote_cents = prices.get(eval_opt)
        if not quote_cents:
            return

        pickup_id = req["legs"][0]["pickup"]["placeId"]
        delivery_id = (
            req["legs"][0]["delivery"]["placeId"] if len(req["legs"]) > 1
            else req["legs"][-1]["delivery"]["placeId"]
        )
        in_hours = is_in_business_quote_hours(req["arrivedAt"])
        ulp = unrounded_list_price_cents(kms, eval_opt)
        ulp_next = unrounded_list_price_cents(kms, "next_day")
        z_km = centered_log_km(kms)

        if quote_cents >= 2.45 * ulp and won_option is None:
            return

        eff_mult = self.dealer_effective_multiplier(d)
        fixed_predictors = (
            log_lane_factor(pickup_id, delivery_id, kms, req["referenceFeeCents"], ulp_next)
            + d["morningRetalLog"]
            + d["latentLogOffset"]
        )
        x_raw = math.log(quote_cents / (eff_mult * ulp)) - fixed_predictors

        if in_hours:
            self.today_quotes += 1
            self.today_history.append({
                "pickupId": pickup_id, "zKm": z_km, "xRaw": x_raw,
                "fasterOptionUnquoted": meta["fasterOptionUnquoted"], "y": y,
            })

            if (
                self.current_day == 1
                and self.mon_had_pw_signal
                and not self.tue_verified_mon
                and not self.price_war_used_this_week
                and self.today_quotes == 16
            ):
                self.tue_verified_mon = True
                tue_imp = self.estimate_day_implied_log()
                if tue_imp - self.mon_implied_log >= 0.135:
                    self.price_war_used_this_week = True
                    self.day_start_world_log_mean = min(
                        self.max_world_log,
                        max(self.min_world_log, self.mon_implied_log - math.log(0.80)),
                    )
                else:
                    self.day_start_world_log_mean = min(
                        self.max_world_log,
                        max(self.min_world_log, 0.5 * (self.mon_implied_log + tue_imp)),
                    )
                self.day_start_world_precision = 350
                self.replay_non_event_quotes()

            self.update_price_war_detector(x_raw, z_km, meta["fasterOptionUnquoted"], y)
            self.update_regional_outage_detector(pickup_id, x_raw, z_km, meta["fasterOptionUnquoted"], y)

        base_log_c_after = self.world_log_mean + self.day_log_offset + self.distance_slope * z_km + fixed_predictors
        x_base_after = math.log(quote_cents / (eff_mult * ulp)) - base_log_c_after
        active_event_log = self.active_event_log(in_hours, pickup_id)

        x_act = x_base_after - active_event_log
        wp = win_probability(x_act, meta["fasterOptionUnquoted"])
        p, dp_dx = wp["p"], wp["dp_dx"]
        dp_d_theta = -dp_dx
        denom = max(1e-4, p * (1 - p))
        grad = ((y - p) * dp_d_theta) / denom
        info = (dp_d_theta * dp_d_theta) / denom

        in_outage_region = self._in_outage_set(pickup_id)
        if not self.price_war_today and not in_outage_region:
            self.apply_normal_quote_step(grad, info, z_km)

        d["obsInfo"] += info
        d["latentLogOffset"] = max(-0.06, min(0.06, d["latentLogOffset"] + (0.25 * grad) / d["obsInfo"]))
