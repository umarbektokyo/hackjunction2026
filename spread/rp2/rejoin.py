"""Rebuild the desk's state when joining a world in progress (rejoin.ts). Python port of RoutePulse v21e."""
from __future__ import annotations

from .bundling import compute_two_order_bundle_split_at
from .desk_b import sadd, sdel
from .js import INF, co, isfinite
from .notes import parse_dealer_note, reconcile_notes_after_order_change
from .planner import build_stops_for_order
from .rptime import DAY, HOUR, day_of


def rejoin_desk_state(desk, snapshot, history) -> None:
    desk.now = snapshot["now"]
    desk.ends_at = snapshot["endsAt"]

    open_req_ids = dict.fromkeys(r["id"] for r in snapshot["openRequests"])
    first_our_activity_at = INF
    for o in snapshot["orders"]:
        legs = o["legs"]
        first_our_activity_at = min(first_our_activity_at, legs[0]["pickup"]["window"]["from"] if len(legs) > 0 else INF)
    for g in snapshot["gigs"]:
        first_our_activity_at = min(first_our_activity_at, g["postedAt"])
    for ev in history:
        if ev["kind"] == "order_won" or ev["kind"] == "gig_booked" or ev["kind"] == "offer_answered":
            first_our_activity_at = min(first_our_activity_at, ev["at"])
    had_prior_participation = isfinite(first_our_activity_at)
    desk.start_minute = (min(first_our_activity_at, history[0]["at"] if len(history) > 0 else snapshot["now"])
                         if had_prior_participation else snapshot["now"])

    gig_driver_by_id = {}
    for g in snapshot["gigs"]:
        if g.get("driverId"):
            gig_driver_by_id[g["id"]] = g["driverId"]
    hist_orders = {}

    for ev in history:
        desk.now = max(desk.now, ev["at"])
        desk.check_day_rollover()
        desk.finalize_pending_revenue(ev["at"] - 1)

        kind = ev["kind"]
        if kind == "price_request":
            request = ev["request"]
            desk.requests[request["id"]] = request
            notes = parse_dealer_note(request)
            desk.notes_by_order[request["id"]] = notes
            desk.record_batch_arrival(request)
            if request["id"] not in open_req_ids and had_prior_participation and request["respondBy"] >= first_our_activity_at:
                meta = desk.pricing.quote_request(request, notes, {
                    "now": ev["at"],
                    "startMinute": desk.start_minute,
                    "wonOrdersTotal": desk.won_orders_total,
                    "deliveredOrdersTotal": desk.delivered_orders_total,
                    "deliveredOnTimeTotal": desk.delivered_on_time_total,
                    "unbookedOrdersCount": 10,
                    "openPickupsInCluster30": lambda *a: 0,
                    "activeOrdersOnDeadlineDay": lambda *a: 35,
                    "hasArrivingDriverSynergy": lambda *a: False,
                    "roundTripPartnerCredit": lambda *a: 0,
                    "fluActiveToday": desk.flu_active_today,
                })
                if meta:
                    desk.quote_meta_by_req[request["id"]] = meta
            elif request["id"] not in open_req_ids:
                desk.pricing.estimator.get_dealer(request["dealerId"])["unquotedCount"] += 1
        elif kind == "forecast":
            desk.snow.add_forecast(ev["from"], ev["to"], ev["placeIds"])
        elif kind == "deadline_close":
            sadd(desk.urgent, ev["orderId"])
        elif kind == "order_won":
            desk.won_orders_total += 1
            desk.order_won_at[ev["order"]["id"]] = ev["at"]
            hist_orders[ev["order"]["id"]] = ev["order"]
            req = desk.requests.get(ev["order"]["id"])
            if req and req.get("batchId"):
                b = desk.batches.get(req["batchId"])
                if b:
                    sadd(b["wonIds"], ev["order"]["id"])
            meta = desk.quote_meta_by_req.get(ev["order"]["id"])
            if meta:
                desk.pricing.estimator.on_quote_resolved(meta, ev["order"]["option"])
        elif kind == "order_lost":
            req = desk.requests.get(ev["requestId"])
            if req and req.get("batchId"):
                b = desk.batches.get(req["batchId"])
                if b:
                    sadd(b["lostIds"], ev["requestId"])
            meta = desk.quote_meta_by_req.get(ev["requestId"])
            if meta:
                desk.pricing.estimator.on_quote_resolved(meta, None)
        elif kind == "order_cancelled":
            if desk.won_orders_total > 0:
                desk.won_orders_total -= 1
            hist_orders.pop(ev["orderId"], None)
            req = desk.requests.get(ev["orderId"])
            if req and req.get("batchId"):
                b = desk.batches.get(req["batchId"])
                if b:
                    sdel(b["wonIds"], ev["orderId"])
        elif kind == "order_changed":
            prev = hist_orders.get(ev["order"]["id"])
            hist_orders[ev["order"]["id"]] = ev["order"]
            reconcile_notes_after_order_change(prev, ev["order"], desk.get_notes(ev["order"]["id"]))
        elif kind == "gig_viewed":
            desk.offers.record_view(ev["driverId"], ev["at"], ev["gigId"])
        elif kind == "gig_booked":
            gig_driver_by_id[ev["gigId"]] = ev["driverId"]
            desk.offers.record_booked(ev["driverId"], ev["gigId"], ev["at"])
        elif kind == "gig_started":
            gig_driver_by_id[ev["gigId"]] = ev["driverId"]
        elif kind == "delivered":
            desk.offers.record_delivered(gig_driver_by_id.get(ev["gigId"]), ev["placeId"], ev["at"])
        elif kind == "offer_answered":
            if ev["answer"] == "accepted":
                gig_driver_by_id[ev["gigId"]] = ev["driverId"]
            day_key = f"{day_of(max(0, ev['at'] - 1))}:{ev['driverId']}"
            desk.offers.offers_sent_by_day[day_key] = co(desk.offers.offers_sent_by_day.get(day_key), 0) + 1
            sadd(desk.offers.attempted_gig_drivers, f"{ev['gigId']}:{ev['driverId']}")
        elif kind == "gig_dropped":
            if not desk.flu_used_this_week and day_of(ev["at"]) < 5 and ev["at"] % DAY < 90:
                desk.record_midnight_flu_drop()
        elif kind == "release":
            notes = desk.get_notes(ev["orderId"])
            if 0 <= ev["leg"] < len(notes) and notes[ev["leg"]]:
                notes[ev["leg"]]["releasedAt"] = ev["at"]
            cur = desk.get_leg_retry(ev["orderId"], ev["leg"])
            desk.set_leg_retry(ev["orderId"], ev["leg"], {**cur, "pickupFrom": 0})
        elif kind == "visit_failed":
            ord_ = next((o for o in snapshot["orders"] if o["id"] == ev["orderId"]), None)
            desk.apply_visit_failed_retry(ev["orderId"], ev["leg"], ev["reason"], ev["at"], ord_)
        elif kind == "ledger":
            line = ev["line"]
            if (line["kind"] == "late_refund" or line["kind"] == "undelivered_penalty") and line.get("orderId"):
                desk.mark_late_or_penalized(line["orderId"])
            elif line["kind"] == "revenue" and line.get("orderId"):
                req = desk.requests.get(line["orderId"])
                if req:
                    desk.pending_revenue_orders[line["orderId"]] = {"dealerId": req["dealerId"], "at": ev["at"]}
    desk.now = snapshot["now"]
    desk.finalize_pending_revenue(snapshot["now"] - 1)

    for order in snapshot["orders"]:
        if order.get("status") == "cancelled":
            continue
        desk.orders[order["id"]] = order
        if order["id"] not in desk.order_won_at:
            desk.order_won_at[order["id"]] = snapshot["now"]
        undel = []
        for i in range(len(order["legs"])):
            if order["deliveredAt"][i] is None:
                undel.append(i)
        if len(undel) > 0:
            b = build_stops_for_order(
                desk.map,
                desk.snow,
                order,
                undel,
                desk.get_notes(order["id"]),
                co(desk.retries.get(order["id"]), {}),
                snapshot["now"],
                snapshot["endsAt"],
                snapshot["now"] > order["lastPickupAt"],
            )
            desk.effective_last_pickup_by_order[order["id"]] = b["effectiveLastPickupAt"]

    for gig in snapshot["gigs"]:
        distinct_orders = list(dict.fromkeys(s["orderId"] for s in gig["stops"]))
        is_bundle = len(distinct_orders) > 1
        split_at = gig["postedAt"] + 125
        if is_bundle:
            vals = []
            for oid in distinct_orders:
                o = desk.orders.get(oid)
                vals.append(co(desk.effective_last_pickup_by_order.get(oid), o["lastPickupAt"]) if o else INF)
            min_lpa = min(vals)
            split_at = compute_two_order_bundle_split_at(gig["postedAt"], min_lpa)
        p0_ord = desk.orders.get(gig["stops"][0]["orderId"]) if len(gig["stops"]) > 0 else None
        any_urgent = any(s["orderId"] in desk.urgent for s in gig["stops"])
        state = {
            "id": gig["id"],
            "stops": gig["stops"],
            "audience": gig["audience"],
            "schedule": gig["schedule"],
            "status": gig["status"],
            "postedAt": gig["postedAt"],
            "bookedAt": gig["postedAt"] if (gig["status"] == "booked" or gig["status"] == "working") else None,
            "startedAt": max(gig["postedAt"], snapshot["now"] - 30) if gig["status"] == "working" else None,
            "feeCents": gig["feeCents"],
            "driverId": gig.get("driverId"),
            "isBundledTwoOrder": is_bundle,
            "splitAt": split_at,
            "urgentEscalated": any_urgent,
            "urgentEscalatedAt": snapshot["now"] if any_urgent else None,
            "pastDeadlineEscalated": bool(p0_ord and gig["postedAt"] > p0_ord["deadline"]),
            "endWorldRescueEscalated": bool(p0_ord and gig["postedAt"] > p0_ord["deadline"]
                                            and snapshot["endsAt"] - gig["postedAt"] <= 42 * HOUR),
            "zombieCleared": (gig["postedAt"] > p0_ord["lastPickupAt"]) if p0_ord else False,
            "offerWave": 0,
            "nextOfferCheckAt": snapshot["now"] + 12,
        }
        if gig["status"] == "open" or gig["status"] == "booked" or gig["status"] == "working":
            desk.link_gig(state)
        else:
            desk.gigs[gig["id"]] = state

    for order in list(desk.orders.values()):
        missing = desk.unscheduled_legs_for_order(order)
        if len(missing) > 0:
            desk.dispatch_order_legs(order, missing, False)

    for req in snapshot["openRequests"]:
        if req["respondBy"] > snapshot["now"]:
            desk.handle_price_request(req)
    desk.flush_pending_price_requests()
