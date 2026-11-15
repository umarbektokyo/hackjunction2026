"""Stop planning, opening hours and the effective last pickup. Python port of source-exp/RoutePulse typescript/planner.ts."""
from __future__ import annotations

import math
from typing import Optional

from .notes import shift_deadline_business_days

HOUR = 60
DAY = 24 * HOUR
CHARGING_MINUTES = 40
PLATES_MINUTES = 30
CHARGING_ROUTE_KM = 200
MAX_MULTI_CAR_ROAD_MINUTES = 12 * HOUR
INF = math.inf
EMPTY_RETRY = {"pickupFrom": 0, "manualLicence": False, "plates": False}


def co(a, b):
    """JavaScript a ?? b."""
    return a if a is not None else b


def isfinite(x) -> bool:
    return x is not None and math.isfinite(x)


def jceil(x):
    return x if not math.isfinite(x) else math.ceil(x)


def jfloor(x):
    return x if not math.isfinite(x) else math.floor(x)


def jround(x):
    """JavaScript Math.round: halves go up."""
    return x if not math.isfinite(x) else math.floor(x + 0.5)


def haversine_place_km(a, b) -> float:
    R = 6371
    d_lat = ((b["lat"] - a["lat"]) * math.pi) / 180
    d_lon = ((b["lon"] - a["lon"]) * math.pi) / 180
    s = math.sin(d_lat / 2) ** 2 + math.cos((a["lat"] * math.pi) / 180) * math.cos((b["lat"] * math.pi) / 180) * math.sin(d_lon / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(s), math.sqrt(1 - s))


class MapGraph:
    def __init__(self, world_map):
        self.places_by_id = {p["id"]: p for p in world_map["places"]}
        self.roads = {(r["from"], r["to"]): r["minutes"] for r in world_map["roads"]}
        self.road_kms = {(r["from"], r["to"]): r["km"] for r in world_map["roads"]}
        self.within30km: dict[str, list[str]] = {}
        self.within65km: dict[str, list[str]] = {}
        self.within80km_set: dict[str, set[str]] = {}
        self.within80km_list: dict[str, list[str]] = {}
        for p in world_map["places"]:
            n30, n65, n80 = [], [], []
            for q in world_map["places"]:
                d = 0 if p["id"] == q["id"] else haversine_place_km(p, q)
                if d <= 30.0:
                    n30.append(q["id"])
                if d <= 65.0:
                    n65.append(q["id"])
                if d <= 80.0:
                    n80.append(q["id"])
            self.within30km[p["id"]] = n30
            self.within65km[p["id"]] = n65
            self.within80km_set[p["id"]] = set(n80)
            self.within80km_list[p["id"]] = n80

    def road_minutes(self, a: str, b: str):
        return self.roads.get((a, b), INF)

    def road_km(self, a: str, b: str):
        return self.road_kms.get((a, b), INF)

    def dist_km(self, a: str, b: str) -> float:
        if a == b:
            return 0
        pa, pb = self.places_by_id.get(a), self.places_by_id.get(b)
        if pa is None or pb is None:
            return INF
        return haversine_place_km(pa, pb)

    def is_same_cluster30(self, a: str, b: str) -> bool:
        return self.dist_km(a, b) <= 30.0

    def needs_charging(self, car, a: str, b: str) -> bool:
        return bool(car["electric"] and car.get("chargePercent") is not None and car["chargePercent"] < 30 and self.road_km(a, b) > CHARGING_ROUTE_KM)


class SnowTracker:
    def __init__(self):
        self.forecasts: list[dict] = []

    def add_forecast(self, frm: int, to: int, place_ids) -> None:
        for f in self.forecasts:
            if f["from"] == frm and f["to"] == to:
                f["places"].update(place_ids)
                return
        self.forecasts.append({"from": frm, "to": to, "places": set(place_ids)})

    def overlaps(self, a: str, b: str, start, end):
        for f in self.forecasts:
            if end >= f["from"] and start < f["to"] and (a in f["places"] or b in f["places"]):
                return f
        return None

    def has_active_snow(self, place: str, at) -> bool:
        return any(f["from"] <= at < f["to"] and place in f["places"] for f in self.forecasts)


def _slot(hours, wd):
    if wd == 5:
        return hours.get("saturday")
    return hours if wd in hours["weekdays"] else None


