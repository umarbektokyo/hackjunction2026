"""Stop planning, opening hours and the effective last pickup. Python port of planner.ts (RoutePulse v21e)."""
from __future__ import annotations

import math

from .js import INF, co, isfinite, jceil, jfloor, jround  # noqa: F401  (re-exported for convenience)
from .notes import create_default_leg_note
from .rptime import DAY, HOUR, day_of, opening_slot_for_day, shift_deadline_business_days

CHARGING_MINUTES = 40
PLATES_MINUTES = 30
CHARGING_ROUTE_KM = 200
MAX_MULTI_CAR_ROAD_MINUTES = 12 * HOUR

EMPTY_RETRY = {"pickupFrom": 0, "manualLicence": False, "plates": False}


def haversine_place_km(a, b) -> float:
    R = 6371
    d_lat = ((b["lat"] - a["lat"]) * math.pi) / 180
    d_lon = ((b["lon"] - a["lon"]) * math.pi) / 180
    s = math.sin(d_lat / 2) ** 2 + math.cos((a["lat"] * math.pi) / 180) * math.cos((b["lat"] * math.pi) / 180) * math.sin(d_lon / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(s), math.sqrt(1 - s))


def is_same_customer_trade_in(prev, nxt) -> bool:
    return bool(
        prev is not None
        and nxt is not None
        and prev["delivery"]["placeId"] == nxt["pickup"]["placeId"]
        and prev["delivery"]["privateAddress"]
        and nxt["pickup"]["privateAddress"]
    )


class MapGraph:
    def __init__(self, world_map):
        self.places_by_id = {p["id"]: p for p in world_map["places"]}
        self.roads = {(r["from"], r["to"]): r["minutes"] for r in world_map["roads"]}
        self.road_kms = {(r["from"], r["to"]): r["km"] for r in world_map["roads"]}
        self.within30km: dict = {}
        self.within30km_set: dict = {}   # Map<string, Set<string>>: sets are dicts (key -> True)
        self.within65km: dict = {}
        self.within80km_set: dict = {}
        for p in world_map["places"]:
            n30, n65, n80 = [], [], {}
            for q in world_map["places"]:
                d = 0 if p["id"] == q["id"] else haversine_place_km(p, q)
                if d <= 30.0:
                    n30.append(q["id"])
                if d <= 65.0:
                    n65.append(q["id"])
                if d <= 80.0:
                    n80[q["id"]] = True
            self.within30km[p["id"]] = n30
            self.within30km_set[p["id"]] = dict.fromkeys(n30, True)
            self.within65km[p["id"]] = n65
            self.within80km_set[p["id"]] = n80

    def road_minutes(self, a: str, b: str):
        return self.roads.get((a, b), INF)

    def road_km(self, a: str, b: str):
        return self.road_kms.get((a, b), INF)

    def dist_km(self, a: str, b: str):
        if a == b:
            return 0
        pa, pb = self.places_by_id.get(a), self.places_by_id.get(b)
        if pa is None or pb is None:
            return INF
        return haversine_place_km(pa, pb)

    def is_same_cluster30(self, a: str, b: str) -> bool:
        return self.dist_km(a, b) <= 30.0

    def needs_charging(self, car, a: str, b: str) -> bool:
        return bool(
            car["electric"]
            and car.get("chargePercent") is not None
            and car["chargePercent"] < 30
            and self.road_km(a, b) > CHARGING_ROUTE_KM
        )


class SnowTracker:
    def __init__(self):
        self.forecasts: list = []   # SnowWindow dicts {"from", "to", "places"}; places is a Set -> dict

    def add_forecast(self, frm, to, place_ids) -> None:
        for f in self.forecasts:
            if f["from"] == frm and f["to"] == to:
                for p in place_ids:
                    f["places"][p] = True
                return
        self.forecasts.append({"from": frm, "to": to, "places": dict.fromkeys(place_ids, True)})

    def overlaps(self, place_a, place_b, start_min, end_min):
        for f in self.forecasts:
            if end_min >= f["from"] and start_min < f["to"] and (place_a in f["places"] or place_b in f["places"]):
                return f
        return None

    def has_active_snow(self, place_id, at_min) -> bool:
        return any(at_min >= f["from"] and at_min < f["to"] and place_id in f["places"] for f in self.forecasts)


