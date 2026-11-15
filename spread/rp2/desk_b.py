"""Second half of the Desk (desk.ts lines 1137-end): gig/offer event handlers, escalation, bundling, dispatch,
direct offers, timers and the outbox transmission. `class Desk(DeskB)` in rp2/desk.py holds the constructor, the fields
and the methods of lines 1-1136. Python port of RoutePulse v21e, exact to the cent."""
from __future__ import annotations

import re
import time

from .bundling import find_best_two_order_bundle, try_extend_two_to_three_order_bundle
from .dispatch import build_single_gig_schedule, bump_schedule_after_drop, current_schedule_fee
from .js import INF, co, isfinite, jceil, jround, sum_js
from .planner import (CHARGING_MINUTES, MAX_MULTI_CAR_ROAD_MINUTES, PLATES_MINUTES, build_stops_for_order, visit_at)
from .rptime import DAY, HOUR, clamp_trigger_to_awake_window, day_of, day_start_of, opening_slot_for_day

_REFUSED_IGNORE = re.compile(r"withdrawn|expired|not open|not found|unknown|already released", re.IGNORECASE | re.ASCII)
_DONE = re.compile(r"done|deliver|complete", re.IGNORECASE | re.ASCII)
_WORKING = re.compile(r"start|work|mov|left", re.IGNORECASE | re.ASCII)


# ---- helpers (module level) -------------------------------------------------------------------------
def sadd(s, k) -> None:
    """Set.add on whatever the Desk half uses for a Set (dict of keys or python set)."""
    if isinstance(s, dict):
        s[k] = True
    else:
        s.add(k)


def sdel(s, k) -> None:
    """Set.delete / Map.delete."""
    if isinstance(s, dict):
        s.pop(k, None)
    else:
        s.discard(k)


def has_multiple_orders_in_stops(stops) -> bool:
    if len(stops) <= 1:
        return False
    first_id = stops[0]["orderId"]
    for i in range(1, len(stops)):
        if stops[i]["orderId"] != first_id:
            return True
    return False


def _at(lst, i):
    """lst[i] with JS out-of-range semantics (undefined -> None)."""
    return lst[i] if 0 <= i < len(lst) else None


def _note_get(note, key):
    return note.get(key) if note is not None else None


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


class _WireWorld:
    """Adapter: the outbox calls world.act(actions); the Python kit client wants the JSON-clean form."""

    def __init__(self, world):
        self.world = world

    def act(self, actions):
        return self.world.act(wire(actions))