def visit_at(earliest, latest, hours, service):
    if earliest > latest:
        return INF
    if not hours:
        return earliest if earliest + service <= latest else INF
    start_day = jfloor(earliest / DAY)
    end_day = jfloor(latest / DAY)
    if not isfinite(start_day) or not isfinite(end_day):
        if not isfinite(start_day):
            return INF
        end_day = start_day + 30          # JS would loop to Infinity; no slot ever exists that far, stop safely
    day = start_day
    while day <= end_day:
        slot = _slot(hours, day % 7)
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
    start_day = jfloor(t / DAY)
    if not isfinite(start_day):
        return -INF           # JS never gets here (its loop would not end); no caller passes an infinite time
    for day in range(start_day, start_day - 8, -1):
        slot = _slot(hours, day % 7)
        if not slot:
            continue
        open_at = day * DAY + slot["opens"]
        close_limit = day * DAY + slot["closes"] - 1 - safety_buffer
        if t < open_at:
            continue
        if close_limit >= open_at:
            return min(t, close_limit)
    return -INF


def compute_option_plan(m: MapGraph, snow: SnowTracker, legs, notes, raw_option_deadline, now, deadline_already_shifted=False):
    if not legs:
        return None
    leg0, last_leg = legs[0], legs[-1]
    note0 = notes[0] if notes else None
    last_note = notes[-1] if notes else None

    ready_shift = max(0, jfloor(note0["readyAt"] / DAY) - jfloor(leg0["pickup"]["window"]["from"] / DAY)) if (not deadline_already_shifted and note0) else 0
    promised = raw_option_deadline if last_leg["delivery"]["privateAddress"] else shift_deadline_business_days(raw_option_deadline, ready_shift)
    note_dl = last_note["noteDeadline"] if last_note and last_note["noteDeadline"] is not None else (note0["noteDeadline"] if note0 else None)
    eff_dl = min(promised, note_dl) if note_dl is not None else promised

    total_road_min = 0
    total_road_km = 0
    priv_pick = priv_del = 0
    charging_any = False
    plates_any = bool(note0 and note0["needsPlates"])
    manual_required = bool(note0 and note0["manualGearbox"])
    premium_any = any(l["car"]["premium"] for l in legs)
    summer = bool(note0 and note0["summerTyres"])
    snow_overlap = False

    at = now + 20
    earliest_pickup = 0
    for i, leg in enumerate(legs):
        prev = legs[i - 1] if i > 0 else None
        n = notes[i] if i < len(notes) else None
        same_cust = (prev is not None and prev["delivery"]["placeId"] == leg["pickup"]["placeId"]
                     and prev["delivery"]["privateAddress"] and leg["pickup"]["privateAddress"])
        link = 0 if prev is None else 0 if same_cust else m.road_minutes(prev["delivery"]["placeId"], leg["pickup"]["placeId"])
        drive = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        drive_km = m.road_km(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        if not isfinite(link) or not isfinite(drive):
            return None
        total_road_min += link + drive
        total_road_km += drive_km + (0 if prev is None or same_cust else m.road_km(prev["delivery"]["placeId"], leg["pickup"]["placeId"]))
        if leg["pickup"]["privateAddress"]:
            priv_pick += 1
        if leg["delivery"]["privateAddress"]:
            priv_del += 1
        charging = m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        if charging:
            charging_any = True
        plates = i == 0 and plates_any
        pick_hours = co(n and n["pickupHours"], leg["pickup"].get("hours"))
        deliv_hours = co(n and n["deliveryHours"], leg["delivery"].get("hours"))

        pick_earliest = max(at + link, leg["pickup"]["window"]["from"], (n["readyAt"] if n is not None else 0),
                            (n["releasedAt"] if n is not None and n["releasedAt"] is not None else 0))
        pick_latest = leg["pickup"]["window"]["to"] + (30 if same_cust else 0) if leg["pickup"]["privateAddress"] else eff_dl

        sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], pick_earliest, pick_earliest + drive + 60)
        if sw:
            snow_overlap = True
            if summer:
                pick_earliest = max(pick_earliest, sw["to"])
        pick_service = 0 if same_cust else 10
        pick_start = visit_at(pick_earliest, pick_latest, pick_hours, pick_service)
        if summer:
            it = 0
            while it < 8 and isfinite(pick_start):
                sw2 = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], pick_start, pick_start + drive + 45)
                if not sw2:
                    break
                snow_overlap = True
                pick_earliest = max(pick_earliest + 1, sw2["to"])
                pick_start = visit_at(pick_earliest, pick_latest, pick_hours, pick_service)
                it += 1
        if not isfinite(pick_start):
            return None
        if i == 0:
            earliest_pickup = pick_start
        snow_run = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], pick_start, pick_start + jceil(drive * 1.35) + 60)
        if snow_run:
            snow_overlap = True
        eff_drive = jceil(drive * (1.32 if snow_run else 1.04))
        extra = (PLATES_MINUTES if plates else 0) + (CHARGING_MINUTES if charging else 0)
        deliv_earliest = max(pick_start + pick_service + extra + eff_drive, leg["delivery"]["window"]["from"])
        deliv_latest = min(eff_dl, leg["delivery"]["window"]["to"] + 30) if leg["delivery"]["privateAddress"] else eff_dl
        deliv_start = visit_at(deliv_earliest, deliv_latest, deliv_hours, 10)
        if not isfinite(deliv_start):
            return None
        at = deliv_start + 10

    can_single = len(legs) == 1 or total_road_min <= MAX_MULTI_CAR_ROAD_MINUTES

    latest_next = INF
    for i in range(len(legs) - 1, -1, -1):
        leg = legs[i]
        nxt = legs[i + 1] if i + 1 < len(legs) else None
        n = notes[i] if i < len(notes) else None
        same_next = (nxt is not None and leg["delivery"]["placeId"] == nxt["pickup"]["placeId"]
                     and leg["delivery"]["privateAddress"] and nxt["pickup"]["privateAddress"])
        link_min = 0 if nxt is None else 0 if same_next else m.road_minutes(leg["delivery"]["placeId"], nxt["pickup"]["placeId"])
        deliv_hours = co(n and n["deliveryHours"], leg["delivery"].get("hours"))
        pick_hours = co(n and n["pickupHours"], leg["pickup"].get("hours"))
        deliv_window_cap = leg["delivery"]["window"]["to"] + 30 if leg["delivery"]["privateAddress"] else eff_dl
        deliv_cap = min(eff_dl, deliv_window_cap, latest_next - link_min)
        close_buffer = 15 if deliv_hours else 0
        latest_deliv = latest_open_before(deliv_cap, deliv_hours, close_buffer)
        raw_latest_deliv = latest_open_before(deliv_cap, deliv_hours, 0)
        base_drive = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        snow_late = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], max(now, latest_deliv - base_drive * 2), latest_deliv)
        eff_drive = jceil(base_drive * (1.30 if snow_late else 1.03))
        charging = CHARGING_MINUTES if m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"]) else 0
        plates = PLATES_MINUTES if (i == 0 and plates_any) else 0
        pick_window_cap = leg["pickup"]["window"]["to"] + (30 if i > 0 else 0) if leg["pickup"]["privateAddress"] else eff_dl
        pick_cap = min(latest_deliv - eff_drive - charging - plates, pick_window_cap)
        raw_pick_cap = min(raw_latest_deliv - base_drive - charging - plates, pick_window_cap)
        buffered = latest_open_before(pick_cap, pick_hours, 0)
        raw_pickup = latest_open_before(raw_pick_cap, pick_hours, 0)
        latest_next = raw_pickup if (not snow_late and jfloor(buffered / DAY) < jfloor(raw_pickup / DAY)) else buffered

    if not isfinite(latest_next) or latest_next < earliest_pickup - 5 or latest_next <= now + 20:
        return None
    pickup_slack = max(0, latest_next - max(now + 15, min(earliest_pickup, latest_next)))
    raw_booking = max(0, latest_next - now)
    return {
        "promisedDeadline": promised,
        "effectiveDeadline": eff_dl,
        "earliestPickupAt": earliest_pickup,
        "finishAt": at,
        "effectiveLastPickupAt": latest_next,
        "pickupSlackMinutes": max(pickup_slack, min(raw_booking, latest_next - earliest_pickup + (earliest_pickup - now))),
        "deliverySlackMinutes": max(0, eff_dl - at),
        "totalRoadMinutes": total_road_min,
        "totalRoadKm": total_road_km,
        "privatePickupCount": priv_pick,
        "privateDeliveryCount": priv_del,
        "needsChargingAny": charging_any,
        "needsPlatesAny": plates_any,
        "manualRequired": manual_required,
        "premiumAny": premium_any,
        "snowOverlap": snow_overlap,
        "canSingleGig": can_single,
    }


