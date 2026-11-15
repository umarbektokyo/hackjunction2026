"""Port of bundling.ts (RoutePulse v21e): 2-3 order bundles."""
from __future__ import annotations

from .dispatch import normalize_steps
from .js import INF, co, isfinite, jceil, jround
from .planner import CHARGING_MINUTES, PLATES_MINUTES, visit_at
from .rptime import DAY, HOUR, clamp_out_of_night, day_of, day_start_of


def _g(n, key):
    """n?.key (None when n is undefined)."""
    return n.get(key) if n else None


def compute_two_order_bundle_split_at(posted_at, min_last_pickup):
    crosses_night = (
        isfinite(min_last_pickup)
        and day_of(min_last_pickup) > day_of(posted_at)
        and min_last_pickup - posted_at >= 600
    )
    if crosses_night:
        return min(min_last_pickup - 240, max(posted_at + 150, day_start_of(min_last_pickup) + 9 * HOUR + 15))
    return min(posted_at + 125, min_last_pickup - 210)


def is_clean_solo_bundle_leg(entry, now):
    if len(entry["order"]["legs"]) != 1:
        return False
    leg = entry["order"]["legs"][0]
    if leg["car"]["premium"] or leg["pickup"]["privateAddress"] or leg["delivery"]["privateAddress"]:
        return False
    n0 = entry["notes"][0] if entry["notes"] else None
    if co(_g(n0, "releasedAt"), 0) > now:
        return False
    return True


def is_eligible_two_bundle_first(entry, now):
    if len(entry["order"]["legs"]) != 1:
        return False
    leg = entry["order"]["legs"][0]
    if leg["pickup"]["privateAddress"] or leg["delivery"]["privateAddress"]:
        return False
    n0 = entry["notes"][0] if entry["notes"] else None
    if co(_g(n0, "releasedAt"), 0) > now:
        return False
    return True


def is_eligible_two_bundle_second(entry, now):
    if len(entry["order"]["legs"]) != 1:
        return False
    leg = entry["order"]["legs"][0]
    if leg["pickup"]["privateAddress"]:
        return False
    if leg["delivery"]["privateAddress"] and leg["delivery"]["window"]["to"] - now < 300:
        return False
    n0 = entry["notes"][0] if entry["notes"] else None
    if co(_g(n0, "releasedAt"), 0) > now:
        return False
    return True


def _win(stop):
    return stop.get("window")


