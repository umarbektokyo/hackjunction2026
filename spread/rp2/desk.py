"""Port of RoutePulse v21e desk.ts lines 1-1136: types, fields, constructor and the methods up to handleGigBooked.
The methods from handleGigBooked on live in desk_b.py (class DeskB); Desk extends it."""
from __future__ import annotations

import functools
import math

from .bundling import find_best_two_order_bundle, try_extend_two_to_three_order_bundle  # noqa: F401
from .dispatch import build_single_gig_schedule, bump_schedule_after_drop, current_schedule_fee  # noqa: F401
from .estimator import unrounded_list_price_cents
from .market import PricingEngine
from .notes import (create_default_leg_note, effective_order_deadline, parse_dealer_note,  # noqa: F401
                    reconcile_notes_after_order_change)
from .offers import DirectOfferTracker
from .outbox import ActionOutbox
from .planner import (build_stops_for_order, CHARGING_MINUTES, EMPTY_RETRY, MapGraph,  # noqa: F401
                      MAX_MULTI_CAR_ROAD_MINUTES, PLATES_MINUTES, SnowTracker, visit_at)
from .rejoin import rejoin_desk_state
from .supply import RosterSupplyModel
from .rptime import (clamp_trigger_to_awake_window, DAY, day_of, day_start_of, HOUR,  # noqa: F401
                     opening_slot_for_day)
from .js import co, jround, jfloor, truthy, INF
from .desk_b import DeskB

# GigState: dict with keys id, stops, audience, schedule, status, postedAt, bookedAt, startedAt, feeCents, driverId,
#   isBundledTwoOrder, splitAt, urgentEscalated, urgentEscalatedAt, pastDeadlineEscalated, endWorldRescueEscalated,
#   zombieCleared, offerWave, nextOfferCheckAt.
# BatchState: dict {"batchId", "seenIds": set, "wonIds": set, "lostIds": set}.


def has_undelivered_legs(order) -> bool:
    for i in range(len(order["legs"])):
        if order["deliveredAt"][i] is None:
            return True
    return False


def undelivered_legs(order) -> list:
    return [i for i in range(len(order["legs"])) if order["deliveredAt"][i] is None]


def has_multiple_orders_in_stops(stops) -> bool:
    if len(stops) <= 1:
        return False
    first_id = stops[0]["orderId"]
    for i in range(1, len(stops)):
        if stops[i]["orderId"] != first_id:
            return True
    return False


def _at(arr, i):
    """arr[i] with JS out-of-range -> undefined (None)."""
    return arr[i] if 0 <= i < len(arr) else None


def _win_from(stop, default):
    """stop.window?.from ?? default"""
    w = stop.get("window")
    return co(w.get("from") if w is not None else None, default)


def _win_to(stop, default):
    w = stop.get("window")
    return co(w.get("to") if w is not None else None, default)


def _cmp_str(a: str, b: str) -> int:
    # localeCompare for plain lowercase/digit/hyphen ids: same order as code-point order
    return -1 if a < b else (1 if a > b else 0)