def visit_at(earliest, latest, hours, service):
    if earliest > latest:
        return INF
    if not hours:
        return earliest if earliest + service <= latest else INF
    start_day = day_of(earliest)
    end_day = day_of(latest)
    if not isfinite(start_day) or not isfinite(end_day):
        if not isfinite(start_day):
            return INF
        end_day = start_day + 30          # JS would loop to Infinity; no slot ever exists that far, stop safely
    day = start_day
    while day <= end_day:
        slot = opening_slot_for_day(hours, day)
        if slot:
            start = max(earliest, day * DAY + slot["opens"])
            close = min(latest, day * DAY + slot["closes"])
            if start + service <= close:
                return start
        day += 1
    return INF


def latest_open_before(t, hours, safety_buffer=0):
    if not hours:
        return t
    start_day = day_of(t)
    if not isfinite(start_day):
        return -INF           # JS never gets here (its loop would not end); no caller passes an infinite time
    day = start_day
    while day >= start_day - 7:
        slot = opening_slot_for_day(hours, day)
        if slot:
            open_at = day * DAY + slot["opens"]
            close_limit = day * DAY + slot["closes"] - 1 - safety_buffer
            if not (t < open_at):
                if close_limit >= open_at:
                    return min(t, close_limit)
        day -= 1
    return -INF


def _note_at(notes, i):
    return notes[i] if 0 <= i < len(notes) else None


