"""The desk: event handling, dispatch, bundles, offers and timers. Python port of source-exp/RoutePulse
typescript/starter.ts (class Desk). Map/Set iteration order matters for an exact replay, so ordered sets are dicts."""
from __future__ import annotations

import math
import re
import time

from .dispatch import (DirectOfferTracker, build_single_gig_schedule, find_best_two_order_bundle, try_extend_two_to_three)
from .market import PricingEngine, RosterSupplyModel
from .notes import copy_hours, parse_dealer_note
from .planner import (CHARGING_MINUTES, DAY, EMPTY_RETRY, HOUR, INF, PLATES_MINUTES, MapGraph, SnowTracker, build_stops_for_order,
                      co, isfinite, jceil, jfloor, jround, visit_at)

ACTION_PRIORITY = {"quote": 0, "withdraw": 1, "release": 2, "post": 3, "reprice": 4, "offer": 5}
WAKE_ON = ["price_request", "order_won", "order_changed", "order_cancelled", "visit_failed", "gig_expired", "deadline_close",
           "gig_booked", "gig_dropped", "no_show", "driver_late", "offer_answered", "delivered", "release", "forecast"]
_BOOK = re.compile(r"book|start|work", re.IGNORECASE)
_START = re.compile(r"start|work", re.IGNORECASE)


def undelivered_legs(order) -> list[int]:
    return [i for i in range(len(order["legs"])) if order["deliveredAt"][i] is None]


def current_schedule_fee(schedule, now) -> int:
    fee = schedule[0]["feeCents"] if schedule else 0
    for st in schedule:
        if st["at"] <= now:
            fee = st["feeCents"]
    return fee


def empty_notes(order):
    return [{"readyAt": l["pickup"]["window"]["from"], "releasedAt": None, "pickupHours": l["pickup"].get("hours"),
             "deliveryHours": l["delivery"].get("hours"), "manualGearbox": False, "needsPlates": False, "summerTyres": False,
             "noteDeadline": None} for l in order["legs"]]