class Desk(DeskB):
    def __init__(self, world, level, now, ends_at, raw_map, roster=None):
        if roster is None:
            roster = []
        self.snow = SnowTracker()
        self.offers = DirectOfferTracker()
        self.outbox = ActionOutbox()

        self.requests = {}
        self.notes_by_order = {}
        self.quote_meta_by_req = {}
        self.pending_price_requests = {}
        self.unresolved_quotes = {}
        self.batches = {}

        self.orders = {}
        self.order_won_at = {}
        self.effective_last_pickup_by_order = {}
        self.max_reached_fee_by_order = {}
        self.retries = {}
        self.urgent = set()
        self.do_not_bundle = set()
        self.omit_soft_cap_orders = set()
        self.strip_windows_orders = set()
        self.post_backoff_until = {}
        self.pairing_buffer_until = {}

        self.gigs = {}
        self.leg_gigs = {}

        self.start_minute = 0
        self.won_orders_total = 0
        self.delivered_orders_total = 0
        self.delivered_on_time_total = 0
        self.late_or_penalized_orders = set()
        self.pending_revenue_orders = {}
        self.finalized_on_time_orders = {}

        self.flu_day_tracker = -1
        self.midnight_flu_drops = 0
        self.flu_active_today = False
        self.flu_used_this_week = False
        self.needs_immediate_offer_pass = False
        self.last_non_urgent_offer_ms = 0
        self.is_final = False

        self.world = world
        self.level = level
        self.now = now
        self.start_minute = now
        self.ends_at = ends_at
        self.map = MapGraph(raw_map)
        self.supply = RosterSupplyModel(self.map, roster)
        self.pricing = PricingEngine(level, self.map, self.snow, self.supply)

    # --- Core State & Graph Helpers ---

    def record_order_reached_fee(self, order_id, fee_cents) -> None:
        if fee_cents <= 0:
            return
        prev = co(self.max_reached_fee_by_order.get(order_id), 0)
        if fee_cents > prev:
            self.max_reached_fee_by_order[order_id] = fee_cents

    def check_day_rollover(self) -> None:
        day = day_of(self.now)
        if day != self.flu_day_tracker:
            if self.flu_active_today:
                self.flu_used_this_week = True
            self.flu_day_tracker = day
            self.midnight_flu_drops = 0
            self.flu_active_today = False

    def record_midnight_flu_drop(self) -> None:
        self.midnight_flu_drops += 1
        if self.midnight_flu_drops >= (6 if self.supply.total_drivers < 740 else 8):
            self.flu_active_today = True

    def get_leg_retry(self, order_id, leg):
        m = self.retries.get(order_id)
        return co(m.get(leg) if m is not None else None, EMPTY_RETRY)

    def set_leg_retry(self, order_id, leg, nxt) -> None:
        m = self.retries.get(order_id)
        if m is None:
            m = {}
            self.retries[order_id] = m
        m[leg] = nxt

    def apply_visit_failed_retry(self, order_id, leg, reason, at, order) -> None:
        req = self.requests.get(order_id)
        prev = self.get_leg_retry(order_id, leg)
        car_not_there = reason == "not_ready" or reason == "closed"
        if car_not_there and order is not None and req is not None:
            pickup_from = self.compute_retry_from(order, req, leg, at)
        else:
            pickup_from = prev["pickupFrom"]
        self.set_leg_retry(order_id, leg, {
            "pickupFrom": pickup_from,
            "manualLicence": truthy(prev["manualLicence"]) or reason == "licence",
            "plates": truthy(prev["plates"]) or reason == "no_plates",
        })

    def get_notes(self, order_id):
        cached = self.notes_by_order.get(order_id)
        if cached is not None:
            return cached
        req = self.requests.get(order_id)
        if req is not None:
            parsed = parse_dealer_note(req)
            self.notes_by_order[order_id] = parsed
            return parsed
        order = self.orders.get(order_id)
        if order is None:
            return []
        return [create_default_leg_note(l) for l in order["legs"]]

    def link_gig(self, gig) -> None:
        self.gigs[gig["id"]] = gig
        for stop in gig["stops"]:
            if stop["kind"] != "pickup":
                continue
            m = self.leg_gigs.get(stop["orderId"])
            if m is None:
                m = {}
                self.leg_gigs[stop["orderId"]] = m
            m[stop["leg"]] = gig["id"]

    def unlink_gig(self, gig_id) -> None:
        gig = self.gigs.get(gig_id)
        if gig is None:
            return
        for stop in gig["stops"]:
            m = self.leg_gigs.get(stop["orderId"])
            if m is not None and m.get(stop["leg"]) == gig_id:
                del m[stop["leg"]]
        self.offers.clear_gig(gig_id)

    def distinct_live_orders_of_stops(self, stops) -> list:
        seen = set()
        lst = []
        for s in stops:
            if s["orderId"] in seen:
                continue
            seen.add(s["orderId"])
            o = self.orders.get(s["orderId"])
            if o is not None:
                lst.append(o)
        return lst

    def has_remaining_undelivered_pickups(self, stops) -> bool:
        for s in stops:
            if s["kind"] != "pickup":
                continue
            o = self.orders.get(s["orderId"])
            if o is not None and o["deliveredAt"][s["leg"]] is None:
                return True
        return False

    def measure_stops_road_stats(self, stops) -> dict:
        total_road_minutes = 0
        max_deadhead_minutes = 0
        prev_pl = None
        prev_was_deliv = False
        for s in stops:
            o = self.orders.get(s["orderId"])
            leg = _at(o["legs"], s["leg"]) if o is not None else None
            if not leg:
                continue
            pl = leg["pickup"]["placeId"] if s["kind"] == "pickup" else leg["delivery"]["placeId"]
            if prev_pl is not None and prev_pl != pl:
                seg = self.map.road_minutes(prev_pl, pl)
                total_road_minutes += seg
                if prev_was_deliv and s["kind"] == "pickup" and seg > max_deadhead_minutes:
                    max_deadhead_minutes = seg
            prev_was_deliv = s["kind"] == "delivery"
            prev_pl = pl
        return {"totalRoadMinutes": total_road_minutes, "maxDeadheadMinutes": max_deadhead_minutes}

    def unscheduled_legs_for_order(self, order, check_pending_outbox=False) -> list:
        leg_map = self.leg_gigs.get(order["id"])
        out = []
        for i in range(len(order["legs"])):
            if order["deliveredAt"][i] is not None:
                continue
            if leg_map is not None and i in leg_map:
                continue
            if check_pending_outbox and self.outbox.has_pending_post_for_leg(order["id"], i):
                continue
            out.append(i)
        return out

    # --- Portfolio, Load & Synergy Queries ---

    def active_commitments(self) -> list:
        lst = []
        for g in self.gigs.values():
            if (g["status"] != "booked" and g["status"] != "working") or not g["driverId"]:
                continue
            pickups = [s for s in g["stops"] if s["kind"] == "pickup"]
            delivs = [s for s in g["stops"] if s["kind"] == "delivery"]
            if len(pickups) == 0 or len(delivs) == 0:
                continue
            first_ord = self.orders.get(pickups[0]["orderId"])
            last_ord = self.orders.get(delivs[-1]["orderId"])
            if first_ord is None or last_ord is None:
                continue
            fl = _at(first_ord["legs"], pickups[0]["leg"])
            ll = _at(last_ord["legs"], delivs[-1]["leg"])
            p_place = fl["pickup"]["placeId"] if fl is not None else None
            d_place = ll["delivery"]["placeId"] if ll is not None else None
            if not p_place or not d_place:
                continue

            total_road_minutes = self.measure_stops_road_stats(g["stops"])["totalRoadMinutes"]
            if g["status"] == "working" and g["startedAt"] is not None:
                est_start = g["startedAt"]
            else:
                est_start = max(
                    self.now,
                    _win_from(pickups[0], first_ord["legs"][pickups[0]["leg"]]["pickup"]["window"]["from"]),
                )
            est_finish = max(self.now + 5, est_start + total_road_minutes + len(pickups) * 25)
            lst.append({
                "gigId": g["id"],
                "driverId": g["driverId"],
                "status": g["status"],
                "pickupPlaceId": p_place,
                "deliveryPlaceId": d_place,
                "estStartAt": est_start,
                "estFinishAt": est_finish,
                "driveMinutes": total_road_minutes,
            })
        return lst

    def count_unbooked_orders(self):
        count = 0
        for o in self.orders.values():
            if not has_undelivered_legs(o):
                continue
            m = self.leg_gigs.get(o["id"])
            all_booked = True
            in_early_discovery = o["id"] in self.pairing_buffer_until
            for leg in range(len(o["legs"])):
                if o["deliveredAt"][leg] is not None:
                    continue
                gid = m.get(leg) if m is not None else None
                g = self.gigs.get(gid) if gid else None
                if g is None or (g["status"] != "booked" and g["status"] != "working"):
                    all_booked = False
                    if g is not None and g["status"] == "open" and not g["urgentEscalated"] and self.now - g["postedAt"] <= 95:
                        eff_lpa = co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"])
                        if eff_lpa - self.now >= 480:
                            in_early_discovery = True
                    break
            if not all_booked:
                count += 0.55 if in_early_discovery else 1
        return count

    def count_bundled_driver_savings(self):
        saved_slots = 0
        for g in self.gigs.values():
            if not g["isBundledTwoOrder"] or g["status"] == "withdrawn":
                continue
            distinct_orders = set()
            for s in g["stops"]:
                distinct_orders.add(s["orderId"])
            if len(distinct_orders) >= 2:
                saved_slots += 0.55 * (len(distinct_orders) - 1)
        return saved_slots

    def prune_unresolved_quotes(self) -> None:
        for req_id, meta in list(self.unresolved_quotes.items()):
            if meta["request"]["respondBy"] <= self.now or req_id in self.orders:
                del self.unresolved_quotes[req_id]

    def total_unresolved_expected_wins(self):
        total = 0
        for meta in self.unresolved_quotes.values():
            if meta["request"]["respondBy"] > self.now and meta["request"]["id"] not in self.orders:
                total += meta["expectedWinProb"]
        return total

    def record_batch_arrival(self, request) -> None:
        if not truthy(request.get("batchId")):
            return
        st = self.batches.get(request["batchId"])
        if st is None:
            st = {"batchId": request["batchId"], "seenIds": set(), "wonIds": set(), "lostIds": set()}
            self.batches[request["batchId"]] = st
        st["seenIds"].add(request["id"])

    def count_active_orders_on_deadline_day(self, deadline_day):
        count = 0
        for o in self.orders.values():
            if not has_undelivered_legs(o):
                da = o["deliveredAt"]
                last_deliv = da[-1] if len(da) > 0 else None
                if last_deliv is not None and day_of(last_deliv) == deadline_day and day_of(self.now) == deadline_day:
                    count += 0.55
                continue
            if day_of(effective_order_deadline(o, self.get_notes(o["id"]))) == deadline_day:
                count += 1
        for meta in self.unresolved_quotes.values():
            if meta["request"]["respondBy"] <= self.now or meta["request"]["id"] in self.orders:
                continue
            for d in meta["expectedWinsByDeadlineDay"]:
                if d["deadlineDay"] == deadline_day:
                    count += d["expectedWins"]
        return count

    def cluster30_set(self, place_id):
        s = self.map.within30km_set.get(place_id)
        return s if s is not None else {place_id}

    def count_open_pickups_in_cluster30(self, place_id):
        cluster = self.cluster30_set(place_id)
        count = 0
        for g in self.gigs.values():
            if g["status"] != "open":
                continue
            if len(g["stops"]) == 0:
                continue
            p0 = g["stops"][0]
            o = self.orders.get(p0["orderId"])
            leg = _at(o["legs"], p0["leg"]) if o is not None else None
            p_id = leg["pickup"]["placeId"] if leg is not None else None
            if p_id and p_id in cluster:
                eff_lpa = co(self.effective_last_pickup_by_order.get(o["id"]), o["lastPickupAt"]) if o is not None else 0
                in_discovery = (not g["urgentEscalated"]) and self.now - g["postedAt"] <= 95 and eff_lpa - self.now >= 480
                count += 0.55 if in_discovery else 1
        return count

    def count_pending_pickups_in_cluster30(self, place_id):
        cluster = self.cluster30_set(place_id)
        count = 0
        for act in self.outbox.actions:
            if act["type"] != "post" or not act["stops"]:
                continue
            p0 = act["stops"][0]
            o = self.orders.get(p0["orderId"])
            leg = _at(o["legs"], p0["leg"]) if o is not None else None
            p_id = leg["pickup"]["placeId"] if leg is not None else None
            if p_id and p_id in cluster:
                count += 1
        for buffered_id in self.pairing_buffer_until.keys():
            o = self.orders.get(buffered_id)
            if o is None:
                continue
            undel = undelivered_legs(o)
            if len(undel) == 0:
                continue
            leg0 = undel[0]
            lg = self.leg_gigs.get(o["id"])
            if (lg is not None and leg0 in lg) or self.outbox.has_pending_post_for_leg(o["id"], leg0):
                continue
            l0 = _at(o["legs"], leg0)
            p_id = l0["pickup"]["placeId"] if l0 is not None else None
            if p_id and p_id in cluster:
                count += 1
        for meta in self.unresolved_quotes.values():
            if meta["request"]["respondBy"] <= self.now or meta["request"]["id"] in self.orders:
                continue
            l0 = _at(meta["request"]["legs"], 0)
            p_id = l0["pickup"]["placeId"] if l0 is not None else None
            if p_id and p_id in cluster:
                count += meta["expectedWinProb"]
        return count

    def count_overdue_undelivered_orders(self):
        count = 0
        for o in self.orders.values():
            if not has_undelivered_legs(o):
                continue
            if self.now > effective_order_deadline(o, self.get_notes(o["id"])):
                count += 1
        return count

    def count_in_flight_dealer_orders(self, dealer_id):
        count = 0
        for o in self.orders.values():
            if o["dealerId"] != dealer_id or not has_undelivered_legs(o):
                continue
            if self.now <= effective_order_deadline(o, self.get_notes(o["id"])):
                count += 0.96
        for meta in self.unresolved_quotes.values():
            if meta["request"]["dealerId"] != dealer_id:
                continue
            if meta["request"]["respondBy"] <= self.now or meta["request"]["id"] in self.orders:
                continue
            count += meta["expectedWinProb"]
        return count

    def has_arriving_driver_synergy(self, pickup_id, delivery_id, earliest_min, latest_min) -> bool:
        comms = self.active_commitments()
        for c in comms:
            if self.map.dist_km(c["deliveryPlaceId"], pickup_id) > 35:
                continue
            link = self.map.road_minutes(c["deliveryPlaceId"], pickup_id)
            if c["estFinishAt"] + link < earliest_min - 90 or c["estFinishAt"] + link > latest_min - 30:
                continue
            prof = self.supply.by_id.get(c["driverId"])
            if prof is not None and self.map.dist_km(prof["homePlaceId"], delivery_id) <= 35:
                return True
        return False

    def matches_round_trip_partner_order(self, o, pickup_id, delivery_id) -> bool:
        if o is None or len(o["legs"]) != 1:
            return False
        l = o["legs"][0]
        if truthy(l["car"]["premium"]) or truthy(l["pickup"]["privateAddress"]) or truthy(l["delivery"]["privateAddress"]):
            return False
        return (
            self.map.road_minutes(l["delivery"]["placeId"], pickup_id) <= 50
            and self.map.road_minutes(delivery_id, l["pickup"]["placeId"]) <= 120
        )

    def compute_round_trip_partner_credit(self, current_req_id, pickup_id, delivery_id, earliest_pickup_at,
                                          effective_last_pickup_at, effective_deadline):
        for buffered_id in self.pairing_buffer_until.keys():
            if self.matches_round_trip_partner_order(self.orders.get(buffered_id), pickup_id, delivery_id):
                return 1.0
        for g in self.gigs.values():
            if g["status"] != "open" or g["isBundledTwoOrder"] or len(g["stops"]) != 2:
                continue
            if self.matches_round_trip_partner_order(self.orders.get(g["stops"][0]["orderId"]), pickup_id, delivery_id):
                return 1.0
        if effective_last_pickup_at - self.now < 300:
            return 0
        my_ready_day = day_of(earliest_pickup_at)
        my_dl_day = day_of(effective_deadline)
        r1 = self.map.road_minutes(pickup_id, delivery_id)
        miss = {"opposing": 1.0, "local": 1.0}
        tod = math.fmod(self.now, DAY)
        in_pw = tod >= 8 * HOUR and tod <= 18 * HOUR and self.level == 8 and truthy(self.pricing.estimator.price_war_today)

        def consider_candidate(cand, cand_win_prob):
            if cand["id"] == current_req_id or cand_win_prob < 0.05 or len(cand["legs"]) != 1:
                return
            l2 = cand["legs"][0]
            if truthy(l2["car"]["premium"]) or truthy(l2["pickup"]["privateAddress"]) or truthy(l2["delivery"]["privateAddress"]):
                return
            nl = self.notes_by_order.get(cand["id"])
            n2 = nl[0] if nl else None
            p2 = l2["pickup"]["placeId"]
            d2 = l2["delivery"]["placeId"]
            opts = cand["options"]
            max_cand_dl = co(opts[-1].get("deadline") if opts else None, 0)
            if n2 is not None and truthy(n2.get("summerTyres")) and self.snow.overlaps(p2, d2, self.now, max_cand_dl):
                return
            cand_ready_day = day_of(max(l2["pickup"]["window"]["from"], co(n2.get("readyAt") if n2 is not None else None, 0)))
            cand_dl_day = day_of(min(max_cand_dl, co(n2.get("noteDeadline") if n2 is not None else None, INF)))
            if cand_ready_day > my_dl_day or my_ready_day > cand_dl_day:
                return
            dh12 = self.map.road_minutes(delivery_id, p2)
            dh21 = self.map.road_minutes(d2, pickup_id)
            if dh12 > 50 or dh21 > 50 or r1 + dh12 + self.map.road_minutes(p2, d2) > 540:
                return
            if not self.map.is_same_cluster30(pickup_id, p2):
                miss["opposing"] *= 1 - cand_win_prob
            elif dh12 <= 40 and dh21 <= 40:
                miss["local"] *= 1 - 0.5 * cand_win_prob

        for meta in self.unresolved_quotes.values():
            if meta["request"]["respondBy"] <= self.now or meta["request"]["id"] in self.orders:
                continue
            consider_candidate(meta["request"], meta["expectedWinProb"])
        unquoted_prior_prob = 0.12 if in_pw else 0.38
        for pending_req in self.pending_price_requests.values():
            if pending_req["respondBy"] <= self.now or pending_req["id"] in self.unresolved_quotes:
                continue
            consider_candidate(pending_req, unquoted_prior_prob)
        p_opposing = 1 - miss["opposing"]
        p_local = 1 - miss["local"]
        return min(0.85, 0.90 * p_opposing + 0.42 * (1 - p_opposing) * p_local)

    # --- Ledger & Dealer Trust Accounting ---

    def finalize_pending_revenue(self, up_to_minute) -> None:
        for order_id, info in list(self.pending_revenue_orders.items()):
            if info["at"] > up_to_minute:
                continue
            del self.pending_revenue_orders[order_id]
            on_time = order_id not in self.late_or_penalized_orders
            self.delivered_orders_total += 1
            if on_time:
                self.delivered_on_time_total += 1
                self.finalized_on_time_orders[order_id] = info["dealerId"]
            self.pricing.estimator.on_order_delivered(info["dealerId"], on_time)

    def mark_late_or_penalized(self, order_id) -> None:
        if order_id in self.late_or_penalized_orders:
            return
        self.late_or_penalized_orders.add(order_id)
        pending_rev = self.pending_revenue_orders.get(order_id)
        if pending_rev is not None:
            del self.pending_revenue_orders[order_id]
            self.delivered_orders_total += 1
            self.pricing.estimator.on_order_delivered(pending_rev["dealerId"], False)
            return
        already_on_time_dealer = self.finalized_on_time_orders.get(order_id)
        if truthy(already_on_time_dealer):
            del self.finalized_on_time_orders[order_id]
            if self.delivered_on_time_total > 0:
                self.delivered_on_time_total -= 1
            d = self.pricing.estimator.get_dealer(already_on_time_dealer)
            if self.level == 8:
                d["trust"] = jfloor(max(0, d["trust"] - 1) / 2)
            d["lateCount"] = min(6, d["lateCount"] + 1.125)

    # --- Rejoin & Event Dispatch ---

    def rejoin(self, snapshot, history) -> None:
        # async in TS, body is synchronous
        rejoin_desk_state(self, snapshot, history)

    def handle(self, event) -> None:
        self.now = max(self.now, event["at"])
        self.check_day_rollover()
        self.finalize_pending_revenue(event["at"] - 1)

        kind = event["kind"]
        if kind == "forecast":
            self.handle_forecast(event["from"], event["to"], event["placeIds"])
        elif kind == "price_request":
            self.handle_price_request(event["request"])
        elif kind == "order_won":
            self.handle_order_won(event["order"], event["at"])
        elif kind == "order_lost":
            self.handle_order_lost(event["requestId"])
        elif kind == "order_changed":
            self.handle_order_changed(event["order"])
        elif kind == "order_cancelled":
            self.handle_order_cancelled(event["orderId"], event["gigs"])
        elif kind == "gig_viewed":
            self.handle_gig_viewed(event["gigId"], event["driverId"], event["at"])
        elif kind == "gig_booked":
            self.handle_gig_booked(event["gigId"], event["driverId"], event["feeCents"], event["at"])
        elif kind == "gig_started":
            g = self.gigs.get(event["gigId"])
            if g is not None:
                g["status"] = "working"
                g["driverId"] = event["driverId"]
                g["startedAt"] = event["at"]
        elif kind == "gig_dropped" or kind == "no_show":
            self.handle_gig_dropped_or_no_show(event["gigId"], kind == "gig_dropped")
        elif kind == "driver_late":
            self.handle_driver_late(event["gigId"], event["pickupAt"])
        elif kind == "gig_expired":
            self.handle_gig_expired(event["gigId"])
        elif kind == "offer_answered":
            self.handle_offer_answered(event["gigId"], event["driverId"], event["answer"])
        elif kind == "release":
            self.handle_release_event(event["orderId"], event["leg"], event["at"])
        elif kind == "visit_failed":
            self.handle_visit_failed(event["gigId"], event["orderId"], event["leg"], event["reason"])
        elif kind == "delivered":
            self.handle_delivered(event["gigId"], event["orderId"], event["leg"], event["placeId"], event["at"])
        elif kind == "deadline_close":
            self.handle_deadline_close(event["orderId"])
        elif kind == "ledger":
            line = event["line"]
            if (line["kind"] == "late_refund" or line["kind"] == "undelivered_penalty") and truthy(line.get("orderId")):
                self.mark_late_or_penalized(line["orderId"])
            elif line["kind"] == "revenue" and truthy(line.get("orderId")):
                ord_ = self.orders.get(line["orderId"])
                req = self.requests.get(line["orderId"])
                dealer_id = co(ord_["dealerId"] if ord_ is not None else None, req["dealerId"] if req is not None else None)
                if truthy(dealer_id):
                    self.pending_revenue_orders[line["orderId"]] = {"dealerId": dealer_id, "at": event["at"]}

    def handle_forecast(self, from_, to, place_ids) -> None:
        self.snow.add_forecast(from_, to, place_ids)
        for g in list(self.gigs.values()):
            if g["status"] != "open" or g["isBundledTwoOrder"] or len(g["stops"]) == 0:
                continue
            ord_ = self.orders.get(g["stops"][0]["orderId"])
            if ord_ is None:
                continue
            legs = [s["leg"] for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == ord_["id"]]
            if len(legs) == 0:
                continue
            prev_lpa = co(self.effective_last_pickup_by_order.get(ord_["id"]), ord_["lastPickupAt"])
            notes = self.get_notes(ord_["id"])
            omit_cap = ord_["id"] in self.omit_soft_cap_orders or self.now > ord_["lastPickupAt"]
            rebuilt = build_stops_for_order(
                self.map, self.snow, ord_, legs, notes,
                co(self.retries.get(ord_["id"]), {}),
                self.now, self.ends_at, omit_cap,
            )
            self.effective_last_pickup_by_order[ord_["id"]] = rebuilt["effectiveLastPickupAt"]
            first_from = ord_["legs"][legs[0]]["pickup"]["window"]["from"]
            prev_from = _win_from(g["stops"][0], first_from)
            new_from = _win_from(rebuilt["stops"][0], first_from) if rebuilt["stops"] else first_from
            prev_to = _win_to(g["stops"][0], ord_["deadline"])
            new_to = _win_to(rebuilt["stops"][0], ord_["deadline"]) if rebuilt["stops"] else ord_["deadline"]
            if new_from > prev_from + 15 or prev_to - new_to >= 20 or prev_lpa - rebuilt["effectiveLastPickupAt"] >= 20:
                g["status"] = "withdrawn"
                self.unlink_gig(g["id"])
                self.outbox.push({"type": "withdraw", "gigId": g["id"]})
                self.dispatch_order_legs(ord_, legs, False)

    def handle_gig_viewed(self, gig_id, driver_id, at) -> None:
        self.offers.record_view(driver_id, at, gig_id)
        vg = self.gigs.get(gig_id)
        if vg is None or vg["status"] != "open" or self.now < vg["postedAt"] + 6:
            return

        gv = self.offers.gig_viewers.get(gig_id)
        rec = gv.get(driver_id) if gv is not None else None
        v_count = co(rec["count"] if rec is not None else None, 0)
        pair_key = f"{gig_id}:{driver_id}"
        is_high_yield_first_view = vg["isBundledTwoOrder"]
        if not is_high_yield_first_view and v_count == 1 and len(vg["stops"]) > 0:
            prof = self.supply.by_id.get(driver_id)
            f_ord = self.orders.get(vg["stops"][0]["orderId"])
            l_stop = vg["stops"][-1]
            l_ord = self.orders.get(l_stop["orderId"]) if l_stop is not None else None
            fl = _at(f_ord["legs"], vg["stops"][0]["leg"]) if f_ord is not None else None
            p_pl = fl["pickup"]["placeId"] if fl is not None else None
            if l_ord is not None and l_stop is not None:
                ll = _at(l_ord["legs"], l_stop["leg"])
                d_pl = ll["delivery"]["placeId"] if ll is not None else None
            else:
                d_pl = None
            if (prof is not None and p_pl and d_pl and self.map.dist_km(prof["homePlaceId"], d_pl) <= 30
                    and self.map.dist_km(prof["homePlaceId"], p_pl) > 30):
                is_high_yield_first_view = True
        if ((v_count >= 2 or (v_count == 1 and is_high_yield_first_view))
                and pair_key not in self.offers.attempted_gig_drivers
                and self.offers.open_count(gig_id) < 3):
            vg["nextOfferCheckAt"] = self.now
            self.needs_immediate_offer_pass = True

    # --- Quoting ---

    def handle_price_request(self, request) -> None:
        self.requests[request["id"]] = request
        if request["id"] not in self.notes_by_order:
            self.notes_by_order[request["id"]] = parse_dealer_note(request)
        self.record_batch_arrival(request)
        if request["respondBy"] <= self.now:
            self.pricing.estimator.get_dealer(request["dealerId"])["unquotedCount"] += 1
            return
        if request["id"] in self.quote_meta_by_req or request["id"] in self.orders:
            return
        self.pending_price_requests[request["id"]] = request

    def score_pending_request_priority(self, req, pending_list):
        leg0 = req["legs"][0]
        last_leg = req["legs"][-1]
        pickup_id = leg0["pickup"]["placeId"]
        delivery_id = last_leg["delivery"]["placeId"]
        leg_kms = [self.map.road_km(l["pickup"]["placeId"], l["delivery"]["placeId"]) for l in req["legs"]]
        ref_opt = "next_day" if any(o["kind"] == "next_day" for o in req["options"]) else req["options"][0]["kind"]
        ulp = unrounded_list_price_cents(leg_kms, ref_opt)
        dealer = self.pricing.estimator.get_dealer(req["dealerId"])
        trust_mult = 1 + 0.01 * dealer["trust"] if self.level == 8 else 1.0
        world_mult = math.exp(self.pricing.estimator.world_log_mean) if self.level >= 8 else 1.22
        gross_headroom_cents = ulp * world_mult * trust_mult - req["referenceFeeCents"] * 0.92
        dest_pool30 = self.supply.pool30(delivery_id, False, False)
        dest_bonus_cents = 950 if dest_pool30 >= 80 else (300 if dest_pool30 >= 25 else -650)

        has_mutual_or_open_rt = False
        if (len(req["legs"]) == 1 and not truthy(leg0["car"]["premium"]) and not truthy(leg0["pickup"]["privateAddress"])
                and not truthy(leg0["delivery"]["privateAddress"])):
            max_dl = req["options"][-1]["deadline"]
            if self.compute_round_trip_partner_credit(req["id"], pickup_id, delivery_id, leg0["pickup"]["window"]["from"],
                                                      max_dl, max_dl) >= 0.25:
                has_mutual_or_open_rt = True
            else:
                def other_ok(other):
                    if other["id"] == req["id"] or len(other["legs"]) != 1:
                        return False
                    ol = other["legs"][0]
                    if truthy(ol["car"]["premium"]) or truthy(ol["pickup"]["privateAddress"]) or truthy(ol["delivery"]["privateAddress"]):
                        return False
                    return (
                        (not self.map.is_same_cluster30(pickup_id, ol["pickup"]["placeId"]))
                        and self.map.road_minutes(delivery_id, ol["pickup"]["placeId"]) <= 50
                        and self.map.road_minutes(ol["delivery"]["placeId"], pickup_id) <= 50
                    )
                has_mutual_or_open_rt = any(other_ok(o) for o in pending_list)
        notes = self.get_notes(req["id"])
        needs_charging = any(self.map.needs_charging(l["car"], l["pickup"]["placeId"], l["delivery"]["placeId"]) for l in req["legs"])
        friction_penalty_cents = (
            (700 if any(truthy(l["car"]["premium"]) for l in req["legs"]) else 0)
            + (800 if any(truthy(l["pickup"]["privateAddress"]) or truthy(l["delivery"]["privateAddress"]) for l in req["legs"]) else 0)
            + (600 if len(req["legs"]) > 1 else 0)
            + (450 if needs_charging else 0)
            + (250 if (notes and truthy(notes[0].get("manualGearbox"))) else 0)
        )
        return gross_headroom_cents + dest_bonus_cents + (1100 if has_mutual_or_open_rt else 0) - friction_penalty_cents

    def flush_pending_price_requests(self) -> None:
        self.prune_unresolved_quotes()
        if len(self.pending_price_requests) == 0:
            return

        valid_list = []
        for req in list(self.pending_price_requests.values()):
            if req["respondBy"] <= self.now:
                del self.pending_price_requests[req["id"]]
                self.pricing.estimator.get_dealer(req["dealerId"])["unquotedCount"] += 1
                continue
            valid_list.append(req)
        if len(valid_list) == 0:
            return

        priorities = {}
        for req in valid_list:
            priorities[req["id"]] = self.score_pending_request_priority(req, valid_list)

        def cmp(a, b):
            diff = co(priorities.get(b["id"]), 0) - co(priorities.get(a["id"]), 0)
            if abs(diff) > 1e-6:
                return diff
            if a["arrivedAt"] != b["arrivedAt"]:
                return a["arrivedAt"] - b["arrivedAt"]
            return _cmp_str(a["id"], b["id"])

        valid_list.sort(key=functools.cmp_to_key(cmp))

        for request in valid_list:
            self.pending_price_requests.pop(request["id"], None)
            notes = self.get_notes(request["id"])
            pending_exp_wins = self.total_unresolved_expected_wins()

            batch_info = None
            if truthy(request.get("batchId")):
                st = self.batches.get(request["batchId"])
                batch_unres = 0
                for u in self.unresolved_quotes.values():
                    if (u["request"].get("batchId") == request["batchId"] and u["request"]["respondBy"] > self.now
                            and u["request"]["id"] not in self.orders):
                        batch_unres += u["expectedWinProb"]
                batch_info = {
                    "batchId": request["batchId"],
                    "seenCount": len(st["seenIds"]) if st is not None else 1,
                    "wonCount": len(st["wonIds"]) if st is not None else 0,
                    "unresolvedExpectedWins": batch_unres,
                }

            meta = self.pricing.quote_request(request, notes, {
                "now": self.now,
                "startMinute": self.start_minute,
                "wonOrdersTotal": max(0, self.won_orders_total - self.count_bundled_driver_savings()) + pending_exp_wins,
                "deliveredOrdersTotal": self.delivered_orders_total,
                "deliveredOnTimeTotal": self.delivered_on_time_total,
                "overdueUndeliveredCount": self.count_overdue_undelivered_orders(),
                "unbookedOrdersCount": self.count_unbooked_orders() + pending_exp_wins,
                "openPickupsInCluster30": lambda p: self.count_open_pickups_in_cluster30(p),
                "pendingPickupsInCluster30": lambda p: self.count_pending_pickups_in_cluster30(p),
                "activeOrdersOnDeadlineDay": lambda dl_day: self.count_active_orders_on_deadline_day(dl_day),
                "inFlightDealerOrders": lambda d_id: self.count_in_flight_dealer_orders(d_id),
                "hasArrivingDriverSynergy": lambda p, d, e_min, l_min: self.has_arriving_driver_synergy(p, d, e_min, l_min),
                "roundTripPartnerCredit": lambda p, d, e_pick, l_pick, eff_dl, _rid=request["id"]:
                    self.compute_round_trip_partner_credit(_rid, p, d, e_pick, l_pick, eff_dl),
                "batchInfo": batch_info,
                "fluActiveToday": self.flu_active_today,
            })

            if not meta:
                continue
            self.quote_meta_by_req[request["id"]] = meta
            if meta["expectedWinProb"] > 0:
                self.unresolved_quotes[request["id"]] = meta
            self.outbox.push({
                "type": "quote",
                "requestId": request["id"],
                "prices": meta["prices"],
            })

    # --- Order & Gig Event Handlers ---

    def handle_order_won(self, order, at) -> None:
        if order["id"] not in self.requests or order["id"] in self.orders:
            return
        self.orders[order["id"]] = order
        self.order_won_at[order["id"]] = at
        self.won_orders_total += 1
        self.unresolved_quotes.pop(order["id"], None)
        self.pending_price_requests.pop(order["id"], None)
        req = self.requests.get(order["id"])
        if req is not None and truthy(req.get("batchId")):
            b = self.batches.get(req["batchId"])
            if b is not None:
                b["wonIds"].add(order["id"])

        meta = self.quote_meta_by_req.get(order["id"])
        if meta is not None:
            self.pricing.estimator.on_quote_resolved(meta, order["option"])

        self.dispatch_order_legs(order, undelivered_legs(order), True)

    def handle_order_lost(self, request_id) -> None:
        self.unresolved_quotes.pop(request_id, None)
        self.pending_price_requests.pop(request_id, None)
        req = self.requests.get(request_id)
        if req is not None and truthy(req.get("batchId")):
            b = self.batches.get(req["batchId"])
            if b is not None:
                b["lostIds"].add(request_id)
        meta = self.quote_meta_by_req.get(request_id)
        if meta is not None:
            self.pricing.estimator.on_quote_resolved(meta, None)

    def handle_order_changed(self, order) -> None:
        if order["id"] not in self.orders:
            return
        prev = self.orders[order["id"]]
        self.orders[order["id"]] = order
        self.omit_soft_cap_orders.discard(order["id"])
        self.strip_windows_orders.discard(order["id"])
        self.post_backoff_until.pop(order["id"], None)
        self.pairing_buffer_until.pop(order["id"], None)

        notes = self.get_notes(order["id"])
        for l in range(len(order["legs"])):
            pl = _at(prev["legs"], l)
            if pl is None or order["legs"][l]["pickup"]["window"]["from"] != pl["pickup"]["window"]["from"]:
                r = self.get_leg_retry(order["id"], l)
                if r["pickupFrom"] > 0:
                    self.set_leg_retry(order["id"], l, {**r, "pickupFrom": 0})
        reconcile_notes_after_order_change(prev, order, notes)

        undel_all = undelivered_legs(order)
        if len(undel_all) > 0:
            b = build_stops_for_order(
                self.map, self.snow, order, undel_all, notes,
                co(self.retries.get(order["id"]), {}),
                self.now, self.ends_at,
            )
            self.effective_last_pickup_by_order[order["id"]] = b["effectiveLastPickupAt"]
            if b["effectiveLastPickupAt"] - self.now > 300:
                self.urgent.discard(order["id"])
                self.max_reached_fee_by_order.pop(order["id"], None)

        displaced_partners = self.outbox.remove_posts_for_order(order["id"])
        open_gigs_to_withdraw = {}
        booked_gigs_to_release = {}
        m = self.leg_gigs.get(order["id"])
        if m is not None:
            for leg_idx, gid in m.items():
                g = self.gigs.get(gid)
                if g is None:
                    continue
                if g["status"] == "open":
                    open_gigs_to_withdraw[gid] = True
                elif g["status"] == "booked":
                    leg_obj = _at(order["legs"], leg_idx)
                    p_stop = next((s for s in g["stops"] if s["kind"] == "pickup" and s["orderId"] == order["id"]
                                   and s["leg"] == leg_idx), None)
                    needs_new_charge = bool(
                        leg_obj is not None and p_stop is not None and not truthy(p_stop.get("withCharging"))
                        and self.map.needs_charging(leg_obj["car"], leg_obj["pickup"]["placeId"], leg_obj["delivery"]["placeId"])
                    )
                    req = self.requests.get(order["id"])
                    new_scale = self.changed_km_scale_for_order(order, req, [leg_idx]) if req is not None else 1.0
                    new_ref = (req["referenceFeeCents"] / len(order["legs"])) * new_scale if req is not None else g["feeCents"]
                    eff_lpa = co(self.effective_last_pickup_by_order.get(order["id"]), order["lastPickupAt"])
                    q30 = (self.supply.pool30(leg_obj["pickup"]["placeId"], g["audience"]["experienced"],
                                              g["audience"]["manualLicence"]) if leg_obj is not None else 0)
                    drastic_shrink_worth_release = (
                        (not g["isBundledTwoOrder"])
                        and len(order["legs"]) == 1
                        and new_scale < 0.62
                        and eff_lpa - self.now >= 480
                        and q30 >= 25
                        and g["feeCents"] - jround(new_ref * 0.95) >= 3500
                    )
                    if needs_new_charge or drastic_shrink_worth_release:
                        booked_gigs_to_release[gid] = True

        partner_orders = {}
        for s in displaced_partners:
            partner_orders[s["orderId"]] = True

        for gid in open_gigs_to_withdraw:
            g = self.gigs[gid]
            for o in self.distinct_live_orders_of_stops(g["stops"]):
                if o["id"] != order["id"]:
                    partner_orders[o["id"]] = True
            g["status"] = "withdrawn"
            self.unlink_gig(gid)
            self.outbox.push({"type": "withdraw", "gigId": gid})

        for gid in booked_gigs_to_release:
            g = self.gigs[gid]
            for o in self.distinct_live_orders_of_stops(g["stops"]):
                if o["id"] != order["id"]:
                    partner_orders[o["id"]] = True
            g["status"] = "withdrawn"
            self.unlink_gig(gid)
            self.outbox.push({"type": "release", "gigId": gid})

        missing_self = self.unscheduled_legs_for_order(order)
        if len(missing_self) > 0:
            self.dispatch_order_legs(order, missing_self, False)
        for pid in partner_orders:
            po = self.orders.get(pid)
            if po is None:
                continue
            missing_partner = self.unscheduled_legs_for_order(po)
            if len(missing_partner) > 0:
                self.dispatch_order_legs(po, missing_partner, False)

    def handle_order_cancelled(self, order_id, cancelled_gigs) -> None:
        if order_id in self.orders:
            del self.orders[order_id]
            if self.won_orders_total > 0:
                self.won_orders_total -= 1
        self.leg_gigs.pop(order_id, None)
        self.urgent.discard(order_id)
        self.pairing_buffer_until.pop(order_id, None)
        c_req = self.requests.get(order_id)
        if c_req is not None and truthy(c_req.get("batchId")):
            b = self.batches.get(c_req["batchId"])
            if b is not None:
                b["wonIds"].discard(order_id)

        displaced = self.outbox.remove_posts_for_order(order_id)
        to_redispatch = {}
        for s in displaced:
            to_redispatch[s["orderId"]] = True

        for cg in cancelled_gigs:
            g = self.gigs.get(cg["gigId"])
            if g is None:
                continue
            if cg["outcome"] == "withdrawn" or cg["outcome"] == "released":
                for o in self.distinct_live_orders_of_stops(g["stops"]):
                    if o["id"] != order_id:
                        to_redispatch[o["id"]] = True
                g["status"] = "withdrawn"
                self.unlink_gig(cg["gigId"])
            else:
                g["stops"] = [s for s in g["stops"] if s["orderId"] != order_id]
                g["isBundledTwoOrder"] = has_multiple_orders_in_stops(g["stops"])

        for pid in to_redispatch:
            po = self.orders.get(pid)
            if po is None:
                continue
            missing = self.unscheduled_legs_for_order(po, True)
            if len(missing) > 0:
                self.dispatch_order_legs(po, missing, False)