def compute_option_plan(m, snow, legs, notes, raw_option_deadline, now, deadline_already_shifted=False):
    if len(legs) == 0:
        return None
    leg0 = legs[0]
    last_leg = legs[-1]
    note0 = _note_at(notes, 0)
    last_note = notes[-1] if len(notes) else None

    ready_shift_days = (
        max(0, day_of(note0["readyAt"]) - day_of(leg0["pickup"]["window"]["from"]))
        if (not deadline_already_shifted and note0)
        else 0
    )
    promised_deadline = (
        raw_option_deadline if last_leg["delivery"]["privateAddress"]
        else shift_deadline_business_days(raw_option_deadline, ready_shift_days)
    )

    note_dl = co(last_note["noteDeadline"] if last_note else None,
                 co(note0["noteDeadline"] if note0 else None, None))
    effective_deadline = min(promised_deadline, note_dl) if note_dl is not None else promised_deadline

    total_road_minutes = 0
    server_multi_car_road_minutes = 0
    total_road_km = 0
    private_pickup_count = 0
    private_delivery_count = 0
    needs_charging_any = False
    needs_plates_any = bool(note0 and note0["needsPlates"])
    manual_required = bool(note0 and note0["manualGearbox"])
    premium_any = any(l["car"]["premium"] for l in legs)
    summer_tyres = bool(note0 and note0["summerTyres"])
    snow_overlap = False

    at = now + 20
    earliest_pickup_at = 0
    for i in range(len(legs)):
        leg = legs[i]
        prev = legs[i - 1] if i > 0 else None
        n = _note_at(notes, i)
        same_customer = is_same_customer_trade_in(prev, leg)

        raw_server_link_road = 0 if prev is None else m.road_minutes(prev["delivery"]["placeId"], leg["pickup"]["placeId"])
        link_road = 0 if prev is None else (0 if same_customer else raw_server_link_road)
        drive_road = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        drive_km = m.road_km(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        if not isfinite(raw_server_link_road) or not isfinite(drive_road):
            return None

        total_road_minutes += link_road + drive_road
        server_multi_car_road_minutes += raw_server_link_road + drive_road
        total_road_km += drive_km + (0 if (prev is None or same_customer) else m.road_km(prev["delivery"]["placeId"], leg["pickup"]["placeId"]))
        if leg["pickup"]["privateAddress"]:
            private_pickup_count += 1
        if leg["delivery"]["privateAddress"]:
            private_delivery_count += 1

        charging = m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        if charging:
            needs_charging_any = True
        plates = i == 0 and needs_plates_any

        pick_hours = co(n["pickupHours"] if n else None, leg["pickup"].get("hours"))
        deliv_hours = co(n["deliveryHours"] if n else None, leg["delivery"].get("hours"))

        pick_earliest = max(
            at + link_road,
            leg["pickup"]["window"]["from"],
            co(n["readyAt"] if n else None, 0),
            co(n["releasedAt"] if n else None, 0),
        )
        pick_latest = (
            leg["pickup"]["window"]["to"] + (30 if same_customer else 0)
            if leg["pickup"]["privateAddress"]
            else effective_deadline
        )

        snow_win = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], pick_earliest, pick_earliest + drive_road + 60)
        if snow_win:
            snow_overlap = True
            if summer_tyres:
                pick_earliest = max(pick_earliest, snow_win["to"])

        pick_service = 0 if same_customer else 10
        pick_start = visit_at(pick_earliest, pick_latest, pick_hours, pick_service)
        if summer_tyres:
            it = 0
            while it < 8 and isfinite(pick_start):
                sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], pick_start, pick_start + drive_road + 45)
                if not sw:
                    break
                snow_overlap = True
                pick_earliest = max(pick_earliest + 1, sw["to"])
                pick_start = visit_at(pick_earliest, pick_latest, pick_hours, pick_service)
                it += 1
        if not isfinite(pick_start):
            return None
        if i == 0:
            earliest_pickup_at = pick_start

        snow_at_run = snow.overlaps(
            leg["pickup"]["placeId"],
            leg["delivery"]["placeId"],
            pick_start,
            pick_start + jceil(drive_road * 1.35) + 60,
        )
        if snow_at_run:
            snow_overlap = True
        eff_drive = jceil(drive_road * (1.32 if snow_at_run else 1.04))
        extra_minutes = (PLATES_MINUTES if plates else 0) + (CHARGING_MINUTES if charging else 0)

        deliv_earliest = max(pick_start + pick_service + extra_minutes + eff_drive, leg["delivery"]["window"]["from"])
        deliv_latest = (
            min(effective_deadline, leg["delivery"]["window"]["to"] + 30)
            if leg["delivery"]["privateAddress"]
            else effective_deadline
        )
        deliv_service = 10
        deliv_start = visit_at(deliv_earliest, deliv_latest, deliv_hours, deliv_service)
        if not isfinite(deliv_start):
            return None

        at = deliv_start + deliv_service

    can_single_gig = len(legs) == 1 or server_multi_car_road_minutes <= MAX_MULTI_CAR_ROAD_MINUTES

    latest_next_pickup = INF
    for i in range(len(legs) - 1, -1, -1):
        leg = legs[i]
        nxt = legs[i + 1] if i + 1 < len(legs) else None
        n = _note_at(notes, i)
        same_customer_next = is_same_customer_trade_in(leg, nxt)

        link_minutes = 0 if not nxt else (0 if same_customer_next else m.road_minutes(leg["delivery"]["placeId"], nxt["pickup"]["placeId"]))
        deliv_hours = co(n["deliveryHours"] if n else None, leg["delivery"].get("hours"))
        pick_hours = co(n["pickupHours"] if n else None, leg["pickup"].get("hours"))

        deliv_window_cap = leg["delivery"]["window"]["to"] + 30 if leg["delivery"]["privateAddress"] else effective_deadline
        deliv_cap = min(effective_deadline, deliv_window_cap, latest_next_pickup - link_minutes)
        close_buffer = 15 if deliv_hours else 0
        buffered_deliv_cap = (
            deliv_cap - 15
            if (not leg["delivery"]["privateAddress"] and note_dl is not None and deliv_cap <= note_dl)
            else deliv_cap
        )
        latest_deliv = latest_open_before(buffered_deliv_cap, deliv_hours, close_buffer)
        raw_latest_deliv = latest_open_before(deliv_cap, deliv_hours, 0)

        base_drive = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        snow_late = snow.overlaps(
            leg["pickup"]["placeId"],
            leg["delivery"]["placeId"],
            max(now, latest_deliv - base_drive * 2),
            latest_deliv,
        )
        eff_drive = jceil(base_drive * (1.30 if snow_late else 1.03))
        charging = CHARGING_MINUTES if m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"]) else 0
        plates = PLATES_MINUTES if (i == 0 and needs_plates_any) else 0
        pick_svc = 0 if i > 0 else 10

        pick_window_cap = (
            leg["pickup"]["window"]["to"] + (30 if i > 0 else 0)
            if leg["pickup"]["privateAddress"]
            else effective_deadline
        )
        pick_cap = min(latest_deliv - eff_drive - charging - plates - pick_svc, pick_window_cap)
        raw_pick_cap = min(raw_latest_deliv - base_drive - charging - plates, pick_window_cap)
        buffered_pickup = latest_open_before(pick_cap, pick_hours, 0)
        raw_pickup = latest_open_before(raw_pick_cap, pick_hours, 0)
        latest_next_pickup = (
            raw_pickup if (not snow_late and day_of(buffered_pickup) < day_of(raw_pickup)) else buffered_pickup
        )

    if not isfinite(latest_next_pickup) or latest_next_pickup < earliest_pickup_at - 5 or latest_next_pickup <= now + 20:
        return None

    pickup_slack_minutes = max(
        0,
        latest_next_pickup - max(now + 15, min(earliest_pickup_at, latest_next_pickup)),
    )
    raw_booking_window = max(0, latest_next_pickup - now)

    return {
        "promisedDeadline": promised_deadline,
        "effectiveDeadline": effective_deadline,
        "earliestPickupAt": earliest_pickup_at,
        "finishAt": at,
        "effectiveLastPickupAt": latest_next_pickup,
        "pickupSlackMinutes": max(
            pickup_slack_minutes,
            min(raw_booking_window, latest_next_pickup - earliest_pickup_at + (earliest_pickup_at - now)),
        ),
        "deliverySlackMinutes": max(0, effective_deadline - at),
        "totalRoadMinutes": total_road_minutes,
        "totalRoadKm": total_road_km,
        "privatePickupCount": private_pickup_count,
        "privateDeliveryCount": private_delivery_count,
        "needsChargingAny": needs_charging_any,
        "needsPlatesAny": needs_plates_any,
        "manualRequired": manual_required,
        "premiumAny": premium_any,
        "snowOverlap": snow_overlap,
        "canSingleGig": can_single_gig,
    }