class Desk:
    def __init__(self, world, level: int, now: int, ends_at: int, raw_map, roster=(), params=None):
        self.world, self.level = world, level
        self.params = params or {}
        self.map = MapGraph(raw_map)
        self.snow = SnowTracker()
        self.supply = RosterSupplyModel(self.map, roster)
        self.pricing = PricingEngine(level, self.map, self.snow, self.supply, self.params)
        self.offers = DirectOfferTracker()
        self.now, self.ends_at = now, ends_at
        self.outbox: list = []
        self.requests: dict = {}
        self.notes_by_order: dict = {}
        self.quote_meta: dict = {}
        self.orders: dict = {}
        self.order_won_at: dict = {}
        self.eff_lpa: dict = {}
        self.max_reached_fee: dict = {}
        self.retries: dict = {}
        self.urgent: set = set()
        self.do_not_bundle: set = set()
        self.omit_soft_cap: set = set()
        self.strip_windows: set = set()
        self.post_backoff: dict = {}
        self.pairing_buffer: dict = {}      # ordered: order id -> release minute
        self.gigs: dict = {}
        self.leg_gigs: dict = {}
        self.start_minute = now
        self.won_total = 0
        self.delivered_total = 0
        self.delivered_on_time = 0
        self.late_or_penalized: set = set()
        self.pending_revenue: dict = {}
        self.finalized_on_time: dict = {}
        self.flu_day = -1
        self.morning_drops = 0
        self.flu_today = False
        self.needs_offer_pass = False
        self.last_non_urgent_offer_ms = 0.0

    # ---- small helpers ----------------------------------------------------------------------
    def record_reached_fee(self, oid, fee) -> None:
        if fee <= 0:
            return
        if fee > self.max_reached_fee.get(oid, 0):
            self.max_reached_fee[oid] = fee

    def day_rollover(self) -> None:
        day = jfloor(self.now / DAY)
        if day != self.flu_day:
            self.flu_day = day
            self.morning_drops = 0
            self.flu_today = False

    def get_retry(self, oid, leg):
        m = self.retries.get(oid)
        return (m.get(leg) if m else None) or EMPTY_RETRY

    def set_retry(self, oid, leg, nxt) -> None:
        self.retries.setdefault(oid, {})[leg] = nxt

    def get_notes(self, oid):
        cached = self.notes_by_order.get(oid)
        if cached is not None:
            return cached
        req = self.requests.get(oid)
        if req:
            parsed = parse_dealer_note(req)
            self.notes_by_order[oid] = parsed
            return parsed
        order = self.orders.get(oid)
        return empty_notes(order) if order else []

    def link_gig(self, g) -> None:
        self.gigs[g["id"]] = g
        for s in g["stops"]:
            if s["kind"] != "pickup":
                continue
            self.leg_gigs.setdefault(s["orderId"], {})[s["leg"]] = g["id"]

    def unlink_gig(self, gid) -> None:
        g = self.gigs.get(gid)
        if not g:
            return
        for s in g["stops"]:
            m = self.leg_gigs.get(s["orderId"])
            if m is not None and m.get(s["leg"]) == gid:
                del m[s["leg"]]
        self.offers.clear_gig(gid)

    def has_leg_gig(self, oid, leg) -> bool:
        m = self.leg_gigs.get(oid)
        return bool(m) and leg in m

    def missing_legs(self, order, check_outbox=False):
        return [l for l in undelivered_legs(order) if not self.has_leg_gig(order["id"], l)
                and not (check_outbox and self.has_pending_post(order["id"], l))]

    def live_orders_of_stops(self, stops):
        seen, out = set(), []
        for s in stops:
            if s["orderId"] in seen:
                continue
            seen.add(s["orderId"])
            o = self.orders.get(s["orderId"])
            if o:
                out.append(o)
        return out

    def remove_unsent_posts(self, oid):
        displaced = []
        for i in range(len(self.outbox) - 1, -1, -1):
            a = self.outbox[i]
            if a["type"] == "post" and any(s["orderId"] == oid for s in a["stops"]):
                for s in a["stops"]:
                    if s["orderId"] != oid and s["kind"] == "pickup":
                        displaced.append(s)
                del self.outbox[i]
        return displaced

    def has_pending_post(self, oid, leg) -> bool:
        return any(a["type"] == "post" and any(s["kind"] == "pickup" and s["orderId"] == oid and s["leg"] == leg for s in a["stops"])
                   for a in self.outbox)

    def push_post(self, action, bundled, split_at, urgent_esc, past_esc, stripped) -> None:
        action["_meta"] = {"isBundledTwoOrder": bundled, "splitAt": split_at, "urgentEscalated": urgent_esc,
                           "pastDeadlineEscalated": past_esc, "strippedFallback": stripped}
        self.outbox.append(action)

    def stop_place(self, s):
        o = self.orders.get(s["orderId"])
        leg = o["legs"][s["leg"]] if o and s["leg"] < len(o["legs"]) else None
        if not leg:
            return None
        return leg["pickup"]["placeId"] if s["kind"] == "pickup" else leg["delivery"]["placeId"]

    def road_sum(self, stops) -> int:
        total, prev = 0, None
        for s in stops:
            pl = self.stop_place(s)
            if pl is None:
                continue
            if prev is not None and prev != pl:
                total += self.map.road_minutes(prev, pl)
            prev = pl
        return total

    def active_commitments(self):
        out = []
        for g in self.gigs.values():
            if g["status"] not in ("booked", "working") or not g["driverId"]:
                continue
            pickups = [s for s in g["stops"] if s["kind"] == "pickup"]
            delivs = [s for s in g["stops"] if s["kind"] == "delivery"]
            if not pickups or not delivs:
                continue
            first, last = self.orders.get(pickups[0]["orderId"]), self.orders.get(delivs[-1]["orderId"])
            if not first or not last:
                continue
            fl = first["legs"][pickups[0]["leg"]] if pickups[0]["leg"] < len(first["legs"]) else None
            ll = last["legs"][delivs[-1]["leg"]] if delivs[-1]["leg"] < len(last["legs"]) else None
            p_place = fl["pickup"]["placeId"] if fl else None
            d_place = ll["delivery"]["placeId"] if ll else None
            if not p_place or not d_place:
                continue
            road = self.road_sum(g["stops"])
            if g["status"] == "working" and g["startedAt"] is not None:
                est_start = g["startedAt"]
            else:
                w = pickups[0].get("window")
                est_start = max(self.now, w["from"] if w else first["legs"][pickups[0]["leg"]]["pickup"]["window"]["from"])
            est_finish = max(self.now + 5, est_start + road + len(pickups) * 25)
            out.append({"gigId": g["id"], "driverId": g["driverId"], "status": g["status"], "pickupPlaceId": p_place,
                        "deliveryPlaceId": d_place, "estStartAt": est_start, "estFinishAt": est_finish, "driveMinutes": road})
        return out

    def count_unbooked_orders(self) -> int:
        n = 0
        for o in self.orders.values():
            undel = undelivered_legs(o)
            if not undel:
                continue
            m = self.leg_gigs.get(o["id"])
            all_booked = True
            for leg in undel:
                gid = m.get(leg) if m else None
                g = self.gigs.get(gid) if gid else None
                if not (g and g["status"] in ("booked", "working")):
                    all_booked = False
                    break
            if not all_booked:
                n += 1
        return n

    def count_active_on_deadline_day(self, dl_day) -> int:
        n = 0
        for o in self.orders.values():
            if not undelivered_legs(o):
                continue
            notes = self.get_notes(o["id"])
            note_dl = None
            if notes:
                note_dl = notes[-1]["noteDeadline"] if notes[-1]["noteDeadline"] is not None else notes[0]["noteDeadline"]
            eff = min(o["deadline"], note_dl) if note_dl is not None else o["deadline"]
            if jfloor(eff / DAY) == dl_day:
                n += 1
        return n

    def count_open_pickups_in_cluster30(self, place) -> int:
        cluster = set(self.map.within30km.get(place) or [place])
        n = 0
        for g in self.gigs.values():
            if g["status"] != "open" or not g["stops"]:
                continue
            p0 = g["stops"][0]
            o = self.orders.get(p0["orderId"])
            pid = o["legs"][p0["leg"]]["pickup"]["placeId"] if o and p0["leg"] < len(o["legs"]) else None
            if pid and pid in cluster:
                n += 1
        return n

    def has_arriving_driver_synergy(self, pick, deliv, earliest, latest) -> bool:
        for c in self.active_commitments():
            if self.map.dist_km(c["deliveryPlaceId"], pick) > 35:
                continue
            link = self.map.road_minutes(c["deliveryPlaceId"], pick)
            if c["estFinishAt"] + link < earliest - 90 or c["estFinishAt"] + link > latest - 30:
                continue
            prof = self.supply.by_id.get(c["driverId"])
            if prof and self.map.dist_km(prof["homePlaceId"], deliv) <= 35:
                return True
        return False

    def _round_trip_leg_ok(self, l, pick, deliv) -> bool:
        if l["car"]["premium"] or l["pickup"]["privateAddress"] or l["delivery"]["privateAddress"]:
            return False
        return self.map.road_minutes(l["delivery"]["placeId"], pick) <= 50 and self.map.road_minutes(deliv, l["pickup"]["placeId"]) <= 120

    def has_open_round_trip_partner(self, pick, deliv) -> bool:
        for bid in self.pairing_buffer:
            o = self.orders.get(bid)
            if not o or len(o["legs"]) != 1:
                continue
            if self._round_trip_leg_ok(o["legs"][0], pick, deliv):
                return True
        for g in self.gigs.values():
            if g["status"] != "open" or g["isBundledTwoOrder"] or len(g["stops"]) != 2:
                continue
            o = self.orders.get(g["stops"][0]["orderId"])
            if not o or len(o["legs"]) != 1:
                continue
            if self._round_trip_leg_ok(o["legs"][0], pick, deliv):
                return True
        return False

    def finalize_pending_revenue(self, up_to) -> None:
        for oid, info in list(self.pending_revenue.items()):
            if info["at"] > up_to:
                continue
            del self.pending_revenue[oid]
            on_time = oid not in self.late_or_penalized
            self.delivered_total += 1
            if on_time:
                self.delivered_on_time += 1
                self.finalized_on_time[oid] = info["dealerId"]
            self.pricing.estimator.on_order_delivered(info["dealerId"], on_time)

    def mark_late(self, oid) -> None:
        if oid in self.late_or_penalized:
            return
        self.late_or_penalized.add(oid)
        dealer = self.finalized_on_time.get(oid)
        if dealer:
            del self.finalized_on_time[oid]
            if self.delivered_on_time > 0:
                self.delivered_on_time -= 1
            d = self.pricing.estimator.get_dealer(dealer)
            if self.level == 8:
                d["trust"] = math.floor(max(0, d["trust"] - 1) / 2)
            d["lateCount"] += 1

    def quote_ctx(self, now, rebuild=False):
        if rebuild:
            return {"now": now, "wonOrdersTotal": self.won_total, "deliveredOrdersTotal": self.delivered_total,
                    "deliveredOnTimeTotal": self.delivered_on_time, "unbookedOrdersCount": 10,
                    "openPickupsInCluster30": lambda p: 0, "activeOrdersOnDeadlineDay": lambda d: 35,
                    "hasArrivingDriverSynergy": lambda *a: False, "hasOpenRoundTripPartner": lambda *a: False,
                    "fluActiveToday": self.flu_today}
        return {"now": now, "wonOrdersTotal": self.won_total, "deliveredOrdersTotal": self.delivered_total,
                "deliveredOnTimeTotal": self.delivered_on_time, "unbookedOrdersCount": self.count_unbooked_orders(),
                "openPickupsInCluster30": self.count_open_pickups_in_cluster30,
                "activeOrdersOnDeadlineDay": self.count_active_on_deadline_day,
                "hasArrivingDriverSynergy": self.has_arriving_driver_synergy,
                "hasOpenRoundTripPartner": self.has_open_round_trip_partner, "fluActiveToday": self.flu_today}

    # ---- rejoin ------------------------------------------------------------------------------
    def rejoin(self, snapshot, history) -> None:
        self.now, self.ends_at = snapshot["now"], snapshot["endsAt"]
        self.start_minute = history[0]["at"] if history else snapshot["now"]
        for ev in history:
            self.now = max(self.now, ev["at"])
            self.day_rollover()
            self.finalize_pending_revenue(ev["at"] - 1)
            k = ev["kind"]
            if k == "price_request":
                req = ev["request"]
                self.requests[req["id"]] = req
                notes = parse_dealer_note(req)
                self.notes_by_order[req["id"]] = notes
                meta = self.pricing.quote_request(req, notes, self.quote_ctx(ev["at"], rebuild=True))
                if meta:
                    self.quote_meta[req["id"]] = meta
            elif k == "forecast":
                self.snow.add_forecast(ev["from"], ev["to"], ev["placeIds"])
            elif k == "deadline_close":
                self.urgent.add(ev["orderId"])
            elif k == "order_won":
                self.won_total += 1
                self.order_won_at[ev["order"]["id"]] = ev["at"]
                meta = self.quote_meta.get(ev["order"]["id"])
                if meta:
                    self.pricing.estimator.on_quote_resolved(meta, ev["order"]["option"])
            elif k == "order_lost":
                meta = self.quote_meta.get(ev["requestId"])
                if meta:
                    self.pricing.estimator.on_quote_resolved(meta, None)
            elif k == "order_cancelled":
                if self.won_total > 0:
                    self.won_total -= 1
            elif k == "order_changed":
                notes = self.get_notes(ev["order"]["id"])
                for l, leg in enumerate(ev["order"]["legs"]):
                    if l < len(notes) and notes[l]:
                        notes[l]["deliveryHours"] = copy_hours(leg["delivery"].get("hours"))
            elif k == "gig_viewed":
                self.offers.record_view(ev["driverId"], ev["at"], ev["gigId"])
            elif k == "gig_booked":
                self.offers.record_booked(ev["driverId"], ev["gigId"], ev["at"])
            elif k == "delivered":
                self.offers.record_delivered(None, ev["placeId"], ev["at"])
            elif k == "offer_answered":
                key = f"{jfloor(max(0, ev['at'] - 1) / DAY)}:{ev['driverId']}"
                self.offers.offers_sent_by_day[key] = self.offers.offers_sent_by_day.get(key, 0) + 1
                self.offers.attempted.add(f"{ev['gigId']}:{ev['driverId']}")
            elif k == "gig_dropped":
                tod = ev["at"] % DAY
                if 5 * HOUR <= tod <= 9 * HOUR + 30:
                    self.morning_drops += 1
                    if self.morning_drops >= 3:
                        self.flu_today = True
            elif k == "release":
                notes = self.get_notes(ev["orderId"])
                if ev["leg"] < len(notes) and notes[ev["leg"]]:
                    notes[ev["leg"]]["releasedAt"] = ev["at"]
                cur = self.get_retry(ev["orderId"], ev["leg"])
                self.set_retry(ev["orderId"], ev["leg"], {**cur, "pickupFrom": 0})
            elif k == "visit_failed":
                ord_ = next((o for o in snapshot["orders"] if o["id"] == ev["orderId"]), None)
                req = self.requests.get(ev["orderId"])
                prev = self.get_retry(ev["orderId"], ev["leg"])
                not_there = ev["reason"] in ("not_ready", "closed")
                pf = self.retry_from(ord_, req, ev["leg"], ev["at"]) if (not_there and ord_ and req) else prev["pickupFrom"]
                self.set_retry(ev["orderId"], ev["leg"], {"pickupFrom": pf, "manualLicence": prev["manualLicence"] or ev["reason"] == "licence",
                                                          "plates": prev["plates"] or ev["reason"] == "no_plates"})
            elif k == "ledger":
                line = ev["line"]
                if line["kind"] in ("late_refund", "undelivered_penalty") and line.get("orderId"):
                    self.mark_late(line["orderId"])
                elif line["kind"] == "revenue" and line.get("orderId"):
                    req = self.requests.get(line["orderId"])
                    if req:
                        self.pending_revenue[line["orderId"]] = {"dealerId": req["dealerId"], "at": ev["at"]}
        self.now = snapshot["now"]
        self.finalize_pending_revenue(snapshot["now"] - 1)
        for o in snapshot["orders"]:
            if o["status"] != "cancelled":
                self.orders[o["id"]] = o
                if o["id"] not in self.order_won_at:
                    self.order_won_at[o["id"]] = snapshot["now"]
        for gig in snapshot["gigs"]:
            distinct = {s["orderId"] for s in gig["stops"]}
            any_urgent = any(s["orderId"] in self.urgent for s in gig["stops"])
            first = self.orders.get(gig["stops"][0]["orderId"]) if gig["stops"] else None
            st = {"id": gig["id"], "stops": gig["stops"], "audience": gig["audience"], "schedule": gig["schedule"], "status": gig["status"],
                  "postedAt": gig["postedAt"], "bookedAt": gig["postedAt"] if gig["status"] in ("booked", "working") else None,
                  "startedAt": max(gig["postedAt"], snapshot["now"] - 30) if gig["status"] == "working" else None,
                  "feeCents": gig["feeCents"], "driverId": gig.get("driverId"), "isBundledTwoOrder": len(distinct) > 1,
                  "splitAt": gig["postedAt"] + 120, "urgentEscalated": any_urgent, "urgentEscalatedAt": snapshot["now"] if any_urgent else None,
                  "pastDeadlineEscalated": False,
                  "zombieCleared": (gig["postedAt"] > (first["lastPickupAt"] if first else INF)) if gig["stops"] else False,
                  "offerWave": 0, "nextOfferCheckAt": snapshot["now"] + 12}
            if gig["status"] in ("open", "booked", "working"):
                self.link_gig(st)
            else:
                self.gigs[gig["id"]] = st
        for o in list(self.orders.values()):
            missing = self.missing_legs(o)
            if missing:
                self.dispatch_order_legs(o, missing, False)
        for req in snapshot["openRequests"]:
            if req["respondBy"] > snapshot["now"]:
                self.handle_price_request(req)

    # ---- events ------------------------------------------------------------------------------
    def handle(self, ev) -> None:
        self.now = max(self.now, ev["at"])
        self.day_rollover()
        self.finalize_pending_revenue(ev["at"] - 1)
        k = ev["kind"]
        if k == "forecast":
            self.snow.add_forecast(ev["from"], ev["to"], ev["placeIds"])
        elif k == "price_request":
            self.handle_price_request(ev["request"])
        elif k == "order_won":
            self.handle_order_won(ev["order"], ev["at"])
        elif k == "order_lost":
            meta = self.quote_meta.get(ev["requestId"])
            if meta:
                self.pricing.estimator.on_quote_resolved(meta, None)
        elif k == "order_changed":
            self.handle_order_changed(ev["order"])
        elif k == "order_cancelled":
            self.handle_order_cancelled(ev["orderId"], ev.get("gigs") or [])
        elif k == "gig_viewed":
            self.offers.record_view(ev["driverId"], ev["at"], ev["gigId"])
        elif k == "gig_booked":
            self.handle_gig_booked(ev["gigId"], ev["driverId"], ev["feeCents"], ev["at"])
        elif k == "gig_started":
            g = self.gigs.get(ev["gigId"])
            if g:
                g["status"], g["driverId"], g["startedAt"] = "working", ev["driverId"], ev["at"]
        elif k in ("gig_dropped", "no_show"):
            self.handle_dropped(ev["gigId"], k == "gig_dropped")
        elif k == "driver_late":
            self.handle_driver_late(ev["gigId"], ev["pickupAt"])
        elif k == "gig_expired":
            self.handle_gig_expired(ev["gigId"])
        elif k == "offer_answered":
            self.handle_offer_answered(ev["gigId"], ev["driverId"], ev["answer"])
        elif k == "release":
            self.handle_release(ev["orderId"], ev["leg"], ev["at"])
        elif k == "visit_failed":
            self.handle_visit_failed(ev["gigId"], ev["orderId"], ev["leg"], ev["reason"])
        elif k == "delivered":
            self.handle_delivered(ev["gigId"], ev["orderId"], ev["leg"], ev["placeId"], ev["at"])
        elif k == "deadline_close":
            order = self.orders.get(ev["orderId"])
            if order:
                self.urgent.add(ev["orderId"])
                self.do_not_bundle.add(ev["orderId"])
                self.escalate_urgent(order)
        elif k == "ledger":
            line = ev["line"]
            if line["kind"] in ("late_refund", "undelivered_penalty") and line.get("orderId"):
                self.mark_late(line["orderId"])
            elif line["kind"] == "revenue" and line.get("orderId"):
                o, r = self.orders.get(line["orderId"]), self.requests.get(line["orderId"])
                dealer = (o["dealerId"] if o else None) or (r["dealerId"] if r else None)
                if dealer:
                    self.pending_revenue[line["orderId"]] = {"dealerId": dealer, "at": ev["at"]}

    def handle_price_request(self, req) -> None:
        self.requests[req["id"]] = req
        notes = parse_dealer_note(req)
        self.notes_by_order[req["id"]] = notes
        if req["respondBy"] <= self.now:
            self.pricing.estimator.get_dealer(req["dealerId"])["unquotedCount"] += 1
            return
        meta = self.pricing.quote_request(req, notes, self.quote_ctx(self.now))
        if not meta:
            return
        self.quote_meta[req["id"]] = meta
        self.outbox.append({"type": "quote", "requestId": req["id"], "prices": meta["prices"]})

    def handle_order_won(self, order, at) -> None:
        if order["id"] not in self.requests or order["id"] in self.orders:
            return
        self.orders[order["id"]] = order
        self.order_won_at[order["id"]] = at
        self.won_total += 1
        meta = self.quote_meta.get(order["id"])
        if meta:
            self.pricing.estimator.on_quote_resolved(meta, order["option"])
        self.dispatch_order_legs(order, undelivered_legs(order), True)

    def handle_order_changed(self, order) -> None:
        if order["id"] not in self.orders:
            return
        prev = self.orders[order["id"]]
        self.orders[order["id"]] = order
        oid = order["id"]
        self.omit_soft_cap.discard(oid)
        self.strip_windows.discard(oid)
        self.post_backoff.pop(oid, None)
        self.pairing_buffer.pop(oid, None)
        notes = self.get_notes(oid)
        for l, leg in enumerate(order["legs"]):
            pl = prev["legs"][l] if l < len(prev["legs"]) else None
            if leg["pickup"]["window"]["from"] != (pl["pickup"]["window"]["from"] if pl else None):
                r = self.get_retry(oid, l)
                if r["pickupFrom"] > 0:
                    self.set_retry(oid, l, {**r, "pickupFrom": 0})
            if l < len(notes) and notes[l]:
                if leg["delivery"]["placeId"] != (pl["delivery"]["placeId"] if pl else None):
                    notes[l]["noteDeadline"] = None
                    notes[l]["deliveryHours"] = copy_hours(leg["delivery"].get("hours"))
                elif order["deadline"] > prev["deadline"] and notes[l]["noteDeadline"] is not None:
                    notes[l]["noteDeadline"] = notes[l]["noteDeadline"] + (order["deadline"] - prev["deadline"])
        undel = undelivered_legs(order)
        if undel:
            b = build_stops_for_order(self.map, self.snow, order, undel, notes, self.retries.get(oid) or {}, self.now, self.ends_at)
            self.eff_lpa[oid] = b["effectiveLastPickupAt"]
        displaced = self.remove_unsent_posts(oid)
        to_withdraw = []
        m = self.leg_gigs.get(oid)
        if m:
            for gid in m.values():
                g = self.gigs.get(gid)
                if g and g["status"] == "open" and gid not in to_withdraw:
                    to_withdraw.append(gid)
        partners = []
        for s in displaced:
            if s["orderId"] not in partners:
                partners.append(s["orderId"])
        for gid in to_withdraw:
            g = self.gigs[gid]
            for o in self.live_orders_of_stops(g["stops"]):
                if o["id"] != oid and o["id"] not in partners:
                    partners.append(o["id"])
            g["status"] = "withdrawn"
            self.unlink_gig(gid)
            self.outbox.append({"type": "withdraw", "gigId": gid})
        missing = self.missing_legs(order)
        if missing:
            self.dispatch_order_legs(order, missing, False)
        for pid in partners:
            po = self.orders.get(pid)
            if not po:
                continue
            mp = self.missing_legs(po)
            if mp:
                self.dispatch_order_legs(po, mp, False)

    def handle_order_cancelled(self, oid, cancelled) -> None:
        self.orders.pop(oid, None)
        self.leg_gigs.pop(oid, None)
        self.urgent.discard(oid)
        self.pairing_buffer.pop(oid, None)
        displaced = self.remove_unsent_posts(oid)
        redo = []
        for s in displaced:
            if s["orderId"] not in redo:
                redo.append(s["orderId"])
        for cg in cancelled:
            g = self.gigs.get(cg["gigId"])
            if not g:
                continue
            if cg["outcome"] in ("withdrawn", "released"):
                for o in self.live_orders_of_stops(g["stops"]):
                    if o["id"] != oid and o["id"] not in redo:
                        redo.append(o["id"])
                g["status"] = "withdrawn"
                self.unlink_gig(cg["gigId"])
            else:
                g["stops"] = [s for s in g["stops"] if s["orderId"] != oid]
                g["isBundledTwoOrder"] = len({s["orderId"] for s in g["stops"]}) > 1
        for pid in redo:
            po = self.orders.get(pid)
            if not po:
                continue
            mp = self.missing_legs(po)
            if mp:
                self.dispatch_order_legs(po, mp, False)

    def handle_gig_booked(self, gid, driver, fee, at) -> None:
        self.offers.record_booked(driver, gid, at)
        g = self.gigs.get(gid)
        if g:
            had_withdraw = False
            for i in range(len(self.outbox) - 1, -1, -1):
                a = self.outbox[i]
                if a["type"] == "withdraw" and a["gigId"] == gid:
                    del self.outbox[i]
                    had_withdraw = True
            g["status"], g["driverId"], g["feeCents"], g["bookedAt"] = "booked", driver, fee, at
            self.link_gig(g)
            if had_withdraw:
                booked_ids = {s["orderId"] for s in g["stops"]}
                orphans = []
                for i in range(len(self.outbox) - 1, -1, -1):
                    a = self.outbox[i]
                    if a["type"] == "post" and any(s["orderId"] in booked_ids for s in a["stops"]):
                        for s in a["stops"]:
                            if s["orderId"] not in booked_ids and s["orderId"] not in orphans:
                                orphans.append(s["orderId"])
                        del self.outbox[i]
                for oid in orphans:
                    self.do_not_bundle.add(oid)
                    o = self.orders.get(oid)
                    if not o:
                        continue
                    mp = self.missing_legs(o)
                    if mp:
                        self.dispatch_order_legs(o, mp, False)
        self.queue_direct_offers_for_open_gigs(1)

    def handle_dropped(self, gid, is_drop) -> None:
        g = self.gigs.get(gid)
        if not g:
            return
        if is_drop:
            tod = self.now % DAY
            p0 = g["stops"][0] if g["stops"] else None
            o0 = self.orders.get(p0["orderId"]) if p0 else None
            pick_place = o0["legs"][p0["leg"]]["pickup"]["placeId"] if (o0 and p0["leg"] < len(o0["legs"])) else None
            if (5 * HOUR <= tod <= 9 * HOUR + 30 and g["bookedAt"] is not None and self.now - g["bookedAt"] >= 180
                    and (not pick_place or not self.snow.has_active_snow(pick_place, self.now))):
                self.morning_drops += 1
                if self.morning_drops >= 3:
                    self.flu_today = True
        g["status"], g["driverId"] = "open", None
        self.offers.clear_gig(gid)
        if g["isBundledTwoOrder"]:
            self.split_open_bundle(g)
            return
        order = self.orders.get(g["stops"][0]["orderId"]) if g["stops"] else None
        if not order:
            return
        prev_fee = max(current_schedule_fee(g["schedule"], self.now), g["feeCents"])
        if self.now <= order["lastPickupAt"]:
            self.record_reached_fee(order["id"], jround(prev_fee * 1.03))
        legs = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == order["id"]]
        sched = self.single_schedule(order, legs)
        g["schedule"] = sched
        g["offerWave"] += 1
        self.outbox.append({"type": "reprice", "gigId": g["id"], "schedule": sched})
        self.queue_offers_for_gig(g, 2)

    def handle_driver_late(self, gid, pickup_at) -> None:
        g = self.gigs.get(gid)
        if not g or g["status"] != "booked" or g["isBundledTwoOrder"]:
            return
        p0 = g["stops"][0] if g["stops"] else None
        if not p0:
            return
        order = self.orders.get(p0["orderId"])
        if not order:
            return
        leg0 = order["legs"][p0["leg"]] if p0["leg"] < len(order["legs"]) else None
        if not leg0:
            return
        notes = self.get_notes(order["id"])
        note0 = notes[p0["leg"]] if p0["leg"] < len(notes) else None
        real_pick = co(note0 and note0["pickupHours"], leg0["pickup"].get("hours"))
        violates = False
        if real_pick:
            day = jfloor(pickup_at / DAY)
            wd = day % 7
            slot = real_pick.get("saturday") if wd == 5 else (real_pick if wd in real_pick["weekdays"] else None)
            tod = pickup_at % DAY
            if not slot or tod < slot["opens"] or tod >= slot["closes"]:
                violates = True
        cur = pickup_at
        prev_place = leg0["pickup"]["placeId"]
        n_stops = len(g["stops"])
        for si, s in enumerate(g["stops"]):
            s_leg = order["legs"][s["leg"]] if s["leg"] < len(order["legs"]) else None
            if not s_leg:
                continue
            pl = s_leg["pickup"]["placeId"] if s["kind"] == "pickup" else s_leg["delivery"]["placeId"]
            if si > 0 and pl != prev_place:
                seg = self.map.road_minutes(prev_place, pl)
                sw = 1.30 if self.snow.overlaps(prev_place, pl, cur, cur + seg * 2) else 1.08
                cur += jceil(seg * sw)
            if s["kind"] == "pickup":
                extra = (PLATES_MINUTES if s.get("withPlates") else 0) + (CHARGING_MINUTES if s.get("withCharging") else 0)
                cur += (15 if si == 0 else 10) + extra
            elif si < n_stops - 1:
                cur += 10
            prev_place = pl
        last = g["stops"][-1]
        last_leg = order["legs"][last["leg"]] if last["leg"] < len(order["legs"]) else leg0
        nl = notes[last["leg"]] if last["leg"] < len(notes) else None
        nd = co(nl and nl["noteDeadline"], co(notes[0]["noteDeadline"] if notes else None, INF))
        eff_dl = min(order["deadline"], nd)
        real_deliv = co(nl and nl["deliveryHours"], last_leg["delivery"].get("hours"))
        misses = not isfinite(visit_at(cur, eff_dl, real_deliv, 1))
        eff_lpa = self.eff_lpa.get(order["id"], order["lastPickupAt"])
        q30 = self.supply.pool30(leg0["pickup"]["placeId"], g["audience"]["experienced"], g["audience"]["manualLicence"])
        if violates or (misses and eff_lpa - self.now >= 95 and q30 >= 4):
            g["status"] = "withdrawn"
            self.unlink_gig(gid)
            self.urgent.add(order["id"])
            self.do_not_bundle.add(order["id"])
            self.outbox.append({"type": "release", "gigId": gid})
            mp = self.missing_legs(order)
            if mp:
                self.dispatch_order_legs(order, mp, False)

    def handle_gig_expired(self, gid) -> None:
        g = self.gigs.get(gid)
        if not g:
            return
        had_link = any((self.leg_gigs.get(s["orderId"]) or {}).get(s["leg"]) == gid for s in g["stops"])
        live_fee = current_schedule_fee(g["schedule"], self.now)
        g["status"] = "withdrawn"
        self.unlink_gig(gid)
        if not had_link:
            return
        for order in self.live_orders_of_stops(g["stops"]):
            missing = self.missing_legs(order)
            eff = self.eff_lpa.get(order["id"], order["lastPickupAt"])
            if not g["isBundledTwoOrder"] and self.now <= order["lastPickupAt"]:
                self.record_reached_fee(order["id"], live_fee)
            if self.now >= eff - 2:
                self.omit_soft_cap.add(order["id"])
            if eff - self.now < 420:
                self.do_not_bundle.add(order["id"])
            if missing:
                self.dispatch_order_legs(order, missing, False)

    def handle_offer_answered(self, gid, driver, answer) -> None:
        self.offers.record_offer_answered(gid, driver, answer)
        g = self.gigs.get(gid)
        if not g:
            return
        if answer == "accepted":
            g["status"], g["driverId"] = "booked", driver
            return
        if g["status"] == "open" and self.offers.open_count(gid) == 0 and g["offerWave"] < 2:
            g["offerWave"] += 1
            self.queue_offers_for_gig(g, 1)

    def handle_release(self, oid, leg, at) -> None:
        notes = self.get_notes(oid)
        if leg < len(notes) and notes[leg]:
            notes[leg]["releasedAt"] = at
        cur = self.get_retry(oid, leg)
        self.set_retry(oid, leg, {**cur, "pickupFrom": 0})
        self.post_backoff.pop(oid, None)
        order = self.orders.get(oid)
        if not order or order["deliveredAt"][leg] is not None:
            return
        if oid in self.pairing_buffer:
            return
        gid = (self.leg_gigs.get(oid) or {}).get(leg)
        if not gid:
            if self.has_pending_post(oid, leg):
                stale = any(a["type"] == "post" and any(s["orderId"] == oid and s["leg"] == leg and s["kind"] == "pickup"
                                                        and (s["window"]["from"] if s.get("window") else 0) > self.now + 15 for s in a["stops"])
                            for a in self.outbox)
                if stale:
                    self.handle_order_changed(order)
                return
            mp = self.missing_legs(order, check_outbox=True)
            if mp:
                self.dispatch_order_legs(order, mp, False)
            return
        g = self.gigs.get(gid)
        if g and g["status"] == "open":
            p = next((s for s in g["stops"] if s["orderId"] == oid and s["leg"] == leg and s["kind"] == "pickup"), None)
            if p and p.get("window") and p["window"]["from"] > self.now + 15:
                self.handle_order_changed(order)

    def handle_visit_failed(self, gid, oid, leg, reason) -> None:
        order = self.orders.get(oid)
        if not order:
            return
        m = self.leg_gigs.get(oid)
        if m is not None:
            m.pop(leg, None)
        self.do_not_bundle.add(oid)
        g = self.gigs.get(gid)
        if g:
            g["stops"] = [s for s in g["stops"] if not (s["orderId"] == oid and s["leg"] == leg)]
            remaining = False
            for s in g["stops"]:
                if s["kind"] != "pickup":
                    continue
                o = self.orders.get(s["orderId"])
                if o and o["deliveredAt"][s["leg"]] is None:
                    remaining = True
                    break
            if not remaining:
                g["status"] = "done"
        req = self.requests.get(oid)
        prev = self.get_retry(oid, leg)
        not_there = reason in ("not_ready", "closed")
        pf = self.retry_from(order, req, leg, self.now) if (not_there and req) else prev["pickupFrom"]
        self.set_retry(oid, leg, {"pickupFrom": pf, "manualLicence": prev["manualLicence"] or reason == "licence",
                                  "plates": prev["plates"] or reason == "no_plates"})
        mp = self.missing_legs(order, check_outbox=True)
        if mp:
            self.dispatch_order_legs(order, mp, False)

    def handle_delivered(self, gid, oid, leg, place, at) -> None:
        g = self.gigs.get(gid)
        self.offers.record_delivered(g["driverId"] if g else None, place, at)
        m = self.leg_gigs.get(oid)
        if m is not None:
            m.pop(leg, None)
        self.needs_offer_pass = True
        for og in self.gigs.values():
            if og["status"] != "open" or not og["stops"]:
                continue
            o = self.orders.get(og["stops"][0]["orderId"])
            leg0 = o["legs"][og["stops"][0]["leg"]] if o and og["stops"][0]["leg"] < len(o["legs"]) else None
            if leg0 and self.map.dist_km(place, leg0["pickup"]["placeId"]) <= 35:
                og["nextOfferCheckAt"] = self.now
        order = self.orders.get(oid)
        if order:
            order["deliveredAt"][leg] = at
        if g:
            remaining = False
            for s in g["stops"]:
                if s["kind"] != "pickup":
                    continue
                o = self.orders.get(s["orderId"])
                if o and o["deliveredAt"][s["leg"]] is None:
                    remaining = True
                    break
            if not remaining:
                g["status"] = "done"

    def escalate_urgent(self, order) -> None:
        oid = order["id"]
        self.urgent.add(oid)
        self.do_not_bundle.add(oid)
        for a in self.outbox:
            if a["type"] == "post" and any(s["orderId"] == oid for s in a["stops"]):
                meta = a.get("_meta")
                if meta and not meta["isBundledTwoOrder"]:
                    legs = [s["leg"] for s in a["stops"] if s["kind"] == "pickup" and s["orderId"] == oid]
                    a["schedule"] = self.single_schedule(order, legs)
                    meta["urgentEscalated"] = True
        m = self.leg_gigs.get(oid)
        if not m:
            return
        gids = list(dict.fromkeys(m.values()))
        for gid in gids:
            g = self.gigs.get(gid)
            if not g or g["status"] != "open":
                continue
            if g["isBundledTwoOrder"]:
                self.split_open_bundle(g)
                continue
            past = self.now > order["deadline"]
            if (g["urgentEscalated"] and g["urgentEscalatedAt"] is not None and self.now - g["urgentEscalatedAt"] <= 6 * HOUR
                    and not (past and not g["pastDeadlineEscalated"])):
                g["offerWave"] += 1
                self.queue_offers_for_gig(g, 3)
                continue
            legs = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == oid]
            sched = self.single_schedule(order, legs)
            g["schedule"] = sched
            g["urgentEscalated"], g["urgentEscalatedAt"], g["pastDeadlineEscalated"] = True, self.now, past
            g["offerWave"] += 1
            self.outbox.append({"type": "reprice", "gigId": g["id"], "schedule": sched})
            self.queue_offers_for_gig(g, 3)

    def split_open_bundle(self, g) -> None:
        if g["status"] != "open" or not g["isBundledTwoOrder"]:
            return
        in_bundle = self.live_orders_of_stops(g["stops"])
        g["status"] = "withdrawn"
        self.unlink_gig(g["id"])
        self.outbox.append({"type": "withdraw", "gigId": g["id"]})
        if len(in_bundle) >= 3 and all(o["id"] not in self.urgent and self.eff_lpa.get(o["id"], o["lastPickupAt"]) - self.now >= 280 for o in in_bundle):
            third = in_bundle[-1]
            self.do_not_bundle.add(third["id"])
            o0, o1 = in_bundle[0], in_bundle[1]
            m0 = self.missing_legs(o0)
            if m0:
                self.dispatch_order_legs(o0, m0, False)
            m1 = self.missing_legs(o1)
            if m1:
                self.pairing_buffer[o0["id"]] = self.now + 5
                self.remove_unsent_posts(o0["id"])
                self.dispatch_order_legs(o1, m1, True)
                if o0["id"] in self.pairing_buffer:
                    del self.pairing_buffer[o0["id"]]
                    self.dispatch_order_legs(o0, m0, False)
            for oi in in_bundle[2:]:
                self.do_not_bundle.add(oi["id"])
                mi = self.missing_legs(oi)
                if mi:
                    self.dispatch_order_legs(oi, mi, False)
            return
        for o in in_bundle:
            self.do_not_bundle.add(o["id"])
            mp = self.missing_legs(o)
            if mp:
                self.dispatch_order_legs(o, mp, False)

    def retry_from(self, order, req, leg, now) -> int:
        promised = next((o["deadline"] for o in req["options"] if o["kind"] == order["option"]), order["deadline"])
        delay = max(0, order["deadline"] - promised)
        return max(now + 90, order["legs"][leg]["pickup"]["window"]["from"] + delay)

    def changed_km_scale(self, order, req, legs) -> float:
        route = 0
        orig = 0
        for i in legs:
            route = route + self.map.road_km(order["legs"][i]["pickup"]["placeId"], order["legs"][i]["delivery"]["placeId"])
        for i in legs:
            orig = orig + self.map.road_km(req["legs"][i]["pickup"]["placeId"], req["legs"][i]["delivery"]["placeId"])
        if abs(route - orig) > 5:
            return min(2.25, max(0.45, (1500 + 26 * route) / max(1500, 1500 + 26 * orig)))
        return 1.0

    def _high_trust(self, order) -> bool:
        return self.level == 8 and self.pricing.estimator.get_dealer(order["dealerId"])["trust"] >= 6

    def single_schedule(self, order, legs, built=None):
        req = self.requests[order["id"]]
        notes = self.get_notes(order["id"])
        omit = order["id"] in self.omit_soft_cap or self.now > order["lastPickupAt"]
        b = built or build_stops_for_order(self.map, self.snow, order, legs, notes, self.retries.get(order["id"]) or {}, self.now, self.ends_at, omit)
        self.eff_lpa[order["id"]] = b["effectiveLastPickupAt"]
        first, last = order["legs"][legs[0]], order["legs"][legs[-1]]
        route = 0
        for i in legs:
            route = route + self.map.road_km(order["legs"][i]["pickup"]["placeId"], order["legs"][i]["delivery"]["placeId"])
        scale = self.changed_km_scale(order, req, legs)
        base_ref = ((req["referenceFeeCents"] * len(legs)) / len(order["legs"])) * scale
        p_stop = b["stops"][0]
        earliest = max(self.now, p_stop["window"]["from"] if p_stop.get("window") else first["pickup"]["window"]["from"])
        snow = bool(self.snow.overlaps(first["pickup"]["placeId"], last["delivery"]["placeId"], earliest, order["deadline"]))
        high = self._high_trust(order)
        past = self.now > order["deadline"]
        urgent = past or order["id"] in self.urgent or b["effectiveLastPickupAt"] - self.now <= (245 if high else 210)
        floor_fee = self.max_reached_fee.get(order["id"], 1) if self.now <= order["lastPickupAt"] else 1
        schedule = build_single_gig_schedule(self.map, self.supply, {
            "now": self.now, "endsAt": self.ends_at, "level": self.level, "baseRefFeeCents": base_ref, "orderPriceCents": order["priceCents"],
            "minFloorFeeCents": floor_fee, "routeKm": route, "pickupPlaceId": first["pickup"]["placeId"],
            "deliveryPlaceId": last["delivery"]["placeId"], "effectiveLastPickupAt": b["effectiveLastPickupAt"],
            "rawLastPickupAt": order["lastPickupAt"], "earliestPickupAt": earliest, "audience": b["audience"],
            "hasPrivatePickup": any(order["legs"][i]["pickup"]["privateAddress"] for i in legs),
            "hasPrivateDelivery": any(order["legs"][i]["delivery"]["privateAddress"] for i in legs),
            "isTradeInTwoLegs": len(legs) == 2 and len(order["legs"]) == 2, "withCharging": bool(p_stop.get("withCharging")),
            "withPlates": bool(p_stop.get("withPlates")), "snowOverlap": snow, "fluActive": self.flu_today, "urgent": urgent,
            "isPastDeadline": past, "highTrustDealer": high})
        fee_mult = self.params.get("driver_fee_mult", 1.0)
        if fee_mult != 1.0:
            prev = 0
            for step in schedule:
                step["feeCents"] = max(prev, max(1, jround(step["feeCents"] * fee_mult)))
                prev = step["feeCents"]
        return schedule

    def _entry(self, o, built, won_default):
        return {"order": o, "request": self.requests[o["id"]], "notes": self.get_notes(o["id"]), "built": built,
                "wonAt": self.order_won_at.get(o["id"], won_default)}

    def dispatch_order_legs(self, order, legs, allow_bundle) -> None:
        req = self.requests.get(order["id"])
        if not req or not legs:
            return
        if len(legs) == 2:
            l0, l1 = order["legs"][legs[0]], order["legs"][legs[1]]
            same = l0["delivery"]["placeId"] == l1["pickup"]["placeId"] and l0["delivery"]["privateAddress"] and l1["pickup"]["privateAddress"]
            link = 0 if same else self.map.road_minutes(l0["delivery"]["placeId"], l1["pickup"]["placeId"])
            total = (self.map.road_minutes(l0["pickup"]["placeId"], l0["delivery"]["placeId"]) + link
                     + self.map.road_minutes(l1["pickup"]["placeId"], l1["delivery"]["placeId"]))
            if total > 12 * HOUR:
                for single in legs:
                    self.dispatch_order_legs(order, [single], False)
                return
        oid = order["id"]
        notes = self.get_notes(oid)
        retries = self.retries.get(oid) or {}
        omit = oid in self.omit_soft_cap or self.now > order["lastPickupAt"]
        built = build_stops_for_order(self.map, self.snow, order, legs, notes, retries, self.now, self.ends_at, omit)
        self.eff_lpa[oid] = built["effectiveLastPickupAt"]
        if built["awaitingPrivateSlotRollover"]:
            return

        if (allow_bundle and self.params.get("bundling", 1) and self.level >= 3 and len(legs) == 1 and len(order["legs"]) == 1 and oid not in self.urgent
                and oid not in self.do_not_bundle):
            target = {"order": order, "request": req, "notes": notes, "built": built, "wonAt": self.order_won_at.get(oid, self.now)}
            cands, cand_gig = [], {}
            for g in self.gigs.values():
                if g["status"] != "open" or not g["isBundledTwoOrder"] or len(g["stops"]) != 4:
                    continue
                if self.now - g["postedAt"] > 85:
                    continue
                o1, o2 = self.orders.get(g["stops"][0]["orderId"]), self.orders.get(g["stops"][2]["orderId"])
                if not o1 or not o2 or o1["id"] == oid or o2["id"] == oid:
                    continue
                if (o1["id"] in self.urgent or o2["id"] in self.urgent or o1["id"] in self.do_not_bundle or o2["id"] in self.do_not_bundle):
                    continue
                if o1["deliveredAt"][0] is not None or o2["deliveredAt"][0] is not None:
                    continue
                if o1["id"] not in self.requests or o2["id"] not in self.requests:
                    continue
                b1 = build_stops_for_order(self.map, self.snow, o1, [0], self.get_notes(o1["id"]), self.retries.get(o1["id"]) or {}, self.now, self.ends_at)
                b2 = build_stops_for_order(self.map, self.snow, o2, [0], self.get_notes(o2["id"]), self.retries.get(o2["id"]) or {}, self.now, self.ends_at)
                if b1["awaitingPrivateSlotRollover"] or b2["awaitingPrivateSlotRollover"]:
                    continue
                e1, e2 = self._entry(o1, b1, g["postedAt"]), self._entry(o2, b2, g["postedAt"])
                ext = None
                for a_, b_, c_ in ((e1, e2, target), (e1, target, e2), (target, e1, e2), (e2, e1, target), (e2, target, e1), (target, e2, e1)):
                    ext = try_extend_two_to_three(self.map, self.snow, self.supply, a_, b_, c_, self.now, self.flu_today)
                    if ext:
                        break
                if ext:
                    self.pairing_buffer.pop(oid, None)
                    g["status"] = "withdrawn"
                    self.unlink_gig(g["id"])
                    self.outbox.append({"type": "withdraw", "gigId": g["id"]})
                    self.push_post({"type": "post", "stops": ext["stops"], "audience": ext["audience"], "schedule": ext["schedule"]},
                                   True, ext["splitAt"], False, False, False)
                    return
            for bid in self.pairing_buffer:
                if bid == oid:
                    continue
                co_ = self.orders.get(bid)
                if not co_ or co_["id"] not in self.requests or len(co_["legs"]) != 1 or co_["deliveredAt"][0] is not None:
                    continue
                if co_["id"] in self.urgent or co_["id"] in self.do_not_bundle:
                    continue
                cb = build_stops_for_order(self.map, self.snow, co_, [0], self.get_notes(co_["id"]), self.retries.get(co_["id"]) or {}, self.now, self.ends_at)
                if cb["awaitingPrivateSlotRollover"]:
                    continue
                cands.append(self._entry(co_, cb, self.now))
            for g in self.gigs.values():
                if g["status"] != "open" or g["isBundledTwoOrder"] or len(g["stops"]) != 2:
                    continue
                co_ = self.orders.get(g["stops"][0]["orderId"])
                if not co_ or co_["id"] not in self.requests or len(co_["legs"]) != 1 or co_["deliveredAt"][0] is not None:
                    continue
                if co_["id"] in self.urgent or co_["id"] in self.do_not_bundle:
                    continue
                cb = build_stops_for_order(self.map, self.snow, co_, [0], self.get_notes(co_["id"]), self.retries.get(co_["id"]) or {}, self.now, self.ends_at)
                if cb["awaitingPrivateSlotRollover"]:
                    continue
                cands.append(self._entry(co_, cb, g["postedAt"]))
                cand_gig[co_["id"]] = g
            bundle = find_best_two_order_bundle(self.map, self.snow, self.supply, target, cands, self.now, self.level, self.flu_today)
            if bundle:
                partner = bundle["secondOrderId"] if bundle["firstOrderId"] == oid else bundle["firstOrderId"]
                if partner in self.pairing_buffer:
                    del self.pairing_buffer[partner]
                    self.pairing_buffer.pop(oid, None)
                    self.push_post({"type": "post", "stops": bundle["stops"], "audience": bundle["audience"], "schedule": bundle["schedule"]},
                                   True, bundle["splitAt"], False, False, False)
                    self.needs_offer_pass = True
                    return
                pg = cand_gig.get(partner)
                if pg and pg["status"] == "open":
                    pg["status"] = "withdrawn"
                    self.unlink_gig(pg["id"])
                    self.outbox.append({"type": "withdraw", "gigId": pg["id"]})
                    self.push_post({"type": "post", "stops": bundle["stops"], "audience": bundle["audience"], "schedule": bundle["schedule"]},
                                   True, bundle["splitAt"], False, False, False)
                    self.needs_offer_pass = True
                    return
            leg0 = order["legs"][0]
            cur_day, cur_tod = jfloor(self.now / DAY), self.now % DAY
            n0 = notes[0] if notes else None
            if (cur_day < 5 and 8 * HOUR <= cur_tod <= 17 * HOUR + 40 and not leg0["car"]["premium"] and not leg0["pickup"]["privateAddress"]
                    and not leg0["delivery"]["privateAddress"] and co(n0 and n0["releasedAt"], 0) <= self.now
                    and built["effectiveLastPickupAt"] - self.now >= 480):
                buf = 32 if built["effectiveLastPickupAt"] - self.now >= 900 else 22
                self.pairing_buffer[oid] = self.now + buf
                return

        stripped = oid in self.strip_windows
        if stripped:
            final_stops = []
            for s in built["stops"]:
                leg = order["legs"][s["leg"]] if s["leg"] < len(order["legs"]) else None
                if s["kind"] == "pickup" and leg and leg["pickup"]["privateAddress"]:
                    final_stops.append(s)
                else:
                    final_stops.append({k: v for k, v in s.items() if k != "window"})
        else:
            final_stops = built["stops"]
        sched = self.single_schedule(order, legs, built)
        high = self._high_trust(order)
        past = self.now > order["deadline"]
        urgent = past or oid in self.urgent or built["effectiveLastPickupAt"] - self.now <= (245 if high else 210)
        self.push_post({"type": "post", "stops": final_stops, "audience": built["audience"], "schedule": sched}, False, INF, urgent, past, stripped)
        if urgent:
            self.needs_offer_pass = True

    # ---- direct offers -----------------------------------------------------------------------
    def offer_target(self, g):
        if g["status"] != "open":
            return None
        pickups = [s for s in g["stops"] if s["kind"] == "pickup"]
        delivs = [s for s in g["stops"] if s["kind"] == "delivery"]
        if not pickups or not delivs:
            return None
        first, last = self.orders.get(pickups[0]["orderId"]), self.orders.get(delivs[-1]["orderId"])
        if not first or not last:
            return None
        fl = first["legs"][pickups[0]["leg"]] if pickups[0]["leg"] < len(first["legs"]) else None
        ll = last["legs"][delivs[-1]["leg"]] if delivs[-1]["leg"] < len(last["legs"]) else None
        p_place = fl["pickup"]["placeId"] if fl else None
        d_place = ll["delivery"]["placeId"] if ll else None
        if not p_place or not d_place:
            return None
        ref_sum = 0
        min_lpa = INF
        has_private = False
        any_urgent = g["urgentEscalated"]
        any_past = g["pastDeadlineEscalated"]
        ids = []
        for p in pickups:
            o, r = self.orders.get(p["orderId"]), self.requests.get(p["orderId"])
            if not o or not r:
                continue
            if o["id"] not in ids:
                ids.append(o["id"])
            ref_sum = ref_sum + (r["referenceFeeCents"] / len(o["legs"])) * self.changed_km_scale(o, r, [p["leg"]])
            lpa = self.eff_lpa.get(o["id"], o["lastPickupAt"])
            if lpa < min_lpa:
                min_lpa = lpa
            leg = o["legs"][p["leg"]] if p["leg"] < len(o["legs"]) else None
            if leg and (leg["pickup"]["privateAddress"] or leg["delivery"]["privateAddress"]):
                has_private = True
            if o["id"] in self.urgent:
                any_urgent = True
            if self.now > o["deadline"]:
                any_past = True
        drive = self.road_sum(g["stops"])
        w = pickups[0].get("window")
        earliest = max(self.now, w["from"] if w else first["legs"][pickups[0]["leg"]]["pickup"]["window"]["from"])
        return {"gigId": g["id"], "orderIds": ids, "pickupPlaceId": p_place, "deliveryPlaceId": d_place, "earliestPickupAt": earliest,
                "effectiveLastPickupAt": min_lpa, "driveMinutes": drive, "refFeeCents": ref_sum,
                "currentAppFeeCents": current_schedule_fee(g["schedule"], self.now), "audience": g["audience"], "hasPrivateStop": has_private,
                "urgent": any_urgent, "isPastDeadline": any_past, "offerWave": g["offerWave"]}

    def queue_offers_for_gig(self, g, max_new=2) -> None:
        if self.level < 3 or not self.params.get("direct_offers", 1) or g["status"] != "open":
            return
        target = self.offer_target(g)
        if not target:
            return
        acts = self.offers.select_offers_for_gig(self.map, self.supply, self.active_commitments(), target, self.now, self.level, max_new)
        for a in acts:
            a["feeCents"] = max(1, jround(a["feeCents"] * self.params.get("offer_fee_mult", 1.0)))
            self.offers.record_offer_queued(a["gigId"], a["driverId"], a["feeCents"], self.now)
            self.outbox.append(a)
        g["nextOfferCheckAt"] = self.now + (15 if (target["urgent"] or target["isPastDeadline"]) else 40)

    def queue_direct_offers_for_open_gigs(self, max_per_gig=2, is_final=False) -> None:
        if self.level < 3 or not self.params.get("direct_offers", 1):
            return
        tod = self.now % DAY
        if tod < 7 * HOUR or tod > 22 * HOUR + 45:
            return
        now_ms = time.perf_counter() * 1000
        commitments = self.active_commitments()
        non_urgent = 0
        for g in self.gigs.values():
            if g["status"] != "open":
                continue
            if self.offers.open_count(g["id"]) >= 3:
                continue
            if self.now < g["nextOfferCheckAt"]:
                continue
            target = self.offer_target(g)
            if not target:
                continue
            if is_final and not target["urgent"] and not target["isPastDeadline"]:
                if non_urgent >= 4 or now_ms - self.last_non_urgent_offer_ms < 220:
                    continue
            acts = self.offers.select_offers_for_gig(self.map, self.supply, commitments, target, self.now, self.level, max_per_gig)
            for a in acts:
                a["feeCents"] = max(1, jround(a["feeCents"] * self.params.get("offer_fee_mult", 1.0)))
                self.offers.record_offer_queued(a["gigId"], a["driverId"], a["feeCents"], self.now)
                self.outbox.append(a)
                if not target["urgent"] and not target["isPastDeadline"]:
                    non_urgent += 1
                    self.last_non_urgent_offer_ms = now_ms
            g["nextOfferCheckAt"] = self.now + (12 if (target["urgent"] or target["isPastDeadline"]) else 40)

    # ---- timers ------------------------------------------------------------------------------
    def tick_timers(self, is_final=False) -> None:
        self.day_rollover()
        self.finalize_pending_revenue(self.now if self.now >= self.ends_at else self.now - 1)
        for bid, release_at in list(self.pairing_buffer.items()):
            if self.now >= release_at or bid in self.urgent:
                self.pairing_buffer.pop(bid, None)
                o = self.orders.get(bid)
                if o:
                    mp = self.missing_legs(o, check_outbox=True)
                    if mp:
                        if bid not in self.urgent and bid not in self.do_not_bundle:
                            self.do_not_bundle.add("__flush_guard__")
                            self.dispatch_order_legs(o, mp, True)
                            if bid in self.pairing_buffer:
                                del self.pairing_buffer[bid]
                                self.dispatch_order_legs(o, mp, False)
                            self.do_not_bundle.discard("__flush_guard__")
                        else:
                            self.dispatch_order_legs(o, mp, False)
        for o in list(self.orders.values()):
            if o["id"] in self.pairing_buffer:
                continue
            if self.post_backoff.get(o["id"], 0) > self.now:
                continue
            mp = self.missing_legs(o, check_outbox=True)
            if mp:
                self.do_not_bundle.add(o["id"])
                self.dispatch_order_legs(o, mp, False)
        tod = self.now % DAY
        awake = 7 * HOUR <= tod <= 22 * HOUR + 40
        for g in list(self.gigs.values()):
            if g["status"] != "open":
                continue
            if g["isBundledTwoOrder"] and self.now >= g["splitAt"]:
                self.split_open_bundle(g)
                continue
            if not g["isBundledTwoOrder"] and g["stops"]:
                o = self.orders.get(g["stops"][0]["orderId"])
                if not o:
                    continue
                fl = o["legs"][g["stops"][0]["leg"]] if g["stops"][0]["leg"] < len(o["legs"]) else None
                first_private = bool(fl and fl["pickup"]["privateAddress"])
                min_road = self.map.road_minutes(fl["pickup"]["placeId"], o["legs"][-1]["delivery"]["placeId"]) if fl else 0
                on_time_posted = g["postedAt"] <= o["lastPickupAt"] and g["postedAt"] + min_road <= o["deadline"]
                if not first_private and not g["zombieCleared"] and on_time_posted and self.now > o["lastPickupAt"]:
                    g["status"], g["zombieCleared"] = "withdrawn", True
                    self.unlink_gig(g["id"])
                    self.outbox.append({"type": "withdraw", "gigId": g["id"]})
                    self.omit_soft_cap.add(o["id"])
                    self.urgent.add(o["id"])
                    self.do_not_bundle.add(o["id"])
                    mp = self.missing_legs(o)
                    if mp:
                        self.dispatch_order_legs(o, mp, False)
                    continue
                if not g["pastDeadlineEscalated"] and awake and self.now > o["deadline"] + 30:
                    self.escalate_urgent(o)
                    continue
                if not g["urgentEscalated"] and awake:
                    eff = self.eff_lpa.get(o["id"], o["lastPickupAt"])
                    lead = 240 if self._high_trust(o) else 195
                    if eff - self.now <= lead:
                        self.escalate_urgent(o)
        if self.needs_offer_pass:
            self.needs_offer_pass = False
            self.queue_direct_offers_for_open_gigs(2, is_final)
        else:
            self.queue_direct_offers_for_open_gigs(1, is_final)

    def next_timer_at(self) -> int:
        if self.needs_offer_pass:
            tod = self.now % DAY
            if 7 * HOUR <= tod <= 22 * HOUR + 40:
                return self.now + 2
        nxt = self.ends_at
        for r in self.pairing_buffer.values():
            if r > self.now:
                nxt = min(nxt, r)
        day0 = jfloor(self.now / DAY) * DAY
        flush = day0 + 7 * HOUR + 5
        nxt = min(nxt, flush) if self.now < flush else min(nxt, day0 + DAY + 7 * HOUR + 5)

        def wake(t):
            tt = t % DAY
            if tt > 22 * HOUR + 40:
                return (jfloor(t / DAY) + 1) * DAY + 7 * HOUR + 5
            if tt < 7 * HOUR:
                return jfloor(t / DAY) * DAY + 7 * HOUR + 5
            return t

        for g in self.gigs.values():
            if g["status"] != "open":
                continue
            if g["isBundledTwoOrder"] and g["splitAt"] > self.now:
                nxt = min(nxt, g["splitAt"])
            if g["nextOfferCheckAt"] > self.now:
                ct = g["nextOfferCheckAt"] % DAY
                if 7 * HOUR <= ct <= 22 * HOUR + 45:
                    nxt = min(nxt, g["nextOfferCheckAt"])
            if not g["isBundledTwoOrder"] and g["stops"]:
                o = self.orders.get(g["stops"][0]["orderId"])
                if not o:
                    continue
                fl = o["legs"][g["stops"][0]["leg"]] if g["stops"][0]["leg"] < len(o["legs"]) else None
                min_road = self.map.road_minutes(fl["pickup"]["placeId"], o["legs"][-1]["delivery"]["placeId"]) if fl else 0
                if (not g["zombieCleared"] and not (fl and fl["pickup"]["privateAddress"]) and g["postedAt"] <= o["lastPickupAt"]
                        and g["postedAt"] + min_road <= o["deadline"]):
                    z = o["lastPickupAt"] + 1
                    if z > self.now:
                        nxt = min(nxt, z)
                if not g["pastDeadlineEscalated"]:
                    r = wake(o["deadline"] + 31)
                    if r > self.now:
                        nxt = min(nxt, r)
                if not g["urgentEscalated"]:
                    eff = self.eff_lpa.get(o["id"], o["lastPickupAt"])
                    trig = wake(eff - (240 if self._high_trust(o) else 195))
                    if trig > self.now:
                        nxt = min(nxt, trig)
        return max(self.now + 1, nxt)

    # ---- sending -----------------------------------------------------------------------------
    def drain_outbox_sorted(self):
        if not self.outbox:
            return []
        acts, self.outbox = self.outbox, []
        acts.sort(key=lambda a: ACTION_PRIORITY[a["type"]])
        return acts

    def send(self, is_final=False) -> None:
        if not self.outbox:
            return
        if not is_final:
            acts = self.drain_outbox_sorted()
            if acts:
                self.read_results(acts, self.world.act(wire(acts)))
            return
        quotes = [a for a in self.outbox if a["type"] == "quote"]
        self.outbox = [a for a in self.outbox if a["type"] != "quote"]
        for i in range(0, len(quotes), 20):
            chunk = quotes[i:i + 20]
            self.read_results(chunk, self.world.act(wire(chunk)))
        cancels = [a for a in self.outbox if a["type"] in ("withdraw", "release")]
        self.outbox = [a for a in self.outbox if a["type"] not in ("withdraw", "release")]
        if cancels:
            self.read_results(cancels, self.world.act(wire(cancels)))
        rest = self.drain_outbox_sorted()
        if rest:
            self.read_results(rest, self.world.act(wire(rest)))

    def read_results(self, actions, results) -> None:
        for i, a in enumerate(actions):
            res = results[i] if i < len(results) else None
            if not res:
                continue
            t = a["type"]
            if t == "quote":
                if not res.get("ok"):
                    r = self.requests.get(a["requestId"])
                    if r:
                        self.pricing.estimator.get_dealer(r["dealerId"])["unquotedCount"] += 1
            elif t == "post":
                meta = a.get("_meta")
                if res.get("ok"):
                    immediate = bool(meta and (meta["urgentEscalated"] or meta["pastDeadlineEscalated"]))
                    self.link_gig({"id": res["id"], "stops": a["stops"], "audience": a["audience"], "schedule": a["schedule"], "status": "open",
                                   "postedAt": self.now, "bookedAt": None, "startedAt": None,
                                   "feeCents": a["schedule"][0]["feeCents"] if a["schedule"] else 0, "driverId": None,
                                   "isBundledTwoOrder": meta["isBundledTwoOrder"] if meta else False,
                                   "splitAt": meta["splitAt"] if meta else INF,
                                   "urgentEscalated": meta["urgentEscalated"] if meta else False,
                                   "urgentEscalatedAt": self.now if (meta and meta["urgentEscalated"]) else None,
                                   "pastDeadlineEscalated": meta["pastDeadlineEscalated"] if meta else False, "zombieCleared": False,
                                   "offerWave": 0, "nextOfferCheckAt": self.now if immediate else self.now + 12})
                else:
                    for o in self.live_orders_of_stops(a["stops"]):
                        self.do_not_bundle.add(o["id"])
                        if meta and meta["strippedFallback"]:
                            self.post_backoff[o["id"]] = self.now + 5
                            continue
                        if not (meta and meta["isBundledTwoOrder"]):
                            self.strip_windows.add(o["id"])
                        mp = self.missing_legs(o, check_outbox=True)
                        if mp:
                            self.dispatch_order_legs(o, mp, False)
            elif t == "offer":
                if not res.get("ok"):
                    self.offers.rollback_offer_refused(a["gigId"], a["driverId"], self.now, res.get("reason", ""))
            elif t in ("withdraw", "release"):
                if not res.get("ok"):
                    g = self.gigs.get(a["gigId"])
                    reason = res.get("reason", "") or ""
                    if g and _BOOK.search(reason):
                        g["status"] = "working" if _START.search(reason) else "booked"
                        self.link_gig(g)
                        covered = {s["orderId"] for s in g["stops"]}
                        orphans = []
                        for k in range(len(self.outbox) - 1, -1, -1):
                            c = self.outbox[k]
                            if c["type"] == "post" and any(s["orderId"] in covered for s in c["stops"]):
                                for s in c["stops"]:
                                    if s["orderId"] not in covered and s["orderId"] not in orphans:
                                        orphans.append(s["orderId"])
                                del self.outbox[k]
                        for pid in orphans:
                            self.do_not_bundle.add(pid)
                            po = self.orders.get(pid)
                            if not po:
                                continue
                            mp = self.missing_legs(po)
                            if mp:
                                self.dispatch_order_legs(po, mp, False)


def wire(actions):
    """The actions as JSON sends them from JavaScript: whole floats become integers, Infinity never leaves."""
    def fix(v):
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    return [fix(a) for a in actions]
