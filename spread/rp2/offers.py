"""Port of offers.ts (RoutePulse v21e): direct driver offers."""
from __future__ import annotations

import re

from .js import INF, isfinite, jceil, jround
from .rptime import DAY, HOUR, day_of, weekday_of_day
from .supply import is_experienced_driver

_REFUSE_DAILY = re.compile(r"per day|three|3\s*offer|daily|limit", re.IGNORECASE | re.ASCII)
_GIG = re.compile(r"gig", re.IGNORECASE | re.ASCII)


def evaluate_driver_commitments(m, d_comms, gig, exec_day):
    day_drive_mins = 0
    overlaps = False
    chained = False

    for c in d_comms:
        if day_of(c["estStartAt"]) != exec_day:
            continue
        day_drive_mins += c["driveMinutes"]
        link = m.road_minutes(c["deliveryPlaceId"], gig["pickupPlaceId"])
        if c["estFinishAt"] + link <= gig["effectiveLastPickupAt"] - 15 and m.dist_km(c["deliveryPlaceId"], gig["pickupPlaceId"]) <= 35:
            chained = True
        elif (
            gig["earliestPickupAt"] + gig["driveMinutes"] + 30 + m.road_minutes(gig["deliveryPlaceId"], c["pickupPlaceId"])
            <= c["estStartAt"]
        ):
            pass  # Fits cleanly before existing commitment
        else:
            overlaps = True

    return {"dayDriveMins": day_drive_mins, "overlaps": overlaps, "chained": chained}


def compute_offer_fee_cents(params):
    gig = params["gig"]
    chained = params["chained"]
    v_info = params["vInfo"]
    is_repeat_viewer = params["isRepeatViewer"]
    is_single_viewer = params["isSingleViewer"]
    is_dense_hub_solo = params["isDenseHubSolo"]
    is_urgent = params["isUrgent"]
    is_scarce = params["isScarce"]
    slack_min = params["slackMin"]
    dist_p = params["distP"]
    dist_d = params["distD"]
    dest_pool30 = params["destPool30"]
    same_cluster = params["sameCluster"]
    is_evening_or_sat = params["isEveningOrSat"]
    same_day_exec = params["sameDayExec"]

    cur = gig["currentAppFeeCents"]

    if len(gig["orderIds"]) > 1:
        base_cap_ratio = 0.64 if len(gig["orderIds"]) >= 3 else 0.72
        extra_ratio = (0.10 if gig["audience"]["experienced"] else 0) + (0.05 if gig["hasPrivateStop"] else 0)
        max_bundle_cap = jround(gig["refFeeCents"] * (base_cap_ratio + extra_ratio))
        target_bundle_offer = jround(
            cur * (0.95 if chained else (1.03 if v_info else 1.01 + gig["offerWave"] * 0.03))
        )
        if chained:
            return min(max_bundle_cap, max(jround(cur * 0.94), target_bundle_offer))
        return max(cur, min(max_bundle_cap, target_bundle_offer))

    if chained and dist_d <= 30:
        mult = 0.88
    elif chained:
        mult = 0.94
    elif dist_d <= 30 and dist_p > 30:
        mult = 1.00 if (is_scarce or v_info) else 0.97
    elif dist_p <= 30 and dist_d <= 30:
        mult = 0.96
    elif dist_p <= 30:
        mult = 1.00
    else:
        mult = 1.08 if is_scarce else 1.03

    if gig["driveMinutes"] > 195:
        mult += 0.06
    if gig["driveMinutes"] > 290:
        mult += 0.05
    if dest_pool30 <= 12 and not same_cluster:
        mult += 0.06
    if gig["hasPrivateStop"]:
        mult += 0.09
    if gig["audience"]["experienced"]:
        mult += 0.14
    if is_evening_or_sat:
        mult += 0.05
    if not same_day_exec:
        mult += 0.03
    mult += gig["offerWave"] * 0.08

    if gig["isPastDeadline"]:
        mult = max(mult, 1.55 + gig["offerWave"] * 0.22)
    elif is_urgent and slack_min <= 190:
        mult = max(mult, 1.38 + gig["offerWave"] * 0.15)
    elif is_scarce and slack_min <= 360:
        mult = max(mult, 1.15 + gig["offerWave"] * 0.09)

    raw_fee = jround(gig["refFeeCents"] * min(2.65, mult))
    if is_urgent and slack_min <= 190:
        return max(raw_fee, jround(cur * 1.04))
    if not is_urgent:
        tight_same_day = slack_min <= 380
        if is_repeat_viewer:
            floor_sweet = jround(cur * (1.04 if tight_same_day else (1.02 if is_dense_hub_solo else 1.03)))
            cap_sweet = jround(cur * (1.10 if tight_same_day else (1.05 if is_dense_hub_solo else 1.08)))
            return max(floor_sweet, min(raw_fee, cap_sweet))
        if is_single_viewer:
            floor_sweet = jround(cur * (1.03 if tight_same_day else 1.015))
            cap_sweet = jround(cur * (1.07 if tight_same_day else 1.055))
            return max(floor_sweet, min(raw_fee, cap_sweet))
        if chained:
            cap_chained = jround(cur * (1.06 if tight_same_day else 1.03 + gig["offerWave"] * 0.04))
            return max(cur, min(raw_fee, cap_chained))
        cap_non_urgent = jround(cur * (1.10 if tight_same_day else 1.06 + gig["offerWave"] * 0.05))
        return max(cur, min(raw_fee, cap_non_urgent))
    return max(raw_fee, cur)