def hours_narrowed(real_hours, stated_hours) -> bool:
    if not real_hours or not stated_hours:
        return False
    return real_hours["opens"] > stated_hours["opens"] or real_hours["closes"] < stated_hours["closes"]


def next_real_day_window(earliest, latest, real_hours, min_remaining_minutes):
    start_day = day_of(earliest)
    end_day = day_of(latest)
    if not isfinite(start_day):
        return None
    if not isfinite(end_day):
        end_day = start_day + 30
    day = start_day
    while day <= end_day:
        slot = opening_slot_for_day(real_hours, day)
        if slot:
            frm = max(earliest, day * DAY + slot["opens"])
            to = min(latest, day * DAY + slot["closes"])
            if to - frm >= min_remaining_minutes:
                return {"from": frm, "to": to}
        day += 1
    return None


def apply_first_leg_pickup_safety_cap(params):
    pickup_stop = params["pickupStop"]
    m = params["map"]
    snow = params["snow"]
    order = params["order"]
    leg_indices = params["legIndices"]
    notes = params["notes"]
    retries_by_leg = params["retriesByLeg"]
    real_pick_hours = params["realPickHours"]
    min_start = params["minStart"]
    effective_last_pickup_at = params["effectiveLastPickupAt"]
    now = params["now"]
    ends_at = params["endsAt"]
    omit_soft_pickup_cap = params["omitSoftPickupCap"]

    first_leg_idx = leg_indices[0]
    first_leg = order["legs"][first_leg_idx]
    last_leg_idx = leg_indices[-1]
    last_leg_obj = order["legs"][last_leg_idx]
    last_n = _note_at(notes, last_leg_idx)
    last_deliv_h = co(last_n["deliveryHours"] if last_n else None, last_leg_obj["delivery"].get("hours"))

    tot_road = 0
    extra_m = 0
    for k in range(len(leg_indices)):
        li = leg_indices[k]
        l_obj = order["legs"][li]
        n_obj = _note_at(notes, li)
        r_obj = retries_by_leg.get(li) or EMPTY_RETRY
        tot_road += m.road_minutes(l_obj["pickup"]["placeId"], l_obj["delivery"]["placeId"])
        if k > 0:
            prev_obj = order["legs"][leg_indices[k - 1]]
            if not is_same_customer_trade_in(prev_obj, l_obj):
                tot_road += m.road_minutes(prev_obj["delivery"]["placeId"], l_obj["pickup"]["placeId"])
            extra_m += 20
        if m.needs_charging(l_obj["car"], l_obj["pickup"]["placeId"], l_obj["delivery"]["placeId"]):
            extra_m += CHARGING_MINUTES
        n0 = _note_at(notes, 0)
        if (li == 0 and n0 and n0["needsPlates"]) or (n_obj and n_obj["needsPlates"]) or r_obj["plates"]:
            extra_m += PLATES_MINUTES

    end_world_sw = snow.overlaps(
        first_leg["pickup"]["placeId"],
        last_leg_obj["delivery"]["placeId"],
        max(now, ends_at - DAY),
        ends_at,
    )
    drive_with_sw = jceil(tot_road * (1.32 if end_world_sw else 1.06))
    end_world_deliv = latest_open_before(ends_at, last_deliv_h, 15) if last_deliv_h else ends_at - 15
    end_world_pick_cap = end_world_deliv - drive_with_sw - extra_m - 20

    tier24_deliv = (
        latest_open_before(order["deadline"] + DAY, last_deliv_h, 20)
        if last_deliv_h
        else order["deadline"] + DAY - 20
    )
    tier24_pick_cap = latest_open_before(tier24_deliv - drive_with_sw - extra_m - 20, real_pick_hours, 0)
    active_late_pick_cap = (
        min(tier24_pick_cap, end_world_pick_cap)
        if (now > order["lastPickupAt"] and isfinite(tier24_pick_cap) and tier24_pick_cap > max(now + 95, min_start + 35))
        else end_world_pick_cap
    )

    if (
        not omit_soft_pickup_cap
        and effective_last_pickup_at < order["lastPickupAt"]
        and effective_last_pickup_at > max(now + 75, min_start + 30)
    ):
        pw = pickup_stop.get("window")
        cur_from = co(pw["from"] if pw else None, min_start)
        cur_to = co(pw["to"] if pw else None, order["deadline"])
        capped_to = min(cur_to, effective_last_pickup_at)
        if capped_to >= cur_from + 20:
            pickup_stop["window"] = {"from": max(first_leg["pickup"]["window"]["from"], cur_from), "to": capped_to}
    elif (
        omit_soft_pickup_cap
        and isfinite(active_late_pick_cap)
        and active_late_pick_cap < ends_at - 30
        and active_late_pick_cap > max(now + 45, min_start + 25)
    ):
        pw = pickup_stop.get("window")
        cur_from = co(pw["from"] if pw else None, min_start)
        cur_to = co(pw["to"] if pw else None, ends_at - 30)
        capped_to = min(cur_to, active_late_pick_cap)
        if capped_to >= cur_from + 20:
            pickup_stop["window"] = {"from": max(first_leg["pickup"]["window"]["from"], cur_from), "to": capped_to}
    return tier24_pick_cap if isfinite(tier24_pick_cap) else None