def evaluate_ordered_bundle(m, snow, supply, a, b, now, flu_active):
    if a["order"]["id"] == b["order"]["id"]:
        return None
    if not is_eligible_two_bundle_first(a, now) or not is_eligible_two_bundle_second(b, now):
        return None

    leg1 = a["order"]["legs"][0]
    leg2 = b["order"]["legs"][0]
    n1 = a["notes"][0] if a["notes"] else None
    n2 = b["notes"][0] if b["notes"] else None
    has_priv_deliv2 = leg2["delivery"]["privateAddress"]

    P1 = leg1["pickup"]["placeId"]
    D1 = leg1["delivery"]["placeId"]
    P2 = leg2["pickup"]["placeId"]
    D2 = leg2["delivery"]["placeId"]

    if _g(n1, "summerTyres") and snow.overlaps(P1, D1, now, a["order"]["deadline"]):
        return None
    if _g(n2, "summerTyres") and snow.overlaps(P2, D2, now, b["order"]["deadline"]):
        return None

    r1 = m.road_minutes(P1, D1)
    dh = m.road_minutes(D1, P2)
    r2 = m.road_minutes(P2, D2)
    ret = m.road_minutes(D2, P1)
    total_road = r1 + dh + r2

    if dh > 50 or total_road > 675:
        return None

    experienced = bool(a["built"]["audience"]["experienced"] or b["built"]["audience"]["experienced"])
    manual_licence = bool(a["built"]["audience"]["manualLicence"] or b["built"]["audience"]["manualLicence"])
    pool_p1 = supply.pool30(P1, experienced, manual_licence)
    pool_d2 = supply.pool30(D2, False, False)

    if experienced and pool_p1 < 22:
        return None
    if has_priv_deliv2 and pool_p1 < 20:
        return None
    if manual_licence and pool_p1 < 30:
        return None
    if pool_p1 < 6 and supply.pool65(P1, experienced, manual_licence) < 20:
        return None

    if dh <= 45 and ret <= 50:
        tier = 1
    elif dh <= 50 and ret <= 135 and (ret <= 95 or pool_d2 >= 18):
        tier = 2
    else:
        return None

    min_last_pickup = min(a["built"]["effectiveLastPickupAt"], b["built"]["effectiveLastPickupAt"])
    if min_last_pickup - now < 260:
        return None

    p1_stop = a["built"]["stops"][0]
    d1_stop = a["built"]["stops"][1]
    p2_stop = b["built"]["stops"][0]
    d2_stop = b["built"]["stops"][1]

    h_p1 = co(_g(n1, "pickupHours"), leg1["pickup"].get("hours"))
    h_d1 = co(_g(n1, "deliveryHours"), leg1["delivery"].get("hours"))
    h_p2 = co(_g(n2, "pickupHours"), leg2["pickup"].get("hours"))
    h_d2 = co(_g(n2, "deliveryHours"), leg2["delivery"].get("hours"))

    eff_dl1 = min(a["order"]["deadline"], co(_g(n1, "noteDeadline"), INF),
                  _win(d1_stop)["to"] if _win(d1_stop) else INF)
    eff_dl2 = min(
        b["order"]["deadline"],
        co(_g(n2, "noteDeadline"), INF),
        _win(d2_stop)["to"] if _win(d2_stop) else INF,
        leg2["delivery"]["window"]["to"] if has_priv_deliv2 else INF,
    )

    p1_from = _win(p1_stop)["from"] if _win(p1_stop) else leg1["pickup"]["window"]["from"]
    p1_to = min(eff_dl1, _win(p1_stop)["to"] if _win(p1_stop) else a["order"]["deadline"])
    p2_from = _win(p2_stop)["from"] if _win(p2_stop) else leg2["pickup"]["window"]["from"]
    p2_to = min(eff_dl2, _win(p2_stop)["to"] if _win(p2_stop) else b["order"]["deadline"])

    extra1 = (PLATES_MINUTES if p1_stop.get("withPlates") else 0) + (CHARGING_MINUTES if p1_stop.get("withCharging") else 0)
    extra2 = (PLATES_MINUTES if p2_stop.get("withPlates") else 0) + (CHARGING_MINUTES if p2_stop.get("withCharging") else 0)

    snow1 = snow.overlaps(P1, D1, now, eff_dl1)
    snow2 = snow.overlaps(P2, D2, now, eff_dl2)
    drive1 = jceil(r1 * (1.32 if snow1 else 1.04))
    drive_dh = jceil(dh * (1.25 if (snow1 or snow2) else 1.02))
    drive2 = jceil(r2 * (1.32 if snow2 else 1.04))

    cur_day_start = day_start_of(now)
    p2_aligned_start = max(now + 45, p2_from - drive_dh - 15 - drive1 - extra1 - 15)
    start_candidates = [
        now + 60,
        p2_aligned_start,
        cur_day_start + DAY + 7 * HOUR + 15,
        cur_day_start + 2 * DAY + 7 * HOUR + 15,
    ]
    req_post_deliv_slack1 = 220 if (snow1 or snow2) else 175
    req_post_deliv_slack2 = 95 if has_priv_deliv2 else req_post_deliv_slack1
    feasible_sim = False
    for cand_start in start_candidates:
        if cand_start > min_last_pickup - 120:
            continue
        t_p1 = visit_at(max(cand_start, p1_from), p1_to, h_p1, 15)
        if not isfinite(t_p1):
            continue
        t_d1 = visit_at(max(t_p1 + 15 + extra1 + drive1, leg1["delivery"]["window"]["from"]), eff_dl1, h_d1, 15)
        if not isfinite(t_d1):
            continue
        t_fin1 = t_d1 + 15
        t_arr_p2 = t_fin1 + drive_dh
        t_p2 = visit_at(max(t_arr_p2, p2_from), p2_to, h_p2, 15)
        if not isfinite(t_p2) or t_p2 - t_arr_p2 > 90:
            continue
        t_d2 = visit_at(max(t_p2 + 15 + extra2 + drive2, leg2["delivery"]["window"]["from"]), eff_dl2, h_d2, 15)
        if not isfinite(t_d2):
            continue
        t_fin2 = t_d2 + 15
        if day_of(t_p1) != day_of(t_fin2):
            continue
        if eff_dl1 - t_fin1 < req_post_deliv_slack1 or eff_dl2 - t_fin2 < req_post_deliv_slack2:
            continue
        feasible_sim = True
        break
    if not feasible_sim:
        return None

    ref_sum = a["request"]["referenceFeeCents"] + b["request"]["referenceFeeCents"]
    ref_max = max(a["request"]["referenceFeeCents"], b["request"]["referenceFeeCents"])
    flu_today_bundle = bool(flu_active) and day_of(min_last_pickup) == day_of(now)
    mkt_mult = (
        1.0
        + (0.10 if (snow1 or snow2) else 0)
        + (0.06 if flu_today_bundle else 0)
        + (0.14 if experienced else 0)
        + (0.08 if has_priv_deliv2 else 0)
    )
    deep_slack_bundle = min_last_pickup - now >= 500 and not experienced and not has_priv_deliv2
    if deep_slack_bundle:
        coeffs = [0.50, 0.58, 0.67, 0.77, 0.86] if tier == 1 else [0.58, 0.66, 0.75, 0.84, 0.93]
    else:
        coeffs = [0.58, 0.66, 0.75, 0.85] if tier == 1 else [0.66, 0.74, 0.83, 0.93]

    crosses_night_bundle = day_of(min_last_pickup) > day_of(now) and min_last_pickup - now >= 600
    lpa_day_start = day_start_of(min_last_pickup)
    step_gap = 25 if deep_slack_bundle else 30
    ref_max_base = 0.80 if deep_slack_bundle else 0.90
    ref_max_slope = 0.07 if deep_slack_bundle else 0.08

    prev_step_at2 = now
    mapped = []
    for k, c in enumerate(coeffs):
        if k == 0:
            raw_step_at = now
        elif crosses_night_bundle and k >= 2:
            raw_step_at = max(prev_step_at2 + 20, max(now + k * 32, lpa_day_start + 7 * HOUR + 15 + (k - 2) * 45))
        else:
            raw_step_at = max(prev_step_at2 + 20, clamp_out_of_night(now + k * step_gap, k))
        prev_step_at2 = raw_step_at
        mapped.append({
            "at": raw_step_at,
            "feeCents": jround(max(c * ref_sum, (ref_max_base + ref_max_slope * k) * ref_max) * mkt_mult),
        })
    schedule = normalize_steps(mapped, now)

    split_at = compute_two_order_bundle_split_at(now, min_last_pickup)
    if split_at <= now + 35:
        return None

    if has_priv_deliv2:
        eff_lpa2 = min(b["built"]["effectiveLastPickupAt"], leg2["delivery"]["window"]["to"] - drive2 - extra2 - 25)
    else:
        eff_lpa2 = b["built"]["effectiveLastPickupAt"]
    max_p1_for_p2 = eff_lpa2 - drive_dh - 15 - drive1 - extra1 - 15
    bundle_stops = [*a["built"]["stops"], *b["built"]["stops"]]
    if (
        max_p1_for_p2 >= max(now + 45, p1_from + 20)
        and max_p1_for_p2 < (_win(p1_stop)["to"] if _win(p1_stop) else a["order"]["deadline"])
    ):
        bundle_stops[0] = {
            **p1_stop,
            "window": {
                "from": max(leg1["pickup"]["window"]["from"], p1_from),
                "to": min(p1_to, max_p1_for_p2),
            },
        }
    if has_priv_deliv2 and leg2["delivery"]["window"]["to"] > now + 60:
        bundle_stops[3] = {
            **d2_stop,
            "window": {
                "from": leg2["delivery"]["window"]["from"],
                "to": leg2["delivery"]["window"]["to"] + 15,
            },
        }

    expected_savings = ref_sum - schedule[0]["feeCents"]
    hub_bonus = min(600, pool_p1 * 2) - dh * 12 - ret * 6
    score = expected_savings + hub_bonus

    return {
        "plan": {
            "firstOrderId": a["order"]["id"],
            "secondOrderId": b["order"]["id"],
            "stops": bundle_stops,
            "audience": {"experienced": experienced, "manualLicence": manual_licence},
            "schedule": schedule,
            "tier": tier,
            "splitAt": split_at,
        },
        "score": score,
    }