class DirectOfferTracker:
    def __init__(self):
        self.last_active_at = {}
        self.gig_viewers = {}
        self.booked_or_delivered_day = {}  # Map<string, Set<string>>, membership only
        self.recent_deliveries = {}
        self.offers_sent_by_day = {}
        self.open_offers_by_gig = {}
        self.global_open_offer_drivers = set()  # membership only
        self.attempted_gig_drivers = set()  # membership only
        self.refused_pair_until = {}
        self.declined_max_fee = {}

    def mark_worked_on_day(self, driver_id, at):
        day_key = str(day_of(at))
        s = self.booked_or_delivered_day.get(day_key)
        if not s:
            s = set()
            self.booked_or_delivered_day[day_key] = s
        s.add(driver_id)

    def release_global_driver_if_idle(self, driver_id):
        for mm in self.open_offers_by_gig.values():
            if driver_id in mm:
                return
        self.global_open_offer_drivers.discard(driver_id)

    def record_view(self, driver_id, at, gig_id=None):
        prev = self.last_active_at.get(driver_id)
        if prev is None:
            prev = -INF
        if at > prev:
            self.last_active_at[driver_id] = at
        if gig_id:
            by_gig = self.gig_viewers.get(gig_id)
            if by_gig is None:
                by_gig = {}
                self.gig_viewers[gig_id] = by_gig
            cur = by_gig.get(driver_id)
            if cur:
                cur["lastAt"] = max(cur["lastAt"], at)
                cur["count"] += 1
            else:
                by_gig[driver_id] = {"firstAt": at, "lastAt": at, "count": 1}

    def record_booked(self, driver_id, gig_id, at):
        self.record_view(driver_id, at)
        self.mark_worked_on_day(driver_id, at)
        self.clear_gig(gig_id)

    def record_delivered(self, driver_id, place_id, at):
        if not driver_id:
            return
        self.record_view(driver_id, at)
        self.mark_worked_on_day(driver_id, at)
        self.recent_deliveries[driver_id] = {"placeId": place_id, "at": at}

    def record_offer_queued(self, gig_id, driver_id, fee_cents, now):
        day_key = f"{day_of(now)}:{driver_id}"
        self.offers_sent_by_day[day_key] = self.offers_sent_by_day.get(day_key, 0) + 1
        op = self.open_offers_by_gig.get(gig_id)
        if op is None:
            op = {}
            self.open_offers_by_gig[gig_id] = op
        op[driver_id] = fee_cents
        self.global_open_offer_drivers.add(driver_id)
        self.attempted_gig_drivers.add(f"{gig_id}:{driver_id}")

    def rollback_offer_refused(self, gig_id, driver_id, now, reason=""):
        day_key = f"{day_of(now)}:{driver_id}"
        op = self.open_offers_by_gig.get(gig_id)
        if op is not None:
            op.pop(driver_id, None)
        self.release_global_driver_if_idle(driver_id)
        if _REFUSE_DAILY.search(reason) and not _GIG.search(reason):
            self.offers_sent_by_day[day_key] = 3
        else:
            cur = self.offers_sent_by_day.get(day_key, 0)
            if cur > 0:
                self.offers_sent_by_day[day_key] = cur - 1
        self.refused_pair_until[f"{gig_id}:{driver_id}"] = now + 25
        self.attempted_gig_drivers.add(f"{gig_id}:{driver_id}")

    def record_offer_answered(self, gig_id, driver_id, answer):
        op = self.open_offers_by_gig.get(gig_id)
        offered_fee = op.get(driver_id) if op is not None else None
        if offered_fee is None:
            offered_fee = 0
        if op is not None:
            op.pop(driver_id, None)
        self.release_global_driver_if_idle(driver_id)
        if answer == "accepted":
            self.clear_gig(gig_id)
        elif answer == "declined" and offered_fee > 0:
            key = f"{gig_id}:{driver_id}"
            self.declined_max_fee[key] = max(self.declined_max_fee.get(key, 0), offered_fee)

    def clear_gig(self, gig_id):
        op = self.open_offers_by_gig.get(gig_id)
        if op is not None:
            del self.open_offers_by_gig[gig_id]
            for driver_id in list(op.keys()):
                self.release_global_driver_if_idle(driver_id)
        self.gig_viewers.pop(gig_id, None)

    def offers_today(self, driver_id, now):
        return self.offers_sent_by_day.get(f"{day_of(now)}:{driver_id}", 0)

    def open_count(self, gig_id):
        op = self.open_offers_by_gig.get(gig_id)
        return len(op) if op is not None else 0

    def select_offers_for_gig(self, m, supply, commitments, gig, now, level, max_new_offers=2):
        if level < 3:
            return []
        tod = now % DAY
        if tod < 7 * HOUR or tod > 22 * HOUR + 45:
            return []

        slots_left = min(max_new_offers, 3 - self.open_count(gig["gigId"]))
        if slots_left <= 0:
            return []

        pick_pool30 = supply.pool30(gig["pickupPlaceId"], gig["audience"]["experienced"], gig["audience"]["manualLicence"])
        is_scarce = pick_pool30 <= 8
        slack_min = gig["effectiveLastPickupAt"] - now
        is_dense_hub_solo = len(gig["orderIds"]) == 1 and pick_pool30 >= 45 and slack_min > 300
        is_urgent = bool(gig["urgent"] or gig["isPastDeadline"] or slack_min <= 220)

        exec_at = max(now, gig["earliestPickupAt"])
        exec_day = day_of(exec_at)
        exec_wd = weekday_of_day(exec_day)
        is_evening_or_sat = exec_wd == 5 or (exec_at % DAY) >= 17 * HOUR
        same_day_exec = exec_day == day_of(now)
        worked_today_set = self.booked_or_delivered_day.get(str(day_of(now)))
        gig_viewers_map = self.gig_viewers.get(gig["gigId"])

        by_driver = {}
        for c in commitments:
            arr = by_driver.get(c["driverId"])
            if arr is None:
                arr = []
                by_driver[c["driverId"]] = arr
            arr.append(c)

        dest_pool30 = supply.pool30(gig["deliveryPlaceId"], False, False)
        same_cluster = m.is_same_cluster30(gig["pickupPlaceId"], gig["deliveryPlaceId"])
        scored = []

        for d in supply.drivers:
            pair_key = f"{gig['gigId']}:{d['id']}"
            if d["id"] in self.global_open_offer_drivers:
                continue
            ru = self.refused_pair_until.get(pair_key)
            if (-INF if ru is None else ru) > now:
                continue
            if not is_urgent and pair_key in self.attempted_gig_drivers:
                continue
            used_today = self.offers_today(d["id"], now)
            if used_today >= 3:
                continue

            is_exp = is_experienced_driver(d)
            if gig["audience"]["experienced"] and not is_exp:
                continue
            if gig["audience"]["manualLicence"] and d["licence"] != "manual":
                continue

            la = self.last_active_at.get(d["id"])
            last_act = -INF if la is None else la
            mins_since_act = now - last_act
            worked_today = bool(worked_today_set is not None and d["id"] in worked_today_set)

            fit = evaluate_driver_commitments(m, by_driver.get(d["id"], []), gig, exec_day)
            if fit["overlaps"] or (fit["dayDriveMins"] > 0 and fit["dayDriveMins"] + gig["driveMinutes"] > 460):
                continue

            chained = fit["chained"]
            if not chained:
                recent = self.recent_deliveries.get(d["id"])
                if (
                    recent
                    and day_of(recent["at"]) == exec_day
                    and now - recent["at"] <= 180
                    and m.dist_km(recent["placeId"], gig["pickupPlaceId"]) <= 35
                ):
                    chained = True

            v_info = gig_viewers_map.get(d["id"]) if gig_viewers_map is not None else None
            is_repeat_viewer = bool(v_info and v_info["count"] >= 2 and now - v_info["lastAt"] <= 25)
            is_single_viewer = bool(v_info and v_info["count"] == 1 and now - v_info["lastAt"] <= 20)

            max_inactive_mins = 20 if v_info else (90 if (is_urgent or is_scarce) else 35)
            if not chained and mins_since_act > max_inactive_mins:
                continue

            dist_p = m.dist_km(d["homePlaceId"], gig["pickupPlaceId"])
            dist_d = m.dist_km(d["homePlaceId"], gig["deliveryPlaceId"])
            is_home_return_viewer = bool(v_info and dist_d <= 30 and dist_p > 30)

            if used_today >= 2 and not is_urgent and len(gig["orderIds"]) == 1 and not is_repeat_viewer and not is_home_return_viewer:
                continue
            if not is_urgent and is_dense_hub_solo and not chained and not is_repeat_viewer and not is_home_return_viewer:
                continue

            positioned_repeat_viewer = is_repeat_viewer and slack_min >= 45
            if not chained and not positioned_repeat_viewer and dist_p > 65 and dist_d > 30:
                continue
            if not is_urgent and not is_scarce and not chained and not v_info and dist_d > 30:
                continue
            if not is_urgent and not is_scarce and not chained and not v_info and dist_p <= 30 and dist_d <= 30:
                continue

            transit_min = (
                0 if (chained or positioned_repeat_viewer)
                else jceil(m.road_minutes(d["homePlaceId"], gig["pickupPlaceId"]) * 1.22)
            )
            if not chained and not positioned_repeat_viewer and now + transit_min + 15 > gig["effectiveLastPickupAt"]:
                continue

            match_score = -INF
            if chained and dist_d <= 30:
                match_score = 118
            elif chained:
                match_score = 98 if dist_p > 30 else 84
            elif dist_d == 0 and dist_p > 30:
                match_score = 90 - transit_min * 0.05
            elif dist_d <= 30 and dist_p > 30:
                match_score = 82 - transit_min * 0.05
            elif dist_p > 30 and dist_p <= 65:
                match_score = 74 if (is_scarce or is_urgent) else 52
            elif dist_p <= 30 and dist_d <= 30:
                match_score = 58
            elif dist_p <= 30:
                match_score = 66 if (is_urgent or is_scarce) else 46
            elif positioned_repeat_viewer:
                match_score = 62
            if not isfinite(match_score):
                continue

            if is_repeat_viewer:
                viewer_bonus = 54
            elif is_single_viewer and dist_d <= 30 and dist_p > 30:
                viewer_bonus = 46
            elif is_single_viewer:
                viewer_bonus = 30
            else:
                viewer_bonus = 0

            if mins_since_act <= 15:
                activity_bonus = 30
            elif mins_since_act <= 45:
                activity_bonus = 20
            else:
                activity_bonus = 16 if worked_today else 8

            drop_penalty = min(26, d["drops"] * 3.8)
            budget_penalty = used_today * 12
            exp_save_penalty = 8 if (not gig["audience"]["experienced"] and is_exp) else 0
            total_score = match_score + viewer_bonus + activity_bonus - drop_penalty - budget_penalty - exp_save_penalty

            if total_score < (52 if (is_urgent or is_scarce) else 78):
                continue

            fee_cents = compute_offer_fee_cents({
                "gig": gig,
                "chained": chained,
                "vInfo": v_info,
                "isRepeatViewer": is_repeat_viewer,
                "isSingleViewer": is_single_viewer,
                "isDenseHubSolo": is_dense_hub_solo,
                "isUrgent": is_urgent,
                "isScarce": is_scarce,
                "slackMin": slack_min,
                "distP": dist_p,
                "distD": dist_d,
                "destPool30": dest_pool30,
                "sameCluster": same_cluster,
                "isEveningOrSat": is_evening_or_sat,
                "sameDayExec": same_day_exec,
            })

            prev_declined = self.declined_max_fee.get(pair_key, 0)
            if fee_cents <= prev_declined + 50:
                continue

            scored.append({"driver": d, "score": total_score, "feeCents": max(1, fee_cents)})

        scored.sort(key=lambda s: -s["score"])
        return [
            {"type": "offer", "gigId": gig["gigId"], "driverId": s["driver"]["id"], "feeCents": s["feeCents"]}
            for s in scored[:slots_left]
        ]