def resolve_dealer_delivery_window(params):
    order = params["order"]
    idx = params["idx"]
    leg_indices = params["legIndices"]
    notes = params["notes"]
    pickup_stop = params["pickupStop"]
    drive_min = params["driveMin"]
    now = params["now"]
    ends_at = params["endsAt"]
    omit_soft_pickup_cap = params["omitSoftPickupCap"]

    leg = order["legs"][idx]
    note = _note_at(notes, idx)
    is_final_order_leg = idx == len(order["legs"]) - 1
    n0 = _note_at(notes, 0)

    note_dl = co(
        note["noteDeadline"] if note else None,
        (co(n0["noteDeadline"] if n0 else None, None) if is_final_order_leg else None),
    )
    eff_dl = min(order["deadline"], note_dl) if note_dl is not None else order["deadline"]
    if is_final_order_leg:
        n_last = notes[-1] if len(notes) else None
        fallback_hours = co(n_last["deliveryHours"] if n_last else None, leg["delivery"].get("hours"))
    else:
        fallback_hours = leg["delivery"].get("hours")
    real_deliv_hours = co(note["deliveryHours"] if note else None, fallback_hours)
    narrowed_deliv = hours_narrowed(real_deliv_hours, leg["delivery"].get("hours"))
    pw = pickup_stop.get("window")
    min_reachable_deliv = max(now + 15, pw["from"] if pw else leg["pickup"]["window"]["from"]) + drive_min + 20

    resolved = None
    if narrowed_deliv and real_deliv_hours:
        if (not omit_soft_pickup_cap or now <= order["lastPickupAt"]) and min_reachable_deliv <= eff_dl:
            first_win = next_real_day_window(min_reachable_deliv, eff_dl, real_deliv_hours, 30)
            if first_win and first_win["to"] - min_reachable_deliv < 150:
                next_day_start = (day_of(first_win["to"]) + 1) * DAY
                later_win = next_real_day_window(max(min_reachable_deliv, next_day_start), eff_dl, real_deliv_hours, 30)
                if later_win and later_win["to"] > now + 30:
                    resolved = {"from": max(leg["delivery"]["window"]["from"], later_win["from"]), "to": later_win["to"]}
                elif first_win["to"] > now + 30:
                    resolved = {"from": max(leg["delivery"]["window"]["from"], first_win["from"]), "to": first_win["to"]}
            elif first_win and first_win["to"] > now + 30:
                resolved = {"from": max(leg["delivery"]["window"]["from"], first_win["from"]), "to": first_win["to"]}
        elif now > order["lastPickupAt"]:
            next_win = next_real_day_window(min_reachable_deliv, ends_at - 30, real_deliv_hours, 45)
            if next_win and next_win["to"] > now + 30:
                resolved = {"from": max(leg["delivery"]["window"]["from"], next_win["from"]), "to": next_win["to"]}
    elif not omit_soft_pickup_cap and eff_dl < order["deadline"] and min_reachable_deliv <= eff_dl and eff_dl > now + 30:
        resolved = {"from": leg["delivery"]["window"]["from"], "to": eff_dl}

    if (
        not resolved
        and omit_soft_pickup_cap
        and now > order["lastPickupAt"]
        and idx == leg_indices[-1]
        and ends_at - now <= 60 * HOUR
    ):
        end_world_deliv = latest_open_before(ends_at, real_deliv_hours, 15) if real_deliv_hours else ends_at - 15
        if (
            isfinite(end_world_deliv)
            and end_world_deliv < ends_at - 15
            and end_world_deliv >= min_reachable_deliv
            and end_world_deliv > now + 30
        ):
            resolved = {"from": leg["delivery"]["window"]["from"], "to": end_world_deliv}

    return resolved