def find_best_two_order_bundle(m, snow, supply, target, candidates, now, level, flu_active):
    if level < 3:
        return None
    best = None

    for cand in candidates:
        if cand["order"]["id"] == target["order"]["id"]:
            continue

        ab = evaluate_ordered_bundle(m, snow, supply, target, cand, now, flu_active)
        ba = evaluate_ordered_bundle(m, snow, supply, cand, target, now, flu_active)

        chosen = ab
        if ab and ba:
            pool_a = supply.pool30(target["order"]["legs"][0]["pickup"]["placeId"])
            pool_b = supply.pool30(cand["order"]["legs"][0]["pickup"]["placeId"])
            if min(pool_a, pool_b) < 25 and pool_b != pool_a:
                chosen = ba if pool_b > pool_a else ab
            else:
                chosen = ba if ba["score"] > ab["score"] else ab
        elif ba:
            chosen = ba

        if chosen and (best is None or chosen["score"] > best["score"]):
            best = chosen

    return best["plan"] if best else None


def try_extend_two_to_three_order_bundle(m, snow, supply, a, b, c, now, flu_active):
    # supply.totalDrivers is a getter -> method total_drivers
    if flu_active or supply.total_drivers < 760:
        return None
    entries = [a, b, c]
    for e in entries:
        if not is_clean_solo_bundle_leg(e, now):
            return None
        if _g(e["notes"][0] if e["notes"] else None, "summerTyres"):
            return None

    l1 = a["order"]["legs"][0]
    l2 = b["order"]["legs"][0]
    l3 = c["order"]["legs"][0]
    P1, D1 = l1["pickup"]["placeId"], l1["delivery"]["placeId"]
    P2, D2 = l2["pickup"]["placeId"], l2["delivery"]["placeId"]
    P3, D3 = l3["pickup"]["placeId"], l3["delivery"]["placeId"]

    r1 = m.road_minutes(P1, D1)
    dh1 = m.road_minutes(D1, P2)
    r2 = m.road_minutes(P2, D2)
    dh2 = m.road_minutes(D2, P3)
    r3 = m.road_minutes(P3, D3)
    ret = m.road_minutes(D3, P1)
    total_road = r1 + dh1 + r2 + dh2 + r3

    if dh1 > 32 or dh2 > 32 or ret > 90 or total_road > 440:
        return None
    manual_licence = any(e["built"]["audience"]["manualLicence"] for e in entries)
    pool_p1 = supply.pool30(P1, False, manual_licence)
    pool_d3 = supply.pool30(D3, False, False)
    if pool_p1 < 35 or (ret > 55 and pool_d3 < 45):
        return None

    min_lpa = min(e["built"]["effectiveLastPickupAt"] for e in entries)
    if min_lpa - now < 300:
        return None

    cur_day_start = day_start_of(now)
    start_candidates = [now + 60, cur_day_start + DAY + 7 * HOUR + 15]
    any_snow = False
    feasible3 = False

    for cand_start in start_candidates:
        if cand_start > min_lpa - 180:
            break
        cur_at = cand_start
        first_day = -1
        ok = True
        sim_snow = False
        for idx in range(3):
            e = entries[idx]
            prev_e = entries[idx - 1] if idx > 0 else None
            leg = e["order"]["legs"][0]
            n = e["notes"][0] if e["notes"] else None
            p_stop = e["built"]["stops"][0]
            d_stop = e["built"]["stops"][1]

            eff_dl = min(e["order"]["deadline"], co(_g(n, "noteDeadline"), INF),
                         _win(d_stop)["to"] if _win(d_stop) else INF)
            sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], now, eff_dl)
            if sw:
                sim_snow = True
            link_sw = (
                snow.overlaps(prev_e["order"]["legs"][0]["delivery"]["placeId"], leg["pickup"]["placeId"], now, eff_dl)
                if prev_e else None
            )
            if link_sw:
                sim_snow = True

            link = (
                jceil(m.road_minutes(prev_e["order"]["legs"][0]["delivery"]["placeId"], leg["pickup"]["placeId"])
                      * (1.25 if link_sw else 1.03))
                if prev_e else 0
            )
            arr_p = cur_at + link
            h_p = co(_g(n, "pickupHours"), leg["pickup"].get("hours"))
            h_d = co(_g(n, "deliveryHours"), leg["delivery"].get("hours"))
            p_from = _win(p_stop)["from"] if _win(p_stop) else leg["pickup"]["window"]["from"]
            p_to = min(eff_dl, _win(p_stop)["to"] if _win(p_stop) else e["order"]["deadline"])
            t_p = visit_at(max(arr_p, p_from), p_to, h_p, 15)
            if not isfinite(t_p) or (idx > 0 and t_p - arr_p > 75):
                ok = False
                break
            if idx == 0:
                first_day = day_of(t_p)

            extra = (PLATES_MINUTES if p_stop.get("withPlates") else 0) + (CHARGING_MINUTES if p_stop.get("withCharging") else 0)
            drv = jceil(m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"]) * (1.32 if sw else 1.04))
            t_d = visit_at(max(t_p + 15 + extra + drv, leg["delivery"]["window"]["from"]), eff_dl, h_d, 15)
            if not isfinite(t_d):
                ok = False
                break
            t_fin = t_d + 15
            if eff_dl - t_fin < 260 or day_of(t_fin) != first_day:
                ok = False
                break
            cur_at = t_fin
        if ok:
            feasible3 = True
            any_snow = sim_snow
            break
    if not feasible3:
        return None

    ref_sum = 0
    for e in entries:
        ref_sum = ref_sum + e["request"]["referenceFeeCents"]
    ref_max = max(e["request"]["referenceFeeCents"] for e in entries)
    mkt_mult = 1.0 + (0.10 if any_snow else 0) + (0.08 if flu_active else 0)
    coeffs = [0.52, 0.60, 0.69, 0.80]
    schedule = normalize_steps(
        [{"at": now if k == 0 else clamp_out_of_night(now + k * 30, k),
          "feeCents": jround(max(k_mult * ref_sum, (0.98 + 0.08 * k) * ref_max) * mkt_mult)}
         for k, k_mult in enumerate(coeffs)],
        now,
    )
    crosses_night3 = day_of(min_lpa) > day_of(now) and min_lpa - now >= 600
    if crosses_night3:
        split_at = min(min_lpa - 250, max(now + 150, day_start_of(min_lpa) + 9 * HOUR))
    else:
        split_at = min(now + 135, min_lpa - 220)
    if split_at <= now + 35:
        return None

    return {
        "firstOrderId": a["order"]["id"],
        "secondOrderId": b["order"]["id"],
        "stops": [*a["built"]["stops"], *b["built"]["stops"], *c["built"]["stops"]],
        "audience": {"experienced": False, "manualLicence": manual_licence},
        "schedule": schedule,
        "tier": 1,
        "splitAt": split_at,
    }
