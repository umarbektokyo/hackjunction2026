"""Quote pricing. Python port of RoutePulse v21e market.ts (exact replay). Records are dicts with camelCase keys."""
from __future__ import annotations

import math

from .estimator import CompetitorMarketEstimator, option_multiplier, sigmoid
from .js import INF, co, jceil, jfloor, jround
from .planner import compute_option_plan
from .rptime import DAY, HOUR, day_of, weekday_of_day


def evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd_cents,
                         p_sd_cents, p_nd_cents, p_3d_cents) -> dict:
    """Optional price args are None when absent. Returns {"pWin", "winSd", "winNd", "win3d"}."""
    safe_scale = max(1, tilde_c_nd_cents)
    r_sd = p_sd_cents / safe_scale if p_sd_cents is not None else None
    r_nd = p_nd_cents / safe_scale if p_nd_cents is not None else None
    r_3d = p_3d_cents / safe_scale if p_3d_cents is not None else None

    def head_win(x):
        return sigmoid(-(13.0 if x >= 0 else 9.8) * x)

    p_sd = head_win(math.log(max(1e-6, r_sd / 1.08))) if has_sd_offered and r_sd is not None else 0
    p_nd = head_win(math.log(max(1e-6, r_nd))) if has_nd_offered and r_nd is not None else 0
    p_3dd = head_win(math.log(max(1e-6, r_3d / 0.93))) if has_3d_offered and r_3d is not None else 0

    b0 = p_sd
    b1 = p_nd
    b2 = p_3dd
    if b0 > b1:
        b0, b1 = b1, b0
    if b1 > b2:
        b1, b2 = b2, b1
    if b0 > b1:
        b0, b1 = b1, b0

    win_sd = 0
    win_nd = 0
    win_3d = 0
    prev = 0

    for step in range(3):
        cur = b0 if step == 0 else b1 if step == 1 else b2
        du = cur - prev
        if du <= 1e-9:
            prev = cur
            continue
        mid = 0.5 * (prev + cur)
        w_sd = mid <= p_sd and r_sd is not None
        w_nd = mid <= p_nd and r_nd is not None
        w_3d = mid <= p_3dd and r_3d is not None

        if w_sd and w_nd and w_3d:
            s_sd = sigmoid(4.8 * (0.092 - math.log(r_sd / r_nd)))
            s_3d = sigmoid(5.2 * (math.log(r_nd / r_3d) - 0.092))
            win_sd += du * s_sd
            win_3d += du * (1 - s_sd) * s_3d
            win_nd += du * (1 - s_sd) * (1 - s_3d)
        elif w_sd and w_nd:
            s_sd = sigmoid(4.8 * (0.092 - math.log(r_sd / r_nd)))
            k3d = sigmoid(6.0 * (0.42 - math.log(r_nd / 0.93))) if has_3d_offered and r_nd > 1.08 else 1.0
            win_sd += du * s_sd
            win_nd += du * (1 - s_sd) * k3d
        elif w_nd and w_3d:
            k_sd = 1 - sigmoid(4.8 * (0.092 - math.log(1.08 / r_nd))) if has_sd_offered else 1.0
            s_3d = sigmoid(5.2 * (math.log(r_nd / r_3d) - 0.092))
            win_3d += du * k_sd * s_3d
            win_nd += du * k_sd * (1 - s_3d)
        elif w_sd and w_3d:
            s_sd = sigmoid(4.8 * (0.092 - math.log(r_sd / 1.0)))
            s_3d = sigmoid(5.2 * (math.log(1.0 / r_3d) - 0.092))
            win_sd += du * s_sd
            win_3d += du * (1 - s_sd) * s_3d
        elif w_sd:
            k_nd = sigmoid(4.8 * (0.18 - math.log(r_sd / 1.0))) if has_nd_offered else 1.0
            win_sd += du * k_nd
        elif w_nd:
            k_sd = 1 - sigmoid(4.8 * (0.092 - math.log(1.08 / r_nd))) if has_sd_offered else 1.0
            k3d = sigmoid(6.0 * (0.42 - math.log(r_nd / 0.93))) if has_3d_offered and r_nd > 1.08 else 1.0
            win_nd += du * k_sd * k3d
        elif w_3d:
            k_fast = (
                sigmoid(5.2 * (math.log(1.0 / r_3d) - 0.092))
                if has_nd_offered
                else sigmoid(5.2 * (math.log(1.08 / r_3d) - 0.184))
                if has_sd_offered
                else 1.0
            )
            win_3d += du * k_fast
        prev = cur

    return {"pWin": win_sd + win_nd + win_3d, "winSd": win_sd, "winNd": win_nd, "win3d": win_3d}


def request_progress_fraction(now) -> float:
    work_per_day = 10 * HOUR
    total_week_work = 5 * work_per_day
    day = min(5, max(0, day_of(now)))
    if day >= 5:
        return 1.0
    tod = now % DAY
    today_work = max(0, min(work_per_day, tod - 8 * HOUR))
    return min(1.0, (day * work_per_day + today_work) / total_week_work)