def build_stops_for_order(m, snow, order, leg_indices, notes, retries_by_leg, now, ends_at, omit_soft_pickup_cap=False):
    combined_trade_in = len(leg_indices) == 2 and len(order["legs"]) == 2
    n0 = _note_at(notes, 0)
    manual_licence = bool(n0 and n0["manualGearbox"])
    experienced = False

    for idx in leg_indices:
        leg = order["legs"][idx]
        if leg["car"]["premium"]:
            experienced = True
        nn = _note_at(notes, idx)
        rr = retries_by_leg.get(idx)
        if (nn and nn["manualGearbox"]) or (rr and rr["manualLicence"]):
            manual_licence = True

    sub_legs = [order["legs"][i] for i in leg_indices]
    sub_notes = [co(_note_at(notes, i), None) if _note_at(notes, i) is not None else create_default_leg_note(order["legs"][i])
                 for i in leg_indices]
    plan = compute_option_plan(m, snow, sub_legs, sub_notes, order["deadline"], now, True)
    effective_last_pickup_at = plan["effectiveLastPickupAt"] if plan else order["lastPickupAt"]

    stops = []
    awaiting_private_slot_rollover = False
    tier24_pickup_cap_at = None

    for idx in leg_indices:
        leg = order["legs"][idx]
        note = _note_at(notes, idx)
        retry = retries_by_leg.get(idx) or EMPTY_RETRY
        is_combined_trade_in_second_leg = combined_trade_in and idx == 1

        with_charging = m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        with_plates = bool((idx == 0 and n0 and n0["needsPlates"]) or (note and note["needsPlates"]) or retry["plates"])

        pickup_stop = {"orderId": order["id"], "leg": idx, "kind": "pickup"}
        if with_plates:
            pickup_stop["withPlates"] = True
        if with_charging:
            pickup_stop["withCharging"] = True

        if not is_combined_trade_in_second_leg:
            min_start = max(
                leg["pickup"]["window"]["from"],
                co(note["readyAt"] if note else None, 0) if idx == 0 else 0,
                co(note["releasedAt"] if note else None, 0) if idx == 0 else 0,
                retry["pickupFrom"],
            )

            if (n0 and n0["summerTyres"]) or (note and note["summerTyres"]):
                drive_min_s = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
                real_pick_h = co(note["pickupHours"] if note else None, leg["pickup"].get("hours"))
                for _ in range(8):
                    cand_pick = visit_at(max(now, min_start), ends_at, real_pick_h, 10)
                    if not isfinite(cand_pick):
                        break
                    sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], cand_pick, cand_pick + drive_min_s + 45)
                    if not sw:
                        break
                    min_start = max(min_start + 1, sw["to"])

            if leg["pickup"]["privateAddress"]:
                slot_from = leg["pickup"]["window"]["from"]
                slot_to = leg["pickup"]["window"]["to"]
                if slot_to <= now + 5 or min_start > slot_to - 5:
                    awaiting_private_slot_rollover = True
                elif min_start > slot_from:
                    pickup_stop["window"] = {"from": min_start, "to": slot_to}
            else:
                real_pick_hours = co(note["pickupHours"] if note else None, leg["pickup"].get("hours"))
                narrowed_pick = hours_narrowed(real_pick_hours, leg["pickup"].get("hours"))
                if narrowed_pick and real_pick_hours:
                    search_earliest = max(now + 10, min_start)
                    search_latest = ends_at - 60 if omit_soft_pickup_cap else max(order["deadline"], search_earliest + 3 * DAY)
                    day_win = next_real_day_window(search_earliest, min(ends_at - 60, search_latest), real_pick_hours, 45)
                    if day_win and day_win["to"] > now + 15:
                        pickup_stop["window"] = {"from": max(leg["pickup"]["window"]["from"], day_win["from"]), "to": day_win["to"]}
                elif min_start > leg["pickup"]["window"]["from"] and min_start > now:
                    to_bound = order["deadline"] if (not omit_soft_pickup_cap and order["deadline"] > min_start + 60) else ends_at - 30
                    if to_bound > min_start and to_bound > now + 15:
                        pickup_stop["window"] = {"from": min_start, "to": to_bound}

                if idx == leg_indices[0]:
                    tier24_pickup_cap_at = apply_first_leg_pickup_safety_cap({
                        "pickupStop": pickup_stop,
                        "map": m,
                        "snow": snow,
                        "order": order,
                        "legIndices": leg_indices,
                        "notes": notes,
                        "retriesByLeg": retries_by_leg,
                        "realPickHours": real_pick_hours,
                        "minStart": min_start,
                        "effectiveLastPickupAt": effective_last_pickup_at,
                        "now": now,
                        "endsAt": ends_at,
                        "omitSoftPickupCap": omit_soft_pickup_cap,
                    })
        stops.append(pickup_stop)

        delivery_stop = {"orderId": order["id"], "leg": idx, "kind": "delivery"}

        drive_min = (
            m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
            + (CHARGING_MINUTES if with_charging else 0)
            + (PLATES_MINUTES if with_plates else 0)
        )

        if leg["delivery"]["privateAddress"]:
            if not omit_soft_pickup_cap and combined_trade_in and idx == 0:
                pw = pickup_stop.get("window")
                min_reach = max(now + 15, pw["from"] if pw else leg["pickup"]["window"]["from"]) + drive_min + 10
                if leg["delivery"]["window"]["to"] + 30 >= min_reach and leg["delivery"]["window"]["to"] + 30 > now + 30:
                    delivery_stop["window"] = {
                        "from": leg["delivery"]["window"]["from"],
                        "to": leg["delivery"]["window"]["to"] + 30,
                    }
        else:
            win = resolve_dealer_delivery_window({
                "order": order,
                "idx": idx,
                "legIndices": leg_indices,
                "notes": notes,
                "pickupStop": pickup_stop,
                "driveMin": drive_min,
                "now": now,
                "endsAt": ends_at,
                "omitSoftPickupCap": omit_soft_pickup_cap,
            })
            if win:
                delivery_stop["window"] = win

        stops.append(delivery_stop)

    return {
        "stops": stops,
        "audience": {"experienced": experienced, "manualLicence": manual_licence},
        "awaitingPrivateSlotRollover": awaiting_private_slot_rollover,
        "effectiveLastPickupAt": effective_last_pickup_at,
        "tier24PickupCapAt": tier24_pickup_cap_at,
    }