class DeskB:
    # ---- gig events ---------------------------------------------------------------------------------
    def handle_gig_booked(self, gig_id, driver_id, fee_cents, at) -> None:
        g = self.gigs.get(gig_id)
        if g and g["status"] == "booked" and g["driverId"] == driver_id:
            g["feeCents"] = fee_cents
            if g["bookedAt"] is None:
                g["bookedAt"] = at
            return
        self.offers.record_booked(driver_id, gig_id, at)
        if g:
            had_pending_withdraw = self.outbox.remove_withdraw_for_gig(gig_id)
            g["status"] = "booked"
            g["driverId"] = driver_id
            g["feeCents"] = fee_cents
            g["bookedAt"] = at
            self.link_gig(g)

            if had_pending_withdraw:
                booked_order_ids = dict.fromkeys(s["orderId"] for s in g["stops"])
                orphaned_orders = self.outbox.remove_posts_overlapping_orders(booked_order_ids)
                for oid in orphaned_orders:
                    sadd(self.do_not_bundle, oid)
                    o = self.orders.get(oid)
                    if not o:
                        continue
                    missing = self.unscheduled_legs_for_order(o)
                    if len(missing) > 0:
                        self.dispatch_order_legs(o, missing, False)

        self.queue_direct_offers_for_open_gigs(1, self.is_final)

    def handle_gig_dropped_or_no_show(self, gig_id, is_drop) -> None:
        g = self.gigs.get(gig_id)
        if not g:
            return

        if is_drop and not self.flu_used_this_week and day_of(self.now) < 5:
            tod = self.now % DAY
            p0 = _at(g["stops"], 0)
            o0 = self.orders.get(p0["orderId"]) if p0 else None
            pick_place = None
            if p0 and o0:
                l0 = _at(o0["legs"], p0["leg"])
                pick_place = l0["pickup"]["placeId"] if l0 else None
            if (tod < 90 and g["bookedAt"] is not None and self.now - g["bookedAt"] >= 120
                    and (not pick_place or not self.snow.has_active_snow(pick_place, self.now))):
                self.record_midnight_flu_drop()

        g["status"] = "open"
        g["driverId"] = None
        self.offers.clear_gig(gig_id)

        if g["isBundledTwoOrder"]:
            b_orders = self.distinct_live_orders_of_stops(g["stops"])
            min_bundle_lpa = (min(co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"]) for o in b_orders)
                              if len(b_orders) > 0 else -INF)
            st = self.measure_stops_road_stats(g["stops"])
            total_bundle_road, max_bundle_dh = st["totalRoadMinutes"], st["maxDeadheadMinutes"]
            drop_tod = self.now % DAY
            if (len(b_orders) >= 2
                    and max_bundle_dh <= 65
                    and (drop_tod < 90 or drop_tod >= 21 * HOUR or total_bundle_road <= 430)
                    and total_bundle_road <= 675
                    and min_bundle_lpa - self.now >= 320
                    and all(o["id"] not in self.urgent for o in b_orders)):
                day_start = day_start_of(self.now)
                bumped = bump_schedule_after_drop(g["schedule"], self.now)
                g["schedule"] = bumped
                if drop_tod < 7 * HOUR:
                    g["splitAt"] = min(min_bundle_lpa - 210, max(self.now + 115, day_start + 9 * HOUR + 15))
                    g["nextOfferCheckAt"] = day_start + 7 * HOUR + 10
                elif drop_tod >= 21 * HOUR and day_of(min_bundle_lpa) > day_of(self.now):
                    g["splitAt"] = min(min_bundle_lpa - 230, max(self.now + 115, day_start + DAY + 9 * HOUR + 15))
                    g["nextOfferCheckAt"] = day_start + DAY + 7 * HOUR + 10
                else:
                    g["splitAt"] = min(self.now + 115, min_bundle_lpa - 230)
                    g["nextOfferCheckAt"] = self.now + 10
                g["offerWave"] += 1
                self.outbox.push({"type": "reprice", "gigId": g["id"], "schedule": bumped})
                return
            self.split_open_bundle(g)
            return

        s0 = _at(g["stops"], 0)
        order = self.orders.get(s0["orderId"]) if s0 else None
        if not order:
            return

        prev_live_fee = max(current_schedule_fee(g["schedule"], self.now), g["feeCents"])
        if self.now <= order["lastPickupAt"]:
            self.record_order_reached_fee(order["id"], jround(prev_live_fee * 1.03))

        leg_indices = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == order["id"]]
        new_schedule = self.compute_single_schedule(order, leg_indices)
        g["schedule"] = new_schedule
        g["offerWave"] += 1
        self.outbox.push({"type": "reprice", "gigId": g["id"], "schedule": new_schedule})
        self.queue_offers_for_single_gig(g, 2)

    def handle_driver_late(self, gig_id, pickup_at) -> None:
        g = self.gigs.get(gig_id)
        if not g or g["status"] != "booked":
            return
        p0 = _at(g["stops"], 0)
        if not p0:
            return
        order = self.orders.get(p0["orderId"])
        if not order:
            return

        if g["isBundledTwoOrder"]:
            b_orders = self.distinct_live_orders_of_stops(g["stops"])
            min_eff_lpa = (min(co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"]) for o in b_orders)
                           if len(b_orders) > 0 else -INF)
            misses_stop0_cap = p0.get("window") is not None and pickup_at > p0["window"]["to"]
            if misses_stop0_cap and min_eff_lpa - self.now >= 140:
                g["status"] = "withdrawn"
                self.unlink_gig(gig_id)
                self.outbox.push({"type": "release", "gigId": gig_id})
                for bo in b_orders:
                    sadd(self.do_not_bundle, bo["id"])
                    missing = self.unscheduled_legs_for_order(bo)
                    if len(missing) > 0:
                        self.dispatch_order_legs(bo, missing, False)
            return

        leg0 = _at(order["legs"], p0["leg"])
        if not leg0:
            return
        notes = self.get_notes(order["id"])
        note0 = _at(notes, p0["leg"])

        real_pick_hours = co(_note_get(note0, "pickupHours"), leg0["pickup"].get("hours"))
        violates_real_pickup_close = False
        if real_pick_hours:
            slot = opening_slot_for_day(real_pick_hours, day_of(pickup_at))
            tod = pickup_at % DAY
            if not slot or tod < slot["opens"] or tod >= slot["closes"]:
                violates_real_pickup_close = True

        cur_time = pickup_at
        prev_place = leg0["pickup"]["placeId"]
        for si in range(len(g["stops"])):
            s = g["stops"][si]
            s_leg = _at(order["legs"], s["leg"])
            if not s_leg:
                continue
            pl = s_leg["pickup"]["placeId"] if s["kind"] == "pickup" else s_leg["delivery"]["placeId"]
            if si > 0 and pl != prev_place:
                seg = self.map.road_minutes(prev_place, pl)
                sw = 1.30 if self.snow.overlaps(prev_place, pl, cur_time, cur_time + seg * 2) else 1.08
                cur_time += jceil(seg * sw)
            if s["kind"] == "pickup":
                extra = (PLATES_MINUTES if s.get("withPlates") else 0) + (CHARGING_MINUTES if s.get("withCharging") else 0)
                cur_time += (15 if si == 0 else 10) + extra
            elif si < len(g["stops"]) - 1:
                cur_time += 10
            prev_place = pl
        last_stop = g["stops"][-1]
        last_leg = co(_at(order["legs"], last_stop["leg"]), leg0)
        n_last = _at(notes, last_stop["leg"])
        n_first = _at(notes, 0)
        eff_dl = min(order["deadline"],
                     co(_note_get(n_last, "noteDeadline"), co(_note_get(n_first, "noteDeadline"), INF)))
        real_deliv_hours = co(_note_get(n_last, "deliveryHours"), last_leg["delivery"].get("hours"))
        misses_delivery = not isfinite(visit_at(cur_time, eff_dl, real_deliv_hours, 1))
        eff_lpa = co(self.effective_last_pickup_by_order.get(order["id"]), order["lastPickupAt"])
        q30 = self.supply.pool30(leg0["pickup"]["placeId"], g["audience"]["experienced"], g["audience"]["manualLicence"])

        if (violates_real_pickup_close
                or (misses_delivery and ((order["lastPickupAt"] - self.now >= 65 and q30 >= 15)
                                         or (eff_lpa - self.now >= 95 and q30 >= 4)))):
            g["status"] = "withdrawn"
            self.unlink_gig(gig_id)
            sadd(self.urgent, order["id"])
            sadd(self.do_not_bundle, order["id"])
            self.outbox.push({"type": "release", "gigId": gig_id})
            missing = self.unscheduled_legs_for_order(order)
            if len(missing) > 0:
                self.dispatch_order_legs(order, missing, False)

    def handle_gig_expired(self, gig_id) -> None:
        g = self.gigs.get(gig_id)
        if not g:
            return
        had_active_link = any((self.leg_gigs.get(s["orderId"]) or {}).get(s["leg"]) == gig_id for s in g["stops"])
        expired_live_fee = current_schedule_fee(g["schedule"], self.now)
        g["status"] = "withdrawn"
        self.unlink_gig(gig_id)
        if not had_active_link:
            return

        for order in self.distinct_live_orders_of_stops(g["stops"]):
            missing = self.unscheduled_legs_for_order(order)
            eff_lpa = co(self.effective_last_pickup_by_order.get(order["id"]), order["lastPickupAt"])
            if not g["isBundledTwoOrder"] and self.now <= order["lastPickupAt"]:
                self.record_order_reached_fee(order["id"], expired_live_fee)
            if self.now >= eff_lpa - 2:
                sadd(self.omit_soft_cap_orders, order["id"])
            if eff_lpa - self.now < 420:
                sadd(self.do_not_bundle, order["id"])
            if len(missing) > 0:
                self.dispatch_order_legs(order, missing, False)

    def handle_offer_answered(self, gig_id, driver_id, answer) -> None:
        offered_fee = (self.offers.open_offers_by_gig.get(gig_id) or {}).get(driver_id)
        self.offers.record_offer_answered(gig_id, driver_id, answer)
        g = self.gigs.get(gig_id)
        if not g:
            return
        if answer == "accepted":
            self.handle_gig_booked(gig_id, driver_id, co(offered_fee, g["feeCents"]), self.now)
            return
        if g["status"] == "open" and self.offers.open_count(gig_id) == 0 and g["offerWave"] < 2:
            g["offerWave"] += 1
            self.queue_offers_for_single_gig(g, 1)

    def handle_release_event(self, order_id, leg, at) -> None:
        notes = self.get_notes(order_id)
        if _at(notes, leg):
            notes[leg]["releasedAt"] = at
        cur = self.get_leg_retry(order_id, leg)
        self.set_leg_retry(order_id, leg, {**cur, "pickupFrom": 0})
        self.post_backoff_until.pop(order_id, None)

        order = self.orders.get(order_id)
        if not order or order["deliveredAt"][leg] is not None:
            return
        if order_id in self.pairing_buffer_until:
            return

        gid = (self.leg_gigs.get(order_id) or {}).get(leg)
        if not gid:
            if self.outbox.has_pending_post_for_leg(order_id, leg):
                if self.outbox.has_stale_pending_release_post(order_id, leg, self.now + 15):
                    self.handle_order_changed(order)
                return
            missing = self.unscheduled_legs_for_order(order, True)
            if len(missing) > 0:
                self.dispatch_order_legs(order, missing, True)
            return
        g = self.gigs.get(gid)
        if g and g["status"] == "open":
            p_stop = next((s for s in g["stops"] if s["orderId"] == order_id and s["leg"] == leg and s["kind"] == "pickup"), None)
            if p_stop and p_stop.get("window") and p_stop["window"]["from"] > self.now + 15:
                self.handle_order_changed(order)

    def handle_visit_failed(self, gig_id, order_id, leg, reason) -> None:
        order = self.orders.get(order_id)
        if not order:
            return
        lg = self.leg_gigs.get(order_id)
        if (lg or {}).get(leg) == gig_id:
            lg.pop(leg, None)
        sadd(self.do_not_bundle, order_id)

        g = self.gigs.get(gig_id)
        if g:
            g["stops"] = [s for s in g["stops"] if not (s["orderId"] == order_id and s["leg"] == leg)]
            g["isBundledTwoOrder"] = has_multiple_orders_in_stops(g["stops"])
            if not self.has_remaining_undelivered_pickups(g["stops"]):
                g["status"] = "done"
                self.unlink_gig(gig_id)

        self.apply_visit_failed_retry(order_id, leg, reason, self.now, order)

        missing = self.unscheduled_legs_for_order(order, True)
        if len(missing) > 0:
            self.dispatch_order_legs(order, missing, False)

    def handle_delivered(self, gig_id, order_id, leg, place_id, at) -> None:
        g = self.gigs.get(gig_id)
        self.offers.record_delivered(g["driverId"] if g else None, place_id, at)
        lg = self.leg_gigs.get(order_id)
        if (lg or {}).get(leg) == gig_id:
            lg.pop(leg, None)
        self.needs_immediate_offer_pass = True

        for open_gig in self.gigs.values():
            if open_gig["status"] != "open" or not _at(open_gig["stops"], 0):
                continue
            o = self.orders.get(open_gig["stops"][0]["orderId"])
            p_leg = _at(o["legs"], open_gig["stops"][0]["leg"]) if o else None
            p_place = p_leg["pickup"]["placeId"] if p_leg else None
            if p_place and self.map.dist_km(place_id, p_place) <= 35:
                open_gig["nextOfferCheckAt"] = self.now

        order = self.orders.get(order_id)
        if order:
            order["deliveredAt"][leg] = at

        if g and not self.has_remaining_undelivered_pickups(g["stops"]):
            g["status"] = "done"
            self.unlink_gig(gig_id)

    def handle_deadline_close(self, order_id) -> None:
        order = self.orders.get(order_id)
        if not order:
            return
        sadd(self.urgent, order_id)
        sadd(self.do_not_bundle, order_id)
        self.escalate_order_urgent(order)

    def escalate_order_urgent(self, order) -> None:
        sadd(self.urgent, order["id"])
        sadd(self.do_not_bundle, order["id"])

        for act in self.outbox.actions:
            if act["type"] == "post" and any(s["orderId"] == order["id"] for s in act["stops"]):
                meta = self.outbox.get_post_meta(act)
                if meta and not meta["isBundledTwoOrder"]:
                    legs = [s["leg"] for s in act["stops"] if s["kind"] == "pickup" and s["orderId"] == order["id"]]
                    act["schedule"] = self.compute_single_schedule(order, legs)
                    meta["urgentEscalated"] = True

        m = self.leg_gigs.get(order["id"])
        if not m:
            return
        gids = dict.fromkeys(m.values())
        for gid in gids:
            g = self.gigs.get(gid)
            if not g or g["status"] != "open":
                continue
            if g["isBundledTwoOrder"]:
                self.split_open_bundle(g)
            else:
                is_past_dl = self.now > order["deadline"]
                is_end_world_rescue = is_past_dl and self.ends_at - self.now <= 42 * HOUR
                if (g["urgentEscalated"]
                        and g["urgentEscalatedAt"] is not None
                        and self.now - g["urgentEscalatedAt"] <= 6 * HOUR
                        and not (is_past_dl and not g["pastDeadlineEscalated"])
                        and not (is_end_world_rescue and not g["endWorldRescueEscalated"])):
                    g["offerWave"] += 1
                    self.queue_offers_for_single_gig(g, 3)
                    continue
                legs = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == order["id"]]
                sched = self.compute_single_schedule(order, legs)
                g["schedule"] = sched
                g["urgentEscalated"] = True
                g["urgentEscalatedAt"] = self.now
                g["pastDeadlineEscalated"] = is_past_dl
                g["endWorldRescueEscalated"] = is_end_world_rescue
                g["offerWave"] += 1
                self.outbox.push({"type": "reprice", "gigId": g["id"], "schedule": sched})
                self.queue_offers_for_single_gig(g, 3)

    # ---- Dispatch & Bundling -------------------------------------------------------------------------
    def split_open_bundle(self, g) -> None:
        if g["status"] != "open" or not g["isBundledTwoOrder"]:
            return
        orders_in_bundle = self.distinct_live_orders_of_stops(g["stops"])
        g["status"] = "withdrawn"
        self.unlink_gig(g["id"])
        self.outbox.push({"type": "withdraw", "gigId": g["id"]})

        if (len(orders_in_bundle) >= 3
                and all(o["id"] not in self.urgent
                        and co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"]) - self.now >= 280
                        for o in orders_in_bundle)):
            third = orders_in_bundle[-1]
            sadd(self.do_not_bundle, third["id"])
            o0 = orders_in_bundle[0]
            o1 = orders_in_bundle[1]
            m0 = self.unscheduled_legs_for_order(o0)
            if len(m0) > 0:
                self.dispatch_order_legs(o0, m0, False)
            m1 = self.unscheduled_legs_for_order(o1)
            if len(m1) > 0:
                self.pairing_buffer_until[o0["id"]] = self.now + 5
                self.outbox.remove_posts_for_order(o0["id"])
                self.dispatch_order_legs(o1, m1, True)
                if o0["id"] in self.pairing_buffer_until:
                    del self.pairing_buffer_until[o0["id"]]
                    self.dispatch_order_legs(o0, m0, False)
            for idx in range(2, len(orders_in_bundle)):
                oi = orders_in_bundle[idx]
                sadd(self.do_not_bundle, oi["id"])
                mi = self.unscheduled_legs_for_order(oi)
                if len(mi) > 0:
                    self.dispatch_order_legs(oi, mi, False)
            return

        for o in orders_in_bundle:
            sadd(self.do_not_bundle, o["id"])
            missing = self.unscheduled_legs_for_order(o)
            if len(missing) > 0:
                self.dispatch_order_legs(o, missing, False)

    def compute_retry_from(self, order, request, leg, now):
        promised = co(next((o["deadline"] for o in request["options"] if o["kind"] == order["option"]), None), order["deadline"])
        delay = max(0, order["deadline"] - promised)
        return max(now + 90, order["legs"][leg]["pickup"]["window"]["from"] + delay)

    def changed_km_scale_for_order(self, order, req, leg_indices):
        def leg_est_ref(p, d):
            km = self.map.road_km(p, d)
            return 1450 + 7.5 * km if self.map.is_same_cluster30(p, d) else 1850 + 24 * km

        olegs, rlegs = order["legs"], req["legs"]
        route_km = sum_js(self.map.road_km(olegs[i]["pickup"]["placeId"], olegs[i]["delivery"]["placeId"]) for i in leg_indices)
        orig_km = sum_js(self.map.road_km(rlegs[i]["pickup"]["placeId"], rlegs[i]["delivery"]["placeId"]) for i in leg_indices)
        new_est = sum_js(leg_est_ref(olegs[i]["pickup"]["placeId"], olegs[i]["delivery"]["placeId"]) for i in leg_indices)
        orig_est = sum_js(leg_est_ref(rlegs[i]["pickup"]["placeId"], rlegs[i]["delivery"]["placeId"]) for i in leg_indices)
        if abs(route_km - orig_km) <= 5 and abs(new_est - orig_est) <= 80:
            return 1.0

        raw_ratio = new_est / max(1200, orig_est)
        base_orig_ref = (req["referenceFeeCents"] * len(leg_indices)) / max(1, len(olegs))
        has_extra_car_cost = any(
            olegs[i]["car"].get("premium")
            or self.map.needs_charging(olegs[i]["car"], olegs[i]["pickup"]["placeId"], olegs[i]["delivery"]["placeId"])
            for i in leg_indices)
        if abs(route_km - orig_km) > 150 and not has_extra_car_cost and base_orig_ref > 0:
            target_ref = 0.65 * (base_orig_ref * raw_ratio) + 0.35 * new_est
            return min(8.5, max(0.45, target_ref / base_orig_ref))
        return min(8.5, max(0.45, raw_ratio))

    def evaluate_order_urgency(self, order, pickup_place_id, audience, effective_last_pickup_at):
        dealer = self.pricing.estimator.get_dealer(order["dealerId"])
        high_trust = self.level == 8 and dealer["trust"] >= 6
        q30 = self.supply.pool30(pickup_place_id, audience["experienced"], audience["manualLicence"])
        is_past_deadline = self.now > order["deadline"]
        is_urgent = (is_past_deadline
                     or order["id"] in self.urgent
                     or effective_last_pickup_at - self.now <= (185 if (high_trust or q30 <= 12) else 155))
        return {"highTrust": high_trust, "isPastDeadline": is_past_deadline, "isUrgent": is_urgent}

    def urgent_warn_lead_minutes(self, order, first_stop_leg, audience):
        dealer = self.pricing.estimator.get_dealer(order["dealerId"])
        q30 = (self.supply.pool30(first_stop_leg["pickup"]["placeId"], audience["experienced"], audience["manualLicence"])
               if first_stop_leg else 0)
        return 180 if ((self.level == 8 and dealer["trust"] >= 8) or q30 <= 12) else 145

    def is_zombie_candidate(self, g, ord_) -> bool:
        if g["zombieCleared"] or not _at(g["stops"], 0):
            return False
        first_stop_leg = _at(ord_["legs"], g["stops"][0]["leg"])
        if first_stop_leg and first_stop_leg["pickup"].get("privateAddress"):
            return False
        min_road = (self.map.road_minutes(first_stop_leg["pickup"]["placeId"], ord_["legs"][-1]["delivery"]["placeId"])
                    if first_stop_leg else 0)
        return g["postedAt"] <= ord_["lastPickupAt"] and g["postedAt"] + min_road <= ord_["deadline"]

    def compute_single_schedule(self, order, leg_indices, built=None):
        req = self.requests.get(order["id"])
        notes = self.get_notes(order["id"])
        retries_map = co(self.retries.get(order["id"]), {})
        omit_soft_cap = order["id"] in self.omit_soft_cap_orders or self.now > order["lastPickupAt"]
        b = built if built is not None else build_stops_for_order(
            self.map, self.snow, order, leg_indices, notes, retries_map, self.now, self.ends_at, omit_soft_cap)
        self.effective_last_pickup_by_order[order["id"]] = b["effectiveLastPickupAt"]

        first_leg = order["legs"][leg_indices[0]]
        last_leg = order["legs"][leg_indices[-1]]
        route_km = sum_js(self.map.road_km(order["legs"][i]["pickup"]["placeId"], order["legs"][i]["delivery"]["placeId"])
                          for i in leg_indices)
        changed_km_scale = self.changed_km_scale_for_order(order, req, leg_indices)
        base_ref_fee_cents = ((req["referenceFeeCents"] * len(leg_indices)) / len(order["legs"])) * changed_km_scale
        p_stop = b["stops"][0]
        earliest_pickup_at = max(self.now, co((p_stop.get("window") or {}).get("from"), first_leg["pickup"]["window"]["from"]))
        snow_overlap = bool(self.snow.overlaps(first_leg["pickup"]["placeId"], last_leg["delivery"]["placeId"],
                                               earliest_pickup_at, order["deadline"]))
        u = self.evaluate_order_urgency(order, first_leg["pickup"]["placeId"], b["audience"], b["effectiveLastPickupAt"])
        min_floor_fee_cents = co(self.max_reached_fee_by_order.get(order["id"]), 1) if self.now <= order["lastPickupAt"] else 1

        return build_single_gig_schedule(self.map, self.supply, {
            "now": self.now,
            "endsAt": self.ends_at,
            "level": self.level,
            "baseRefFeeCents": base_ref_fee_cents,
            "orderPriceCents": order["priceCents"],
            "minFloorFeeCents": min_floor_fee_cents,
            "routeKm": route_km,
            "pickupPlaceId": first_leg["pickup"]["placeId"],
            "deliveryPlaceId": last_leg["delivery"]["placeId"],
            "effectiveLastPickupAt": b["effectiveLastPickupAt"],
            "rawLastPickupAt": order["lastPickupAt"],
            "earliestPickupAt": earliest_pickup_at,
            "tier24PickupCapAt": b["tier24PickupCapAt"],
            "audience": b["audience"],
            "hasPrivatePickup": any(order["legs"][i]["pickup"].get("privateAddress") for i in leg_indices),
            "hasPrivateDelivery": any(order["legs"][i]["delivery"].get("privateAddress") for i in leg_indices),
            "isTradeInTwoLegs": len(leg_indices) == 2 and len(order["legs"]) == 2,
            "withCharging": bool(p_stop.get("withCharging")),
            "withPlates": bool(p_stop.get("withPlates")),
            "snowOverlap": snow_overlap,
            "fluActive": self.flu_active_today,
            "urgent": u["isUrgent"],
            "isPastDeadline": u["isPastDeadline"],
            "highTrustDealer": u["highTrust"],
        })

    def try_extend_open_bundle_to_three(self, target_entry) -> bool:
        order_id = target_entry["order"]["id"]
        for g in list(self.gigs.values()):
            if g["status"] != "open" or not g["isBundledTwoOrder"] or len(g["stops"]) != 4:
                continue
            if self.now - g["postedAt"] > 85:
                continue
            o1 = self.orders.get(g["stops"][0]["orderId"])
            o2 = self.orders.get(g["stops"][2]["orderId"])
            if not o1 or not o2 or o1["id"] == order_id or o2["id"] == order_id:
                continue
            if (o1["id"] in self.urgent or o2["id"] in self.urgent
                    or o1["id"] in self.do_not_bundle or o2["id"] in self.do_not_bundle):
                continue
            if o1["deliveredAt"][0] is not None or o2["deliveredAt"][0] is not None:
                continue
            r1 = self.requests.get(o1["id"])
            r2 = self.requests.get(o2["id"])
            if not r1 or not r2:
                continue
            n1 = self.get_notes(o1["id"])
            n2 = self.get_notes(o2["id"])
            b1 = build_stops_for_order(self.map, self.snow, o1, [0], n1, co(self.retries.get(o1["id"]), {}), self.now, self.ends_at)
            b2 = build_stops_for_order(self.map, self.snow, o2, [0], n2, co(self.retries.get(o2["id"]), {}), self.now, self.ends_at)
            if b1["awaitingPrivateSlotRollover"] or b2["awaitingPrivateSlotRollover"]:
                continue
            e1 = {"order": o1, "request": r1, "notes": n1, "built": b1, "wonAt": co(self.order_won_at.get(o1["id"]), g["postedAt"])}
            e2 = {"order": o2, "request": r2, "notes": n2, "built": b2, "wonAt": co(self.order_won_at.get(o2["id"]), g["postedAt"])}
            ext = None
            for a, b, c in ((e1, e2, target_entry), (e1, target_entry, e2), (target_entry, e1, e2),
                            (e2, e1, target_entry), (e2, target_entry, e1), (target_entry, e2, e1)):
                ext = try_extend_two_to_three_order_bundle(self.map, self.snow, self.supply, a, b, c, self.now, self.flu_active_today)
                if ext is not None:
                    break
            if ext:
                self.pairing_buffer_until.pop(order_id, None)
                g["status"] = "withdrawn"
                self.unlink_gig(g["id"])
                self.outbox.push({"type": "withdraw", "gigId": g["id"]})
                self.outbox.enqueue_post(ext["stops"], ext["audience"], ext["schedule"], {
                    "isBundledTwoOrder": True,
                    "splitAt": ext["splitAt"],
                    "urgentEscalated": False,
                    "pastDeadlineEscalated": False,
                    "endWorldRescueEscalated": False,
                    "strippedFallback": False,
                })
                return True
        return False

    def collect_two_order_bundle_candidates(self, exclude_order_id):
        open_candidates = []
        candidate_gig_by_order = {}

        def try_build_candidate(cand_order_id, fallback_won_at):
            co_ = self.orders.get(cand_order_id)
            creq = self.requests.get(co_["id"]) if co_ else None
            if not co_ or not creq or len(co_["legs"]) != 1 or co_["deliveredAt"][0] is not None:
                return None
            if co_["id"] in self.urgent or co_["id"] in self.do_not_bundle:
                return None
            cnotes = self.get_notes(co_["id"])
            cretries = co(self.retries.get(co_["id"]), {})
            cbuilt = build_stops_for_order(self.map, self.snow, co_, [0], cnotes, cretries, self.now, self.ends_at)
            if cbuilt["awaitingPrivateSlotRollover"]:
                return None
            return {"order": co_, "request": creq, "notes": cnotes, "built": cbuilt,
                    "wonAt": co(self.order_won_at.get(co_["id"]), fallback_won_at)}

        for buffered_id in list(self.pairing_buffer_until.keys()):
            if buffered_id == exclude_order_id:
                continue
            entry = try_build_candidate(buffered_id, self.now)
            if entry:
                open_candidates.append(entry)

        for g in self.gigs.values():
            if g["status"] != "open" or g["isBundledTwoOrder"] or len(g["stops"]) != 2:
                continue
            cand_id = g["stops"][0]["orderId"]
            entry = try_build_candidate(cand_id, g["postedAt"])
            if entry:
                open_candidates.append(entry)
                candidate_gig_by_order[cand_id] = g

        return {"openCandidates": open_candidates, "candidateGigByOrder": candidate_gig_by_order}

    def dispatch_order_legs(self, order, leg_indices, allow_bundle) -> None:
        req = self.requests.get(order["id"])
        if not req or len(leg_indices) == 0:
            return

        if len(leg_indices) == 2:
            l0 = order["legs"][leg_indices[0]]
            l1 = order["legs"][leg_indices[1]]
            total_road = (self.map.road_minutes(l0["pickup"]["placeId"], l0["delivery"]["placeId"])
                          + self.map.road_minutes(l0["delivery"]["placeId"], l1["pickup"]["placeId"])
                          + self.map.road_minutes(l1["pickup"]["placeId"], l1["delivery"]["placeId"]))
            if total_road > MAX_MULTI_CAR_ROAD_MINUTES:
                for single_leg in leg_indices:
                    self.dispatch_order_legs(order, [single_leg], False)
                return

        notes = self.get_notes(order["id"])
        retries_map = co(self.retries.get(order["id"]), {})
        omit_soft_cap = order["id"] in self.omit_soft_cap_orders or self.now > order["lastPickupAt"]
        built = build_stops_for_order(self.map, self.snow, order, leg_indices, notes, retries_map, self.now, self.ends_at, omit_soft_cap)
        self.effective_last_pickup_by_order[order["id"]] = built["effectiveLastPickupAt"]

        if built["awaitingPrivateSlotRollover"]:
            return

        if (allow_bundle
                and self.level >= 3
                and len(leg_indices) == 1
                and len(order["legs"]) == 1
                and order["id"] not in self.urgent
                and order["id"] not in self.do_not_bundle):
            target_entry = {"order": order, "request": req, "notes": notes, "built": built,
                            "wonAt": co(self.order_won_at.get(order["id"]), self.now)}

            if self.try_extend_open_bundle_to_three(target_entry):
                return

            cc = self.collect_two_order_bundle_candidates(order["id"])
            open_candidates, candidate_gig_by_order = cc["openCandidates"], cc["candidateGigByOrder"]
            bundle = find_best_two_order_bundle(self.map, self.snow, self.supply, target_entry, open_candidates,
                                                self.now, self.level, self.flu_active_today)

            if bundle:
                partner_id = bundle["secondOrderId"] if bundle["firstOrderId"] == order["id"] else bundle["firstOrderId"]
                if partner_id in self.pairing_buffer_until:
                    del self.pairing_buffer_until[partner_id]
                    self.pairing_buffer_until.pop(order["id"], None)
                    self.outbox.enqueue_post(bundle["stops"], bundle["audience"], bundle["schedule"], {
                        "isBundledTwoOrder": True,
                        "splitAt": bundle["splitAt"],
                        "urgentEscalated": False,
                        "pastDeadlineEscalated": False,
                        "endWorldRescueEscalated": False,
                        "strippedFallback": False,
                    })
                    self.needs_immediate_offer_pass = True
                    return

                partner_gig = candidate_gig_by_order.get(partner_id)
                if partner_gig and partner_gig["status"] == "open":
                    partner_gig["status"] = "withdrawn"
                    self.unlink_gig(partner_gig["id"])
                    self.outbox.push({"type": "withdraw", "gigId": partner_gig["id"]})
                    self.outbox.enqueue_post(bundle["stops"], bundle["audience"], bundle["schedule"], {
                        "isBundledTwoOrder": True,
                        "splitAt": bundle["splitAt"],
                        "urgentEscalated": False,
                        "pastDeadlineEscalated": False,
                        "endWorldRescueEscalated": False,
                        "strippedFallback": False,
                    })
                    self.needs_immediate_offer_pass = True
                    return

            leg0 = order["legs"][0]
            cur_day = day_of(self.now)
            cur_tod = self.now % DAY
            cur_day_start = cur_day * DAY
            n0 = _at(notes, 0)
            summer_with_upcoming_snow = bool(
                _note_get(n0, "summerTyres")
                and self.snow.overlaps(leg0["pickup"]["placeId"], leg0["delivery"]["placeId"], self.now, order["deadline"]))
            can_buffer_premium = (not leg0["car"].get("premium")
                                  or self.supply.pool30(leg0["pickup"]["placeId"], True, built["audience"]["manualLicence"]) >= 24)
            if (cur_day < 5
                    and cur_tod >= 8 * HOUR
                    and cur_tod <= 18 * HOUR + 5
                    and can_buffer_premium
                    and not leg0["pickup"].get("privateAddress")
                    and not leg0["delivery"].get("privateAddress")
                    and not summer_with_upcoming_snow
                    and co(_note_get(n0, "releasedAt"), 0) <= self.now
                    and built["effectiveLastPickupAt"] - self.now >= 480):
                pick_from = co((built["stops"][0].get("window") or {}).get("from") if built["stops"] else None,
                               leg0["pickup"]["window"]["from"])
                if pick_from >= cur_day_start + DAY:
                    raw_buf = min(75, max(32, cur_day_start + 18 * HOUR + 5 - self.now))
                elif built["effectiveLastPickupAt"] - self.now >= 1100:
                    raw_buf = 48
                elif built["effectiveLastPickupAt"] - self.now >= 900:
                    raw_buf = 34
                else:
                    raw_buf = 22
                buf_mins = min(raw_buf, 22) if leg0["car"].get("premium") else raw_buf
                self.pairing_buffer_until[order["id"]] = self.now + buf_mins
                return

        use_stripped = order["id"] in self.strip_windows_orders
        if use_stripped:
            final_stops = []
            for s in built["stops"]:
                leg = _at(order["legs"], s["leg"])
                if s["kind"] == "pickup" and leg and leg["pickup"].get("privateAddress"):
                    final_stops.append(s)
                else:
                    final_stops.append({k: v for k, v in s.items() if k != "window"})
        else:
            final_stops = built["stops"]

        schedule = self.compute_single_schedule(order, leg_indices, built)
        u = self.evaluate_order_urgency(order, order["legs"][leg_indices[0]]["pickup"]["placeId"], built["audience"],
                                        built["effectiveLastPickupAt"])
        is_past_deadline, is_urgent = u["isPastDeadline"], u["isUrgent"]
        is_end_world_rescue = is_past_deadline and self.ends_at - self.now <= 42 * HOUR
        self.outbox.enqueue_post(final_stops, built["audience"], schedule, {
            "isBundledTwoOrder": False,
            "splitAt": INF,
            "urgentEscalated": is_urgent,
            "pastDeadlineEscalated": is_past_deadline,
            "endWorldRescueEscalated": is_end_world_rescue,
            "strippedFallback": use_stripped,
        })
        if is_urgent:
            self.needs_immediate_offer_pass = True

    # ---- Direct Offers -------------------------------------------------------------------------------
    def build_offer_target(self, g):
        if g["status"] != "open":
            return None
        pickups = [s for s in g["stops"] if s["kind"] == "pickup"]
        delivs = [s for s in g["stops"] if s["kind"] == "delivery"]
        if len(pickups) == 0 or len(delivs) == 0:
            return None

        first_ord = self.orders.get(pickups[0]["orderId"])
        last_ord = self.orders.get(delivs[-1]["orderId"])
        if not first_ord or not last_ord:
            return None

        fl = _at(first_ord["legs"], pickups[0]["leg"])
        ll = _at(last_ord["legs"], delivs[-1]["leg"])
        p_place = fl["pickup"]["placeId"] if fl else None
        d_place = ll["delivery"]["placeId"] if ll else None
        if not p_place or not d_place:
            return None

        ref_sum = 0
        min_eff_lpa = INF
        has_private = False
        any_urgent = False
        any_past_deadline = False
        order_ids = []

        for p in pickups:
            o = self.orders.get(p["orderId"])
            r = self.requests.get(p["orderId"])
            if not o or not r:
                continue
            if o["id"] not in order_ids:
                order_ids.append(o["id"])
            km_scale = self.changed_km_scale_for_order(o, r, [p["leg"]])
            ref_sum += (r["referenceFeeCents"] / len(o["legs"])) * km_scale
            leg = _at(o["legs"], p["leg"])
            if leg and (leg["pickup"].get("privateAddress") or leg["delivery"].get("privateAddress")):
                has_private = True

            is_post_lpa = self.now > o["lastPickupAt"]
            if is_post_lpa:
                lpa = co((p.get("window") or {}).get("to"), self.ends_at - 45)
            else:
                lpa = co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"])
            if lpa < min_eff_lpa:
                min_eff_lpa = lpa

            if is_post_lpa:
                is_end_world_rescue = self.now > o["deadline"] and self.ends_at - self.now <= 42 * HOUR
                if is_end_world_rescue or bool(leg and leg["delivery"].get("privateAddress")):
                    any_urgent = True
                    if self.now > o["deadline"]:
                        any_past_deadline = True
            else:
                if g["urgentEscalated"] or o["id"] in self.urgent:
                    any_urgent = True
                if g["pastDeadlineEscalated"] or self.now > o["deadline"]:
                    any_past_deadline = True

        drive_minutes = self.measure_stops_road_stats(g["stops"])["totalRoadMinutes"]
        earliest_pickup_at = max(
            self.now,
            co((pickups[0].get("window") or {}).get("from"), first_ord["legs"][pickups[0]["leg"]]["pickup"]["window"]["from"]))

        return {
            "gigId": g["id"],
            "orderIds": order_ids,
            "pickupPlaceId": p_place,
            "deliveryPlaceId": d_place,
            "earliestPickupAt": earliest_pickup_at,
            "effectiveLastPickupAt": min_eff_lpa,
            "driveMinutes": drive_minutes,
            "refFeeCents": ref_sum,
            "currentAppFeeCents": current_schedule_fee(g["schedule"], self.now),
            "audience": g["audience"],
            "hasPrivateStop": has_private,
            "urgent": any_urgent,
            "isPastDeadline": any_past_deadline,
            "offerWave": g["offerWave"],
        }

    def queue_offers_for_single_gig(self, g, max_new=2) -> None:
        if self.level < 3 or g["status"] != "open":
            return
        tod = self.now % DAY
        if tod < 7 * HOUR or tod > 22 * HOUR + 45:
            day_start = day_start_of(self.now)
            g["nextOfferCheckAt"] = (day_start + DAY if tod > 22 * HOUR + 45 else day_start) + 7 * HOUR + 10
            return
        target = self.build_offer_target(g)
        if not target:
            return
        commitments = self.active_commitments()
        actions = self.offers.select_offers_for_gig(self.map, self.supply, commitments, target, self.now, self.level, max_new)
        for off in actions:
            self.offers.record_offer_queued(off["gigId"], off["driverId"], off["feeCents"], self.now)
            self.outbox.push(off)
        g["nextOfferCheckAt"] = self.now + (15 if (target["urgent"] or target["isPastDeadline"]) else 40)

    def queue_direct_offers_for_open_gigs(self, max_per_gig=2, is_final=False) -> None:
        if self.level < 3:
            return
        tod = self.now % DAY
        if tod < 7 * HOUR or tod > 22 * HOUR + 45:
            return

        now_ms = time.perf_counter() * 1000
        commitments = self.active_commitments()
        non_urgent_queued = 0

        for g in list(self.gigs.values()):
            if g["status"] != "open":
                continue
            if self.offers.open_count(g["id"]) >= 3:
                continue
            if self.now < g["nextOfferCheckAt"]:
                continue

            target = self.build_offer_target(g)
            if not target:
                continue

            if is_final and not target["urgent"] and not target["isPastDeadline"]:
                if non_urgent_queued >= 4 or now_ms - self.last_non_urgent_offer_ms < 220:
                    continue

            actions = self.offers.select_offers_for_gig(self.map, self.supply, commitments, target, self.now, self.level, max_per_gig)
            for off in actions:
                self.offers.record_offer_queued(off["gigId"], off["driverId"], off["feeCents"], self.now)
                self.outbox.push(off)
                if not target["urgent"] and not target["isPastDeadline"]:
                    non_urgent_queued += 1
                    self.last_non_urgent_offer_ms = now_ms
            g["nextOfferCheckAt"] = self.now + (12 if (target["urgent"] or target["isPastDeadline"]) else 40)

    # ---- Timers & Periodic Maintenance ----------------------------------------------------------------
    def tick_timers(self, is_final=False) -> None:
        self.check_day_rollover()
        self.finalize_pending_revenue(self.now if self.now >= self.ends_at else self.now - 1)

        for buffered_id, release_at in list(self.pairing_buffer_until.items()):
            if self.now >= release_at or buffered_id in self.urgent:
                self.pairing_buffer_until.pop(buffered_id, None)
                ord_ = self.orders.get(buffered_id)
                if ord_:
                    missing = self.unscheduled_legs_for_order(ord_, True)
                    if len(missing) > 0:
                        if ord_["id"] not in self.urgent and ord_["id"] not in self.do_not_bundle:
                            self.dispatch_order_legs_no_rebuffer(ord_, missing)
                        else:
                            self.dispatch_order_legs(ord_, missing, False)

        for order in list(self.orders.values()):
            if order["id"] in self.pairing_buffer_until:
                continue
            if co(self.post_backoff_until.get(order["id"]), 0) > self.now:
                continue
            missing = self.unscheduled_legs_for_order(order, True)
            if len(missing) > 0:
                self.dispatch_order_legs(order, missing, False)

        cur_tod = self.now % DAY
        in_awake_hours = cur_tod >= 7 * HOUR and cur_tod <= 22 * HOUR + 40

        for g in list(self.gigs.values()):
            if g["status"] != "open":
                continue
            if g["isBundledTwoOrder"] and self.now >= g["splitAt"]:
                self.split_open_bundle(g)
                continue

            if not g["isBundledTwoOrder"] and _at(g["stops"], 0):
                ord_ = self.orders.get(g["stops"][0]["orderId"])
                if not ord_:
                    continue

                first_stop_leg = _at(ord_["legs"], g["stops"][0]["leg"])
                ord_notes = self.get_notes(ord_["id"])
                if in_awake_hours and _note_get(_at(ord_notes, 0), "summerTyres") and first_stop_leg:
                    last_ord_leg = ord_["legs"][-1]
                    drive_min = self.map.road_minutes(first_stop_leg["pickup"]["placeId"], last_ord_leg["delivery"]["placeId"])
                    active_sw = self.snow.overlaps(first_stop_leg["pickup"]["placeId"], last_ord_leg["delivery"]["placeId"],
                                                   self.now, self.now + drive_min + 45)
                    cur_from = co((g["stops"][0].get("window") or {}).get("from"), first_stop_leg["pickup"]["window"]["from"])
                    if active_sw and cur_from < active_sw["to"] and active_sw["to"] < ord_["deadline"] - drive_min:
                        legs = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == ord_["id"]]
                        g["status"] = "withdrawn"
                        self.unlink_gig(g["id"])
                        self.outbox.push({"type": "withdraw", "gigId": g["id"]})
                        if len(legs) > 0:
                            self.dispatch_order_legs(ord_, legs, False)
                        continue

                if self.is_zombie_candidate(g, ord_) and self.now > ord_["lastPickupAt"]:
                    g["status"] = "withdrawn"
                    g["zombieCleared"] = True
                    self.unlink_gig(g["id"])
                    self.outbox.push({"type": "withdraw", "gigId": g["id"]})
                    sadd(self.omit_soft_cap_orders, ord_["id"])
                    sadd(self.urgent, ord_["id"])
                    sadd(self.do_not_bundle, ord_["id"])
                    missing = self.unscheduled_legs_for_order(ord_)
                    if len(missing) > 0:
                        self.dispatch_order_legs(ord_, missing, False)
                    continue

                if (not g["endWorldRescueEscalated"] and in_awake_hours and self.now > ord_["deadline"]
                        and self.ends_at - self.now <= 42 * HOUR):
                    self.escalate_order_urgent(ord_)
                    continue
                if not g["pastDeadlineEscalated"] and in_awake_hours and self.now > ord_["deadline"] + 30:
                    self.escalate_order_urgent(ord_)
                    continue
                if not g["urgentEscalated"] and in_awake_hours:
                    eff_lpa = co(self.effective_last_pickup_by_order.get(ord_["id"]), ord_["lastPickupAt"])
                    warn_lead = self.urgent_warn_lead_minutes(ord_, _at(ord_["legs"], g["stops"][0]["leg"]), g["audience"])
                    if eff_lpa - self.now <= warn_lead:
                        self.escalate_order_urgent(ord_)

        if self.needs_immediate_offer_pass:
            self.needs_immediate_offer_pass = False
            self.queue_direct_offers_for_open_gigs(2, is_final)
        else:
            self.queue_direct_offers_for_open_gigs(1, is_final)

    def dispatch_order_legs_no_rebuffer(self, order, leg_indices) -> None:
        self.dispatch_order_legs(order, leg_indices, True)
        if order["id"] in self.pairing_buffer_until:
            del self.pairing_buffer_until[order["id"]]
            self.dispatch_order_legs(order, leg_indices, False)

    def next_timer_at(self):
        if self.needs_immediate_offer_pass:
            tod = self.now % DAY
            if tod >= 7 * HOUR and tod <= 22 * HOUR + 40:
                return self.now + 2

        nxt = self.ends_at
        for release_at in self.pairing_buffer_until.values():
            if release_at > self.now:
                nxt = min(nxt, release_at)
        day_start = day_start_of(self.now)
        morning_flush = day_start + 7 * HOUR + 5
        if self.now < morning_flush:
            nxt = min(nxt, morning_flush)
        else:
            nxt = min(nxt, day_start + DAY + 7 * HOUR + 5)

        for g in self.gigs.values():
            if g["status"] != "open":
                continue
            if g["isBundledTwoOrder"] and g["splitAt"] > self.now:
                nxt = min(nxt, g["splitAt"])
            if g["nextOfferCheckAt"] > self.now:
                check_tod = g["nextOfferCheckAt"] % DAY
                if check_tod >= 7 * HOUR and check_tod <= 22 * HOUR + 45:
                    nxt = min(nxt, g["nextOfferCheckAt"])
            if not g["isBundledTwoOrder"] and _at(g["stops"], 0):
                ord_ = self.orders.get(g["stops"][0]["orderId"])
                if not ord_:
                    continue
                if self.is_zombie_candidate(g, ord_):
                    zombie_at = ord_["lastPickupAt"] + 1
                    if zombie_at > self.now:
                        nxt = min(nxt, zombie_at)
                if not g["endWorldRescueEscalated"]:
                    end_rescue_at = clamp_trigger_to_awake_window(max(ord_["deadline"] + 31, self.ends_at - 42 * HOUR))
                    if end_rescue_at > self.now:
                        nxt = min(nxt, end_rescue_at)
                if not g["pastDeadlineEscalated"]:
                    rescue_at = clamp_trigger_to_awake_window(ord_["deadline"] + 31)
                    if rescue_at > self.now:
                        nxt = min(nxt, rescue_at)
                if not g["urgentEscalated"]:
                    eff_lpa = co(self.effective_last_pickup_by_order.get(ord_["id"]), ord_["lastPickupAt"])
                    warn_lead = self.urgent_warn_lead_minutes(ord_, _at(ord_["legs"], g["stops"][0]["leg"]), g["audience"])
                    trig = clamp_trigger_to_awake_window(eff_lpa - warn_lead)
                    if trig > self.now:
                        nxt = min(nxt, trig)

        return max(self.now + 1, nxt)

    # ---- Outbox & Phased Transmission -----------------------------------------------------------------
    def drain_outbox_sorted(self):
        return self.outbox.drain_sorted()

    def has_pending_quote(self) -> bool:
        return self.outbox.has_pending_quote()

    def send_quotes_only(self) -> None:
        self.outbox.send_quotes_only(_WireWorld(self.world), lambda sent, res: self.read_results(sent, res))

    def send(self, is_final=False) -> None:
        self.outbox.send(_WireWorld(self.world), is_final, lambda sent, res: self.read_results(sent, res))

    def read_results(self, actions, results) -> None:
        for i, action in enumerate(actions):
            res = _at(results, i)
            if not res:
                continue
            t = action["type"]
            if t == "quote":
                if not res.get("ok"):
                    self.unresolved_quotes.pop(action["requestId"], None)
                    req = self.requests.get(action["requestId"])
                    if req:
                        self.pricing.estimator.get_dealer(req["dealerId"])["unquotedCount"] += 1
            elif t == "post":
                meta = self.outbox.get_post_meta(action)
                m = meta if meta is not None else {}
                if res.get("ok"):
                    immediate_offer = bool(m.get("urgentEscalated") or m.get("pastDeadlineEscalated"))
                    gig = {
                        "id": res["id"],
                        "stops": action["stops"],
                        "audience": action["audience"],
                        "schedule": action["schedule"],
                        "status": "open",
                        "postedAt": self.now,
                        "bookedAt": None,
                        "startedAt": None,
                        "feeCents": action["schedule"][0]["feeCents"] if len(action["schedule"]) > 0 else 0,
                        "driverId": None,
                        "isBundledTwoOrder": co(m.get("isBundledTwoOrder"), False),
                        "splitAt": co(m.get("splitAt"), INF),
                        "urgentEscalated": co(m.get("urgentEscalated"), False),
                        "urgentEscalatedAt": self.now if m.get("urgentEscalated") else None,
                        "pastDeadlineEscalated": co(m.get("pastDeadlineEscalated"), False),
                        "endWorldRescueEscalated": co(m.get("endWorldRescueEscalated"), False),
                        "zombieCleared": False,
                        "offerWave": 0,
                        "nextOfferCheckAt": self.now if immediate_offer else self.now + 12,
                    }
                    self.link_gig(gig)
                else:
                    failed_orders = self.distinct_live_orders_of_stops(action["stops"])
                    was_multi_leg_single_order = (
                        not m.get("isBundledTwoOrder")
                        and len(failed_orders) == 1
                        and len([s for s in action["stops"] if s["kind"] == "pickup"]) >= 2)
                    for ord_ in failed_orders:
                        sadd(self.do_not_bundle, ord_["id"])
                        missing = self.unscheduled_legs_for_order(ord_, True)
                        if was_multi_leg_single_order and len(missing) >= 2:
                            for single_leg in missing:
                                self.dispatch_order_legs(ord_, [single_leg], False)
                            continue
                        if m.get("strippedFallback"):
                            self.post_backoff_until[ord_["id"]] = self.now + 5
                            continue
                        if not m.get("isBundledTwoOrder"):
                            sadd(self.strip_windows_orders, ord_["id"])
                        if len(missing) > 0:
                            self.dispatch_order_legs(ord_, missing, False)
            elif t == "offer":
                if not res.get("ok"):
                    self.offers.rollback_offer_refused(action["gigId"], action["driverId"], self.now, res.get("reason"))
            elif t == "withdraw" or t == "release":
                if not res.get("ok"):
                    g = self.gigs.get(action["gigId"])
                    rr = res.get("reason")
                    reason = "undefined" if rr is None else str(rr)  # RegExp.test(undefined) tests "undefined"
                    if g and not _REFUSED_IGNORE.search(reason):
                        g["status"] = ("done" if _DONE.search(reason)
                                       else "working" if _WORKING.search(reason) else "booked")
                        if g["status"] != "done":
                            self.link_gig(g)
                        covered_legs = dict.fromkeys(f"{s['orderId']}:{s['leg']}" for s in g["stops"] if s["kind"] == "pickup")
                        covered_orders = dict.fromkeys(s["orderId"] for s in g["stops"])
                        orphaned_partners = self.outbox.remove_posts_overlapping_pickup_legs(covered_legs, covered_orders)
                        for pid in orphaned_partners:
                            sadd(self.do_not_bundle, pid)
                            po = self.orders.get(pid)
                            if not po:
                                continue
                            missing = self.unscheduled_legs_for_order(po)
                            if len(missing) > 0:
                                self.dispatch_order_legs(po, missing, False)