def hours_narrowed(real, stated) -> bool:
    if not real or not stated:
        return False
    return real["opens"] > stated["opens"] or real["closes"] < stated["closes"]


def next_real_day_window(earliest, latest, real_hours, min_remaining):
    start_day = jfloor(earliest / DAY)
    end_day = jfloor(latest / DAY)
    if not isfinite(start_day):
        return None
    if not isfinite(end_day):
        end_day = start_day + 30
    day = start_day
    while day <= end_day:
        slot = _slot(real_hours, day % 7)
        if slot:
            frm = max(earliest, day * DAY + slot["opens"])
            to = min(latest, day * DAY + slot["closes"])
            if to - frm >= min_remaining:
                return {"from": frm, "to": to}
        day += 1
    return None


def default_note(leg) -> dict:
    return {"readyAt": leg["pickup"]["window"]["from"], "releasedAt": None, "pickupHours": leg["pickup"].get("hours"),
            "deliveryHours": leg["delivery"].get("hours"), "manualGearbox": False, "needsPlates": False, "summerTyres": False,
            "noteDeadline": None}


def build_stops_for_order(m: MapGraph, snow: SnowTracker, order, leg_indices, notes, retries_by_leg, now, ends_at, omit_soft_cap=False):
    combined_trade_in = len(leg_indices) == 2 and len(order["legs"]) == 2
    manual = False
    experienced = False

    def note_at(i):
        return notes[i] if 0 <= i < len(notes) else None

    for idx in leg_indices:
        leg = order["legs"][idx]
        if leg["car"]["premium"]:
            experienced = True
        n = note_at(idx)
        r = retries_by_leg.get(idx)
        if (n and n["manualGearbox"]) or (r and r["manualLicence"]):
            manual = True
    n0 = note_at(0)
    if n0 and n0["manualGearbox"]:
        manual = True

    sub_legs = [order["legs"][i] for i in leg_indices]
    sub_notes = [note_at(i) if note_at(i) is not None else default_note(order["legs"][i]) for i in leg_indices]
    plan = compute_option_plan(m, snow, sub_legs, sub_notes, order["deadline"], now, True)
    eff_lpa = plan["effectiveLastPickupAt"] if plan else order["lastPickupAt"]

    stops = []
    awaiting = False
    for idx in leg_indices:
        leg = order["legs"][idx]
        note = note_at(idx)
        retry = retries_by_leg.get(idx) or EMPTY_RETRY
        second_tradein = combined_trade_in and idx == 1
        with_charging = m.needs_charging(leg["car"], leg["pickup"]["placeId"], leg["delivery"]["placeId"])
        with_plates = bool((idx == 0 and n0 and n0["needsPlates"]) or (note and note["needsPlates"]) or retry["plates"])

        pickup = {"orderId": order["id"], "leg": idx, "kind": "pickup"}
        if with_plates:
            pickup["withPlates"] = True
        if with_charging:
            pickup["withCharging"] = True

        if not second_tradein:
            min_start = max(leg["pickup"]["window"]["from"],
                            (note["readyAt"] if note else 0) if idx == 0 else 0,
                            ((note["releasedAt"] if note and note["releasedAt"] is not None else 0)) if idx == 0 else 0,
                            retry["pickupFrom"])
            if (n0 and n0["summerTyres"]) or (note and note["summerTyres"]):
                drive_min = m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"])
                real_pick_h = co(note and note["pickupHours"], leg["pickup"].get("hours"))
                for _ in range(8):
                    cand = visit_at(max(now, min_start), ends_at, real_pick_h, 10)
                    if not isfinite(cand):
                        break
                    sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], cand, cand + drive_min + 45)
                    if not sw:
                        break
                    min_start = max(min_start + 1, sw["to"])
            if leg["pickup"]["privateAddress"]:
                slot_from, slot_to = leg["pickup"]["window"]["from"], leg["pickup"]["window"]["to"]
                if slot_to <= now + 5 or min_start > slot_to - 5:
                    awaiting = True
                elif min_start > slot_from:
                    pickup["window"] = {"from": min_start, "to": slot_to}
            else:
                real_pick_hours = co(note and note["pickupHours"], leg["pickup"].get("hours"))
                narrowed = hours_narrowed(real_pick_hours, leg["pickup"].get("hours"))
                if narrowed and real_pick_hours:
                    s_early = max(now + 10, min_start)
                    s_late = ends_at - 60 if omit_soft_cap else max(order["deadline"], s_early + 3 * DAY)
                    win = next_real_day_window(s_early, min(ends_at - 60, s_late), real_pick_hours, 45)
                    if win and win["to"] > now + 15:
                        pickup["window"] = {"from": max(leg["pickup"]["window"]["from"], win["from"]), "to": win["to"]}
                elif min_start > leg["pickup"]["window"]["from"] and min_start > now:
                    to_bound = order["deadline"] if (not omit_soft_cap and order["deadline"] > min_start + 60) else ends_at - 30
                    if to_bound > min_start and to_bound > now + 15:
                        pickup["window"] = {"from": min_start, "to": to_bound}
                if (not omit_soft_cap and idx == leg_indices[0] and eff_lpa < order["lastPickupAt"]
                        and eff_lpa > max(now + 75, min_start + 30)):
                    cur_from = pickup["window"]["from"] if "window" in pickup else min_start
                    cur_to = pickup["window"]["to"] if "window" in pickup else order["deadline"]
                    capped = min(cur_to, eff_lpa)
                    if capped >= cur_from + 20:
                        pickup["window"] = {"from": max(leg["pickup"]["window"]["from"], cur_from), "to": capped}
        stops.append(pickup)

        delivery = {"orderId": order["id"], "leg": idx, "kind": "delivery"}
        drive_min = (m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"]) + (CHARGING_MINUTES if with_charging else 0)
                     + (PLATES_MINUTES if with_plates else 0))
        pw_from = pickup["window"]["from"] if "window" in pickup else leg["pickup"]["window"]["from"]
        if leg["delivery"]["privateAddress"]:
            if combined_trade_in and idx == 0:
                min_reach = max(now + 15, pw_from) + drive_min + 15
                if leg["delivery"]["window"]["to"] + 15 >= min_reach and leg["delivery"]["window"]["to"] > now + 30:
                    delivery["window"] = {"from": leg["delivery"]["window"]["from"], "to": leg["delivery"]["window"]["to"] + 15}
        else:
            if note and note["noteDeadline"] is not None:
                note_dl = note["noteDeadline"]
            elif idx == len(order["legs"]) - 1:
                note_dl = n0["noteDeadline"] if n0 else None
            else:
                note_dl = None
            eff_dl = min(order["deadline"], note_dl) if note_dl is not None else order["deadline"]
            if note is not None and note["deliveryHours"] is not None:
                real_dh = note["deliveryHours"]
            elif idx == len(order["legs"]) - 1:
                real_dh = co(notes[-1]["deliveryHours"] if notes and notes[-1] is not None else None, leg["delivery"].get("hours"))
            else:
                real_dh = leg["delivery"].get("hours")
            narrowed_d = hours_narrowed(real_dh, leg["delivery"].get("hours"))
            min_reach = max(now + 15, pw_from) + drive_min + 20
            if narrowed_d and real_dh:
                if not omit_soft_cap and min_reach <= eff_dl:
                    first = next_real_day_window(min_reach, eff_dl, real_dh, 30)
                    if first and first["to"] - min_reach < 150:
                        next_day_start = (jfloor(first["to"] / DAY) + 1) * DAY
                        later = next_real_day_window(max(min_reach, next_day_start), eff_dl, real_dh, 30)
                        if later and later["to"] > now + 30:
                            delivery["window"] = {"from": max(leg["delivery"]["window"]["from"], later["from"]), "to": later["to"]}
                        elif first["to"] > now + 30:
                            delivery["window"] = {"from": max(leg["delivery"]["window"]["from"], first["from"]), "to": first["to"]}
                    elif first and first["to"] > now + 30:
                        delivery["window"] = {"from": max(leg["delivery"]["window"]["from"], first["from"]), "to": first["to"]}
                else:
                    nw = next_real_day_window(min_reach, ends_at - 30, real_dh, 45)
                    if nw and nw["to"] > now + 30:
                        delivery["window"] = {"from": max(leg["delivery"]["window"]["from"], nw["from"]), "to": nw["to"]}
            elif not omit_soft_cap and eff_dl < order["deadline"] and min_reach <= eff_dl and eff_dl > now + 30:
                delivery["window"] = {"from": leg["delivery"]["window"]["from"], "to": eff_dl}
        stops.append(delivery)

    return {"stops": stops, "audience": {"experienced": experienced, "manualLicence": manual},
            "awaitingPrivateSlotRollover": awaiting, "effectiveLastPickupAt": eff_lpa}