def sweep_menu_grid(lo, hi, steps, fallback_price, eval_at) -> dict:
    """Returns {"bestP", "bestEv"}."""
    best_p = fallback_price
    best_ev = -1e9
    for s in range(steps + 1):
        cand = jround(lo + (s / steps) * (hi - lo))
        ev = eval_at(cand)
        if ev > best_ev:
            best_ev = ev
            best_p = cand
    return {"bestP": best_p, "bestEv": best_ev}


ARCTIC_SINKS = frozenset(["rovaniemi", "kemi"])
NORTHERN_SINKS = frozenset(["oulu", "vaasa", "kokkola", "ylivieska", "kajaani", "joensuu"])


class PricingEngine:
    def __init__(self, level: int, map, snow, supply, params=None):
        # `params` is accepted and ignored (v17 lane-fit knobs are not in v21e)
        self.level = level
        self.map = map
        self.snow = snow
        self.supply = supply
        self.estimator = CompetitorMarketEstimator(level, map.within80km_set)

    def evaluate_option(self, request, option, notes, ctx):
        plan = compute_option_plan(self.map, self.snow, request["legs"], notes, option["deadline"], ctx["now"])
        if not plan:
            return None
        if len(request["legs"]) > 1 and not plan["canSingleGig"]:
            return None

        pickup_id = request["legs"][0]["pickup"]["placeId"]
        delivery_id = request["legs"][-1]["delivery"]["placeId"]
        far_place_id = (
            request["legs"][0]["delivery"]["placeId"]
            if len(request["legs"]) == 2 and self.map.is_same_cluster30(pickup_id, delivery_id)
            else delivery_id
        )
        Q30 = self.supply.pool30(pickup_id, plan["premiumAny"], plan["manualRequired"])
        Q65 = self.supply.pool65(pickup_id, plan["premiumAny"], plan["manualRequired"])
        D_pool30 = self.supply.pool30(far_place_id, False, False)
        same_cluster30 = 1 if len(request["legs"]) == 1 and self.map.is_same_cluster30(pickup_id, delivery_id) else 0
        open30 = ctx["openPickupsInCluster30"](pickup_id)
        pending30 = ctx["pendingPickupsInCluster30"](pickup_id) if ctx.get("pendingPickupsInCluster30") is not None else 0

        batch_load = 0
        batch_info = ctx.get("batchInfo")
        if batch_info is not None and batch_info["seenCount"] >= 12:
            expected_batch_wins = batch_info["wonCount"] + batch_info["unresolvedExpectedWins"]
            local_yard_allowance = max(2.5, min(26, 0.25 * Q30))
            return_hub_allowance = (
                min(10, 0.04 * D_pool30) if D_pool30 >= 80 and plan["totalRoadKm"] <= 220 else 0
            )
            effective_batch_cap = local_yard_allowance + return_hub_allowance
            batch_load = expected_batch_wins / effective_batch_cap

            if batch_load >= 1.40 and option["kind"] == "same_day":
                return None
            if batch_load >= 1.90 and D_pool30 < 80:
                return None

        road_hours = plan["totalRoadMinutes"] / HOUR
        over4h = max(0, road_hours - 4)
        lead_hours = max(0.5, (plan["effectiveLastPickupAt"] - ctx["now"]) / HOUR)
        pick_day = day_of(plan["earliestPickupAt"])
        pick_wd = weekday_of_day(pick_day)

        dl_day = day_of(plan["effectiveDeadline"])
        dl_wd = weekday_of_day(dl_day)
        day_cap_mult = 0.165 if dl_day >= 7 else 0.064 if dl_wd == 4 else 0.096
        day_cap = max(40, jround(self.supply.total_drivers * day_cap_mult))
        day_orders = ctx["activeOrdersOnDeadlineDay"](dl_day)
        day_load = day_orders / day_cap
        if dl_wd == 4 and day_load >= 0.92 and option["kind"] == "same_day":
            return None
        if day_load >= 1.05 and option["kind"] == "same_day":
            return None
        if day_load >= 1.20:
            return None

        has_priv_pick = plan["privatePickupCount"] > 0
        is_fri = 1 if pick_wd == 4 and (dl_day == pick_day or has_priv_pick or day_load >= 0.82) else 0
        is_sat = 1 if pick_wd == 5 and (dl_day <= 6 or has_priv_pick or day_load >= 0.82) else 0
        is_flu_same_day = ctx["fluActiveToday"] and dl_day == day_of(ctx["now"])
        is_flu_shortage_rollover = (
            ctx["fluActiveToday"] and not is_flu_same_day and self.supply.total_drivers < 720
        )

        if plan["premiumAny"] and Q30 == 0 and (Q65 < 10 or lead_hours < 12):
            return None
        if Q65 <= 3 and plan["totalRoadKm"] > 450 and lead_hours < 36:
            return None
        if plan["privateDeliveryCount"] > 0 and len(request["legs"]) == 1 and (Q65 < 6 or lead_hours < 3.5):
            return None
        if lead_hours < 2.0 and Q30 < 25:
            return None

        hub_pool_threshold = min(80, jround(self.supply.total_drivers * 0.095))
        is_arctic_sink = far_place_id in ARCTIC_SINKS
        is_northern_sink = far_place_id in NORTHERN_SINKS
        is_any_sink = is_arctic_sink or is_northern_sink
        shortage_frac = max(0, min(1.1, (780 - self.supply.total_drivers) / 135))
        if not same_cluster30:
            sink_eta_lift = (
                (0.85 if is_arctic_sink else 0.35 if is_northern_sink
                 else 0.18 if D_pool30 < 30 and plan["totalRoadKm"] > 220 else 0)
                + (0.35 if is_any_sink and option["kind"] == "same_day" else 0)
                + (0.55 if plan["totalRoadKm"] > 300 and (is_any_sink or D_pool30 < 25)
                   and option["kind"] == "next_day" else 0)
            )
        else:
            sink_eta_lift = 0

        eta_late = (
            2.55
            - 0.82 * math.log(Q30 + 1)
            + (0.85 if Q30 == 0 else 0)
            - 0.16 * math.log(D_pool30 + 1)
            + 0.75 * same_cluster30
            + 0.12 * road_hours
            + 0.48 * over4h
            - 1.42 * math.log(lead_hours)
            + 0.28 * is_fri
            + 0.55 * is_sat
            + (0.60 if len(request["legs"]) == 1 and plan["privateDeliveryCount"] > 0 else 0)
            + ((0.60 + (0.40 if plan["totalRoadKm"] >= 220 else 0)) if len(request["legs"]) == 2 else 0)
            + (0.50 if plan["needsChargingAny"] else 0)
            + (0.38 if plan["snowOverlap"] else 0)
            + (0.32 if is_flu_same_day else 0.12 if is_flu_shortage_rollover else 0)
            + 0.30 * shortage_frac
            + sink_eta_lift
            + 0.85 * math.log(open30 + 1)
            + (1.4 * (day_load - 0.80) if day_load > 0.80 else 0)
            + (0.55 * (batch_load - 0.65) if batch_load > 0.65 else 0)
        )

        p_late = sigmoid(eta_late)

        dealer = self.estimator.get_dealer(request["dealerId"])
        progress = request_progress_fraction(ctx["now"])
        start_prog = request_progress_fraction(co(ctx.get("startMinute"), 0))
        rel_progress = max(0, progress - start_prog)

        prior_weekly_reqs = 75 if dealer["totalRequestsSeen"] >= 4 else 28
        denom_prog = max(0.01, rel_progress) + 0.05
        est_weekly_reqs = (dealer["totalRequestsSeen"] + prior_weekly_reqs * 0.05) / denom_prog
        in_flight_same_dealer = (
            ctx["inFlightDealerOrders"](request["dealerId"]) if ctx.get("inFlightDealerOrders") is not None else 0
        )
        proj_trust = min(25, dealer["trust"] + jround(in_flight_same_dealer))
        is_vip_franchise = self.level == 8 and (est_weekly_reqs >= 55 or dealer["trust"] >= 8 or proj_trust >= 10)

        eff_delivered_total = ctx["deliveredOrdersTotal"] + co(ctx.get("overdueUndeliveredCount"), 0)
        current_on_time = (ctx["deliveredOnTimeTotal"] + 38) / (eff_delivered_total + 40)
        max_allowed_p_late = (
            0.018 if current_on_time < 0.912 else
            0.045 if current_on_time < 0.924 else
            0.090 if current_on_time < 0.940 else 0.135
        )

        if is_vip_franchise and progress < 0.88 and option["kind"] == "same_day" and len(request["options"]) > 1:
            max_allowed_p_late = min(max_allowed_p_late, 0.058 if proj_trust >= 12 else 0.072)
        if p_late > max_allowed_p_late:
            return None

        fee_mult = 0.86
        if (
            D_pool30 >= hub_pool_threshold
            and Q30 >= 40
            and not plan["premiumAny"]
            and plan["privatePickupCount"] == 0
            and plan["privateDeliveryCount"] == 0
            and plan["totalRoadKm"] <= 240
        ):
            fee_mult -= 0.045
        if not same_cluster30:
            if is_arctic_sink:
                fee_mult += 0.28 + 0.05 * min(1.5, max(0, plan["totalRoadKm"] - 220) / 300)
            elif is_northern_sink:
                scarcity_add = 0.04 if D_pool30 <= 5 else 0.02 if D_pool30 <= 15 else 0
                fee_mult += 0.08 + scarcity_add + 0.03 * min(1.2, max(0, plan["totalRoadKm"] - 220) / 220)
            elif D_pool30 <= 5:
                fee_mult += 0.08
            elif D_pool30 <= 15:
                fee_mult += 0.04
            elif D_pool30 < 65 and plan["totalRoadKm"] > 220:
                fee_mult += 0.04
            if is_any_sink and shortage_frac > 0:
                fee_mult += 0.05 * shortage_frac

        if Q30 == 0:
            fee_mult += 0.12
        elif Q30 <= 5:
            fee_mult += 0.07
        elif Q30 <= 15:
            fee_mult += 0.03

        if plan["totalRoadKm"] > 260:
            fee_mult += 0.02 if D_pool30 >= hub_pool_threshold else 0.06
        if plan["privatePickupCount"] > 0 and len(request["legs"]) == 1:
            fee_mult += 0.15
        if plan["privateDeliveryCount"] > 0 and len(request["legs"]) == 1:
            fee_mult += 0.17
        if len(request["legs"]) == 2:
            fee_mult += 0.20
        if plan["premiumAny"]:
            fee_mult += 0.14 if Q30 >= 22 else 0.19
        if plan["needsChargingAny"]:
            fee_mult += 0.08
        if plan["needsPlatesAny"] or plan["manualRequired"]:
            fee_mult += 0.04
        if is_fri or is_sat:
            fee_mult += 0.07
        if over4h > 0:
            fee_mult += (0.02 if D_pool30 >= hub_pool_threshold else 0.035) * over4h
        if plan["snowOverlap"]:
            fee_mult += 0.14
        if is_flu_same_day:
            fee_mult += 0.10
        if batch_load > 0.65:
            fee_mult += 0.08 * (batch_load - 0.65)
        if lead_hours >= 8.5 and Q30 >= 22 and not plan["snowOverlap"] and not is_flu_same_day:
            fee_mult -= 0.04

        p_escalate = sigmoid(eta_late + 1.10)
        fee_mult += p_escalate * 0.34

        if (
            plan["totalRoadMinutes"] <= 250
            and not is_arctic_sink
            and ctx["hasArrivingDriverSynergy"](pickup_id, delivery_id, plan["earliestPickupAt"] - 60, plan["effectiveLastPickupAt"])
        ):
            fee_mult -= 0.14
        elif (
            len(request["legs"]) == 1
            and plan["totalRoadMinutes"] <= 215
            and not plan["premiumAny"]
            and plan["privatePickupCount"] == 0
            and plan["privateDeliveryCount"] == 0
        ):
            rt_credit = ctx["roundTripPartnerCredit"](
                pickup_id,
                delivery_id,
                plan["earliestPickupAt"],
                plan["effectiveLastPickupAt"],
                plan["effectiveDeadline"],
            )
            if rt_credit > 0:
                fee_mult -= 0.12 * min(1, rt_credit)

        fee_mult = max(0.71, fee_mult)
        expected_driver_fee = max(
            2600 if plan["premiumAny"] else 0,
            request["referenceFeeCents"] * fee_mult,
        )

        deliv_progress = min(1.0, request_progress_fraction(plan["effectiveDeadline"]))
        rem_wins_after_deliv = max(0, (1 - deliv_progress) * est_weekly_reqs * 0.38)
        halve_units = 0
        if self.level == 8 and proj_trust >= 2 and rem_wins_after_deliv > 0.2:
            t_at_deliv = min(25, proj_trust)
            t_half = jfloor(t_at_deliv / 2)
            steps = min(35, jround(rem_wins_after_deliv))
            for k in range(steps):
                halve_units += min(25, t_at_deliv + k) - min(25, t_half + k)
        heal_wins = min(8, rem_wins_after_deliv)
        sat_loss_units = 0.5 * heal_wins * 4.05 if self.level >= 4 and dealer["lateCount"] < 5.8 else 0
        franchise_loss_cents = min(16500, jround((halve_units + sat_loss_units) * 102))
        expected_risk_cost = p_late * (0.35 * option["listPriceCents"] * 1.45 + franchise_loss_cents)
        true_cost_cents = expected_driver_fee + expected_risk_cost

        drv = self.supply.total_drivers
        base_target_weekly = (
            max(295, min(475, jround(drv * (0.44 + 0.00018 * max(0, drv - 690)))))
            if self.level >= 7
            else max(450, min(640, jround(drv * 0.26)))
        )

        soft_backlog = max(10, drv * 0.030)
        backlog_excess = max(0, (ctx["unbookedOrdersCount"] - soft_backlog) / 16)
        if self.level >= 7:
            health_mult = max(
                0.86,
                min(
                    1.08,
                    1.0
                    + 0.08 * max(0, min(1, (current_on_time - 0.955) / 0.025)) * max(0, 1 - backlog_excess)
                    - 0.10 * min(1.4, backlog_excess)
                    - (2.8 * (0.942 - current_on_time) if current_on_time < 0.942 else 0)
                    - (0.04 if ctx["fluActiveToday"] and self.supply.total_drivers < 720 else 0),
                ),
            )
        else:
            health_mult = 1.0
        target_weekly = jround(base_target_weekly * health_mult)
        expected_won_now = target_weekly * rel_progress
        pace_ratio = (ctx["wonOrdersTotal"] + 16) / (expected_won_now + 16)

        local_sat = (open30 + 0.5 * pending30) / max(2.5, Q30 * 0.28)
        day_sat = max(0, day_load - 0.64)
        batch_sat = max(0, batch_load - 0.55)

        shadow_mult = (
            0.20 * max(0, pace_ratio - 0.72)
            + 0.34 * max(0, pace_ratio - 1.02)
            + 0.24 * backlog_excess * backlog_excess
            + 0.22 * local_sat * local_sat
            + 0.52 * day_sat * day_sat
            + 0.32 * batch_sat * batch_sat
        )
        if is_flu_same_day:
            shadow_mult += 0.06
        if lead_hours < 5:
            shadow_mult *= 1.18

        slot_shadow_unit_cents = 520 + jround(135 * road_hours + 0.24 * request["referenceFeeCents"])
        if self.level >= 7:
            ref_shadow_cents = jround(slot_shadow_unit_cents * min(1.45, shadow_mult * 1.45))
        else:
            ref_shadow_cents = jround(request["referenceFeeCents"] * min(0.65, shadow_mult))

        trust_bonus_cents = 0
        if (
            self.level == 8
            and not self.estimator.price_war_today
            and proj_trust < 25
            and p_late <= 0.030
            and deliv_progress < 0.78
            and pace_ratio < 1.05
        ):
            gain_units = min(25 - proj_trust, rem_wins_after_deliv)
            opt_bonus_cap = 420 if option["kind"] == "same_day" else 280
            trust_bonus_cents = min(
                opt_bonus_cap,
                jround(request["referenceFeeCents"] * 0.18),
                jround(gain_units * 36),
            )

        base_effective_cost_cents = max(
            request["referenceFeeCents"] * 0.62,
            max(request["referenceFeeCents"] * 0.75, true_cost_cents + ref_shadow_cents) - trust_bonus_cents,
        )

        return {
            "option": option,
            "plan": plan,
            "trueCostCents": true_cost_cents,
            "baseEffectiveCostCents": base_effective_cost_cents,
            "paceRatio": pace_ratio,
            "dayLoad": day_load,
            "pLate": p_late,
        }

    def compute_option_menu_bounds(self, request, ev, tilde_c_nd_cents) -> dict:
        target_scale = tilde_c_nd_cents * option_multiplier(ev["option"]["kind"])
        day_idx = day_of(request["arrivedAt"])
        tod = request["arrivedAt"] % DAY
        in_hours = tod >= 8 * HOUR and tod <= 18 * HOUR
        normal_scale = (
            target_scale / 0.80 if in_hours and self.level == 8 and self.estimator.price_war_today else target_scale
        )

        pickup_id = request["legs"][0]["pickup"]["placeId"]
        in_outage_zone = False
        if in_hours and self.estimator.outage_center_today:
            s = self.map.within80km_set.get(self.estimator.outage_center_today)
            in_outage_zone = s is not None and pickup_id in s
        d = self.estimator.get_dealer(request["dealerId"])
        last12 = d["priorOutcomes"][-12:]
        if len(last12) >= 8:
            tot = 0
            for v in last12:
                tot = tot + v
            recent_dealer_win_rate = tot / len(last12)
        else:
            recent_dealer_win_rate = 0.40
        anti_retal_shadow = (
            jround(normal_scale * min(0.035, 0.14 * (recent_dealer_win_rate - 0.58) * (1 - 0.18 * day_idx)))
            if not in_outage_zone and day_idx < 4 and recent_dealer_win_rate > 0.64
            else 0
        )

        raw_gross_margin_ratio = (normal_scale - ev["trueCostCents"]) / max(1, normal_scale)
        wide_spread_lift = 0.32 * (raw_gross_margin_ratio - 0.42) if raw_gross_margin_ratio > 0.42 else 0
        outage_harvest_lift = 0.14 if in_outage_zone else 0
        if self.level >= 7:
            surplus_frac = min(
                0.72,
                max(
                    0,
                    0.28 * max(0, ev["paceRatio"] - 0.68)
                    + 0.38 * max(0, ev["paceRatio"] - 1.00)
                    + (0.30 * (ev["dayLoad"] - 0.70) if ev["dayLoad"] > 0.70 else 0)
                    + wide_spread_lift
                    + outage_harvest_lift,
                ),
            )
        else:
            surplus_frac = 0
        surplus_shadow = surplus_frac * max(0, normal_scale - ev["trueCostCents"])

        plan = ev["plan"]
        pick_wd = weekday_of_day(day_of(plan["earliestPickupAt"]))
        dl_day = day_of(plan["effectiveDeadline"])
        dl_wd = weekday_of_day(dl_day)

        hidden_fri_exec_cost = (
            jround(request["referenceFeeCents"] * (0.065 + 0.11 * max(0, ev["dayLoad"] - 0.55)))
            if dl_wd == 4 and pick_wd != 4
            else 0
        )

        can_bundle_clean = (
            len(request["legs"]) == 1
            and not plan["premiumAny"]
            and plan["privatePickupCount"] == 0
            and plan["privateDeliveryCount"] == 0
            and plan["totalRoadMinutes"] <= 240
        )
        same_day_slack_forfeit = (
            jround(
                request["referenceFeeCents"]
                * ((0.055 if can_bundle_clean else 0.02) + (0.03 if plan["totalRoadKm"] > 90 and pick_wd != 3 else 0))
            )
            if ev["option"]["kind"] == "same_day"
            else 0
        )

        in_flight_d = min(25, d["trust"] + (2 if ev["option"]["kind"] == "within_3_days" else 0))
        trust_delay_cost = (
            min(280, jround(request["referenceFeeCents"] * 0.035 + 90))
            if ev["option"]["kind"] == "within_3_days" and self.level == 8 and in_flight_d < 24
            and dl_day < 7 and plan["totalRoadKm"] < 300
            else 0
        )

        true_cost = ev["trueCostCents"] + hidden_fri_exec_cost
        eff_cost = (
            ev["baseEffectiveCostCents"]
            + surplus_shadow
            + anti_retal_shadow
            + hidden_fri_exec_cost
            + same_day_slack_forfeit
            + trust_delay_cost
        )

        min_margin_floor = (
            max(650, jround(request["referenceFeeCents"] * 0.16))
            if in_hours and self.level == 8 and self.estimator.price_war_today
            else 450
        )
        min_p = jceil(max(true_cost + min_margin_floor, eff_cost + 120))
        max_p = max(min_p + 500, jround(target_scale * 1.44))

        return {"minP": min_p, "maxP": max_p, "effCost": eff_cost, "trueCost": true_cost,
                "dlDay": dl_day, "dlWd": dl_wd, "dayLoad": ev["dayLoad"]}

    def quote_request(self, request, notes, ctx):
        d = self.estimator.get_dealer(request["dealerId"])
        d["totalRequestsSeen"] += 1

        leg_road_kms = [self.map.road_km(l["pickup"]["placeId"], l["delivery"]["placeId"]) for l in request["legs"]]

        if self.level <= 3:
            first_opt = request["options"][0] if request["options"] else None
            if not first_opt:
                return None
            ev = self.evaluate_option(request, first_opt, notes, ctx)
            if not ev or first_opt["listPriceCents"] <= ev["trueCostCents"] + 200:
                return None
            return {
                "request": request,
                "legRoadKms": leg_road_kms,
                "prices": {first_opt["kind"]: first_opt["listPriceCents"]},
                "competitiveOptions": [first_opt["kind"]],
                "fasterOptionUnquoted": False,
                "expectedWinProb": 1.0,
                "expectedWinsByDeadlineDay": [{"deadlineDay": day_of(ev["plan"]["effectiveDeadline"]), "expectedWins": 1.0}],
            }

        evals: dict = {}
        for opt in request["options"]:
            ev = self.evaluate_option(request, opt, notes, ctx)
            if ev:
                evals[opt["kind"]] = ev

        has_sd_offered = any(o["kind"] == "same_day" for o in request["options"])
        has_nd_offered = any(o["kind"] == "next_day" for o in request["options"])
        has_3d_offered = any(o["kind"] == "within_3_days" for o in request["options"])

        sd_ev = evals.get("same_day")
        nd_ev = evals.get("next_day")
        d3_ev = evals.get("within_3_days")

        if not sd_ev and not nd_ev and not d3_ev:
            decline_opt = request["options"][-1]
            return {
                "request": request,
                "legRoadKms": leg_road_kms,
                "prices": {decline_opt["kind"]: jround(decline_opt["listPriceCents"] * 7.0)},
                "competitiveOptions": [],
                "fasterOptionUnquoted": False,
                "expectedWinProb": 0,
                "expectedWinsByDeadlineDay": [],
            }

        pickup_id = request["legs"][0]["pickup"]["placeId"]
        delivery_id = (
            request["legs"][0]["delivery"]["placeId"] if len(request["legs"]) > 1
            else request["legs"][-1]["delivery"]["placeId"]
        )
        probe_nd = self.estimator.predict_option({
            "arrivedAt": request["arrivedAt"],
            "dealerId": request["dealerId"],
            "pickupId": pickup_id,
            "deliveryId": delivery_id,
            "legRoadKms": leg_road_kms,
            "refFeeCents": request["referenceFeeCents"],
            "opt": "next_day",
            "fasterOptionUnquoted": False,
            "quoteCents": max(100, request["referenceFeeCents"]),
        })
        tilde_c_nd = max(1, probe_nd["effMult"] * probe_nd["compCents"])

        sd_b = self.compute_option_menu_bounds(request, sd_ev, tilde_c_nd) if sd_ev else None
        nd_b = self.compute_option_menu_bounds(request, nd_ev, tilde_c_nd) if nd_ev else None
        d3_b = self.compute_option_menu_bounds(request, d3_ev, tilde_c_nd) if d3_ev else None

        def eval_menu_ev(p_sd, p_nd, p_3d):
            r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, p_sd, p_nd, p_3d)
            ev = 0
            if p_sd is not None and sd_b:
                ev += r["winSd"] * (p_sd - sd_b["effCost"])
            if p_nd is not None and nd_b:
                ev += r["winNd"] * (p_nd - nd_b["effCost"])
            if p_3d is not None and d3_b:
                ev += r["win3d"] * (p_3d - d3_b["effCost"])
            return r, ev

        def opt_solo(kind, b):
            if not b:
                return None

            def f(cand):
                r = evaluate_menu_choice(
                    has_sd_offered,
                    has_nd_offered,
                    has_3d_offered,
                    tilde_c_nd,
                    cand if kind == "same_day" else None,
                    cand if kind == "next_day" else None,
                    cand if kind == "within_3_days" else None,
                )
                w = r["winSd"] if kind == "same_day" else r["winNd"] if kind == "next_day" else r["win3d"]
                return w * (cand - b["effCost"])

            res = sweep_menu_grid(b["minP"], b["maxP"], 36, b["minP"], f)
            return {"p": res["bestP"], "ev": res["bestEv"]}

        solo_sd = opt_solo("same_day", sd_b)
        solo_nd = opt_solo("next_day", nd_b)
        solo_3d = opt_solo("within_3_days", d3_b)

        best_sd = None
        best_nd = None
        best_3d = None
        best_ev = -1e9
        best_choice = {"pWin": 0, "winSd": 0, "winNd": 0, "win3d": 0}

        def consider_menu(p_sd, p_nd, p_3d):
            nonlocal best_sd, best_nd, best_3d, best_ev, best_choice
            r, ev = eval_menu_ev(p_sd, p_nd, p_3d)
            if ev > best_ev:
                best_ev = ev
                best_sd = p_sd
                best_nd = p_nd
                best_3d = p_3d
                best_choice = r

        if solo_nd:
            consider_menu(None, solo_nd["p"], None)
        if not nd_b and solo_sd:
            consider_menu(solo_sd["p"], None, None)
        if not nd_b and not sd_b and solo_3d:
            consider_menu(None, None, solo_3d["p"])
        if nd_b and solo_sd and nd_b["dlWd"] == 4 and nd_b["dayLoad"] >= 0.85:
            consider_menu(solo_sd["p"], None, None)

        if sd_b and nd_b and solo_nd:
            is_thu_fri_bypass = sd_b["dlWd"] == 3 and nd_b["dlWd"] == 4
            min_sd_spread = (
                max(250, jround(sd_b["trueCost"] - nd_b["trueCost"] + 150))
                if is_thu_fri_bypass
                else max(400, jround(sd_b["effCost"] - nd_b["effCost"] + 150))
            )

            cur_nd = solo_nd["p"]
            sd_pct_floor = 0 if is_thu_fri_bypass else jround(cur_nd * 1.12)
            cur_sd = max(sd_b["minP"], cur_nd + min_sd_spread, sd_pct_floor)
            for _pass in range(2):
                dyn_pct_floor = 0 if is_thu_fri_bypass else jround(cur_nd * 1.12)
                lo_sd = max(sd_b["minP"], cur_nd + min_sd_spread, dyn_pct_floor)
                hi_sd = max(lo_sd + 200, sd_b["maxP"])

                def f_sd(cand_sd, cur_nd=cur_nd):
                    r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, cand_sd, cur_nd, None)
                    return r["winSd"] * (cand_sd - sd_b["effCost"]) + r["winNd"] * (cur_nd - nd_b["effCost"])

                cur_sd = sweep_menu_grid(lo_sd, hi_sd, 28, cur_sd, f_sd)["bestP"]

                lo_nd = nd_b["minP"]
                hi_nd_by_pct = INF if is_thu_fri_bypass else jfloor(cur_sd / 1.12)
                hi_nd = min(nd_b["maxP"], cur_sd - min_sd_spread, hi_nd_by_pct)
                if hi_nd >= lo_nd:
                    def f_nd(cand_nd, cur_sd=cur_sd):
                        r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, cur_sd, cand_nd, None)
                        return r["winSd"] * (cur_sd - sd_b["effCost"]) + r["winNd"] * (cand_nd - nd_b["effCost"])

                    cur_nd = sweep_menu_grid(lo_nd, hi_nd, 28, cur_nd, f_nd)["bestP"]
            consider_menu(cur_sd, cur_nd, None)

        if d3_b:
            if not nd_b:
                if sd_b and solo_sd and solo_3d and solo_sd["p"] >= solo_3d["p"] + 500:
                    consider_menu(solo_sd["p"], None, solo_3d["p"])
                elif solo_3d:
                    consider_menu(None, None, solo_3d["p"])
            elif (
                d3_b["dlWd"] != 4
                and (
                    nd_b["effCost"] - d3_b["effCost"] >= 260
                    or nd_b["dlWd"] == 4
                    or bool(nd_ev and nd_ev["pLate"] >= 0.045 and (d["trust"] >= 10 or nd_ev["plan"]["totalRoadKm"] >= 300))
                )
                and solo_nd
            ):
                base_ev_without_3d = best_ev
                anchor_sd = best_sd
                is_thu_fri_bypass_3d = bool(sd_b and sd_b["dlWd"] == 3 and nd_b["dlWd"] == 4)
                if sd_b and anchor_sd is not None:
                    if is_thu_fri_bypass_3d:
                        min_sd_spread = max(250, jround(sd_b["trueCost"] - nd_b["trueCost"] + 150))
                    else:
                        min_sd_spread = max(400, jround(sd_b["effCost"] - nd_b["effCost"] + 150))
                else:
                    min_sd_spread = 0

                cur_nd = co(best_nd, solo_nd["p"])
                cur_3d = min(d3_b["maxP"], cur_nd - 300)
                for _pass in range(2):
                    lo_3 = d3_b["minP"]
                    hi_3 = min(d3_b["maxP"], cur_nd - 300)
                    if hi_3 < lo_3:
                        break

                    def f_3(cand3, cur_nd=cur_nd):
                        r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, anchor_sd, cur_nd, cand3)
                        return (
                            (r["winSd"] * (anchor_sd - sd_b["effCost"]) if anchor_sd is not None and sd_b else 0)
                            + r["winNd"] * (cur_nd - nd_b["effCost"])
                            + r["win3d"] * (cand3 - d3_b["effCost"])
                        )

                    cur_3d = sweep_menu_grid(lo_3, hi_3, 24, cur_3d, f_3)["bestP"]

                    lo_nd = max(nd_b["minP"], cur_3d + 300)
                    hi_nd_by_pct = jfloor(anchor_sd / 1.12) if anchor_sd is not None and not is_thu_fri_bypass_3d else INF
                    hi_nd = min(nd_b["maxP"], anchor_sd - min_sd_spread, hi_nd_by_pct) if anchor_sd is not None else nd_b["maxP"]
                    if hi_nd >= lo_nd:
                        def f_n3(cand_nd, cur_3d=cur_3d):
                            r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, anchor_sd, cand_nd, cur_3d)
                            return (
                                (r["winSd"] * (anchor_sd - sd_b["effCost"]) if anchor_sd is not None and sd_b else 0)
                                + r["winNd"] * (cand_nd - nd_b["effCost"])
                                + r["win3d"] * (cur_3d - d3_b["effCost"])
                            )

                        cur_nd = sweep_menu_grid(lo_nd, hi_nd, 24, cur_nd, f_n3)["bestP"]

                final_sd = anchor_sd
                if sd_b and final_sd is not None:
                    dyn_pct_floor = 0 if is_thu_fri_bypass_3d else jround(cur_nd * 1.12)
                    lo_sd = max(sd_b["minP"], cur_nd + min_sd_spread, dyn_pct_floor)
                    hi_sd = max(lo_sd + 200, sd_b["maxP"])

                    def f_fs(cand_sd):
                        r = evaluate_menu_choice(has_sd_offered, has_nd_offered, has_3d_offered, tilde_c_nd, cand_sd, cur_nd, cur_3d)
                        return (
                            r["winSd"] * (cand_sd - sd_b["effCost"])
                            + r["winNd"] * (cur_nd - nd_b["effCost"])
                            + r["win3d"] * (cur_3d - d3_b["effCost"])
                        )

                    final_sd = sweep_menu_grid(lo_sd, hi_sd, 24, final_sd, f_fs)["bestP"]

                if cur_3d >= d3_b["minP"] and cur_3d <= cur_nd - 300:
                    r, ev = eval_menu_ev(final_sd, cur_nd, cur_3d)
                    if ev >= base_ev_without_3d + 25:
                        best_ev = ev
                        best_sd = final_sd
                        best_nd = cur_nd
                        best_3d = cur_3d
                        best_choice = r

        prices: dict = {}
        competitive_options: list = []
        if best_nd is not None:
            prices["next_day"] = best_nd
            competitive_options.append("next_day")
        if best_sd is not None:
            prices["same_day"] = best_sd
            competitive_options.append("same_day")
        if best_3d is not None:
            prices["within_3_days"] = best_3d
            competitive_options.append("within_3_days")

        if len(competitive_options) == 0:
            decline_opt = request["options"][-1]
            prices[decline_opt["kind"]] = jround(decline_opt["listPriceCents"] * 7.0)
            return {
                "request": request,
                "legRoadKms": leg_road_kms,
                "prices": prices,
                "competitiveOptions": [],
                "fasterOptionUnquoted": False,
                "expectedWinProb": 0,
                "expectedWinsByDeadlineDay": [],
            }

        fastest_offered = request["options"][0]["kind"]
        faster_option_unquoted = fastest_offered not in competitive_options

        by_day: dict = {}
        if best_sd is not None and sd_b and best_choice["winSd"] > 0:
            by_day[sd_b["dlDay"]] = co(by_day.get(sd_b["dlDay"]), 0) + best_choice["winSd"]
        if best_nd is not None and nd_b and best_choice["winNd"] > 0:
            by_day[nd_b["dlDay"]] = co(by_day.get(nd_b["dlDay"]), 0) + best_choice["winNd"]
        if best_3d is not None and d3_b and best_choice["win3d"] > 0:
            by_day[d3_b["dlDay"]] = co(by_day.get(d3_b["dlDay"]), 0) + best_choice["win3d"]
        expected_wins_by_deadline_day = [
            {"deadlineDay": deadline_day, "expectedWins": expected_wins} for deadline_day, expected_wins in by_day.items()
        ]

        return {
            "request": request,
            "legRoadKms": leg_road_kms,
            "prices": prices,
            "competitiveOptions": competitive_options,
            "fasterOptionUnquoted": faster_option_unquoted,
            "expectedWinProb": min(0.98, best_choice["pWin"]),
            "expectedWinsByDeadlineDay": expected_wins_by_deadline_day,
        }
