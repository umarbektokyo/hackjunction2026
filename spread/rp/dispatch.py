"""Fee schedules, 2-3 car bundles and direct offers. Python port of source-exp/RoutePulse typescript/dispatch.ts."""
from __future__ import annotations

import math
import re

from .planner import CHARGING_MINUTES, DAY, HOUR, INF, PLATES_MINUTES, co, isfinite, jceil, jfloor, jround, visit_at


def clamp_out_of_night(t, stagger=0):
    day = jfloor(t / DAY)
    tod = t % DAY
    if tod >= 22 * HOUR + 45:
        return (day + 1) * DAY + 7 * HOUR + 5 + stagger * 25
    if tod < 7 * HOUR + 5:
        return day * DAY + 7 * HOUR + 5 + stagger * 25
    return t


def normalize_steps(steps, now, max_fee=INF, min_first=1):
    cap = max(1, jround(max_fee))
    floor0 = min(cap, max(1, jround(min_first)))
    mapped = [{"at": max(now, jround(s["at"])), "feeCents": min(cap, max(floor0 if i == 0 else 1, jround(s["feeCents"])))}
              for i, s in enumerate(steps)]
    mapped.sort(key=lambda s: s["at"])
    out = []
    for st in mapped:
        prev = out[-1] if out else None
        mono = max(prev["feeCents"], st["feeCents"]) if prev else max(floor0, st["feeCents"])
        if prev and prev["at"] == st["at"]:
            prev["feeCents"] = mono
        else:
            out.append({"at": st["at"], "feeCents": mono})
    return out[:48]


def build_single_gig_schedule(m, supply, c):
    q30 = supply.pool30(c["pickupPlaceId"], c["audience"]["experienced"], c["audience"]["manualLicence"])
    d_pool30 = supply.pool30(c["deliveryPlaceId"], False, False)
    same30 = m.is_same_cluster30(c["pickupPlaceId"], c["deliveryPlaceId"])
    long_or_dead = c["routeKm"] > 250 or (d_pool30 <= 14 and not same30)
    now = c["now"]
    pick_day = jfloor(max(now, c["earliestPickupAt"]) / DAY)
    pick_wd = pick_day % 7
    pick_tod = max(now, c["earliestPickupAt"]) % DAY
    evening_or_sat = pick_wd == 5 or pick_tod >= 17 * HOUR
    extras = (c["hasPrivatePickup"] or c["hasPrivateDelivery"] or c["isTradeInTwoLegs"] or c["audience"]["experienced"]
              or c["withCharging"] or c["withPlates"])
    m0 = 0.85
    if d_pool30 >= 95 and q30 >= 40 and not extras and not c["snowOverlap"] and not c["fluActive"] and c["routeKm"] <= 220:
        m0 -= 0.04
    if d_pool30 <= 5 and not same30:
        m0 += 0.08
    elif d_pool30 <= 14 and not same30:
        m0 += 0.05
    if q30 == 0:
        m0 += 0.12
    elif q30 <= 5:
        m0 += 0.07
    elif q30 <= 15:
        m0 += 0.03
    if c["routeKm"] > 260:
        m0 += 0.07
    if c["routeKm"] > 400:
        m0 += 0.06
    if c["hasPrivatePickup"] and not c["isTradeInTwoLegs"]:
        m0 += 0.14
    if c["hasPrivateDelivery"] and not c["isTradeInTwoLegs"]:
        m0 += 0.16
    if c["isTradeInTwoLegs"]:
        m0 += 0.14
    if c["audience"]["experienced"]:
        m0 += 0.18
    if c["withCharging"]:
        m0 += 0.08
    if c["withPlates"] or c["audience"]["manualLicence"]:
        m0 += 0.04
    if evening_or_sat:
        m0 += 0.06
    if c["snowOverlap"]:
        m0 += 0.12
    if c["fluActive"]:
        m0 += 0.10
    m0 = max(0.80, min(1.45 if (extras or c["snowOverlap"]) else 1.32, m0))
    max_econ = max(c["baseRefFeeCents"], jround(c["orderPriceCents"] * 2.65)) if c["orderPriceCents"] > 0 else INF
    ref = c["baseRefFeeCents"]

    if c["level"] == 1:
        flat = 2.20 if c["isPastDeadline"] else max(1.48, m0 + 0.35) if c["urgent"] else m0
        fee = min(max_econ, max(c["minFloorFeeCents"], jround(ref * flat)))
        return [{"at": now, "feeCents": max(1, fee)}]

    if c["isPastDeadline"] and c["endsAt"] - now <= 42 * HOUR:
        mults = [max(m0 + 0.45, 1.58), max(m0 + 0.75, 1.88), max(m0 + 1.05, 2.22), max(m0 + 1.40, 2.58), max(m0 + 1.75, 2.95)]
        return normalize_steps([{"at": now if k == 0 else clamp_out_of_night(now + k * 35, k), "feeCents": jround(ref * x)}
                                for k, x in enumerate(mults)], now, max_econ, c["minFloorFeeCents"])

    if (c["isPastDeadline"] or now > c["rawLastPickupAt"]) and not c["hasPrivateDelivery"] and c["endsAt"] - now > 42 * HOUR:
        mults = [max(m0 + 0.10, 1.05), max(m0 + 0.24, 1.20), max(m0 + 0.40, 1.38), max(m0 + 0.60, 1.60), max(m0 + 0.82, 1.85)]
        return normalize_steps([{"at": now if k == 0 else clamp_out_of_night(now + k * 70, k), "feeCents": jround(ref * x)}
                                for k, x in enumerate(mults)], now, max_econ, 1)

    slack = c["effectiveLastPickupAt"] - now
    max_urgent = 2.55 if c["highTrustDealer"] else 2.40
    if c["urgent"] or slack <= 210:
        mults = [max(m0 + 0.30, 1.38), max(m0 + 0.52, 1.60), max(m0 + 0.76, 1.84), max(m0 + 1.02, 2.12), max(m0 + 1.26, max_urgent)]
        return normalize_steps([{"at": now if k == 0 else clamp_out_of_night(now + k * 25, k), "feeCents": jround(ref * x)}
                                for k, x in enumerate(mults)], now, max_econ, c["minFloorFeeCents"])

    lpa = c["effectiveLastPickupAt"]
    lpa_day_start = jfloor(lpa / DAY) * DAY
    post_day_start = jfloor(now / DAY) * DAY
    crosses_night = jfloor(lpa / DAY) > jfloor(now / DAY)
    ramp = [{"at": now, "mult": m0}]
    if crosses_night and c["routeKm"] > 400:
        eve = max(now + 60, post_day_start + 19 * HOUR + 15)
        if eve <= post_day_start + 21 * HOUR + 45 and eve < lpa - 300:
            ramp.append({"at": eve, "mult": max(m0 + 0.08, 1.04)})
    if jfloor(lpa / DAY) - jfloor(now / DAY) >= 2:
        mid = max(now + 120, post_day_start + DAY + 10 * HOUR)
        if mid < lpa_day_start:
            ramp.append({"at": mid, "mult": min(0.98, m0 + 0.06)})
    if crosses_night and long_or_dead:
        wave = max(now + 90, lpa_day_start + 7 * HOUR + 35)
        if wave < lpa - 240:
            ramp.append({"at": wave, "mult": max(m0 + 0.12, 1.08)})
    min_ramp_start = max(c["earliestPickupAt"] - 180,
                         max(now + 120, lpa_day_start + (7 * HOUR + 55 if long_or_dead else 8 * HOUR + 45)) if crosses_night else now + 75)
    anchors = [(360, 0.11, 0.98), (265, 0.23, 1.12), (185, 0.39, 1.30), (115, 0.60, 1.56), (60, 0.88, 1.88)]
    span_end = lpa - 45
    if min_ramp_start > lpa - 360 and span_end > min_ramp_start + 25:
        for idx, (_, add, fl) in enumerate(anchors):
            frac = idx / (len(anchors) - 1)
            raw_t = jround(min_ramp_start + frac * (span_end - min_ramp_start))
            t = clamp_out_of_night(raw_t, idx)
            if t < lpa - 15:
                ramp.append({"at": t, "mult": min(max_urgent, max(m0 + add, fl))})
    else:
        for idx, (before, add, fl) in enumerate(anchors):
            t = clamp_out_of_night(max(min_ramp_start, lpa - before), idx)
            if t < lpa - 15:
                ramp.append({"at": t, "mult": min(max_urgent, max(m0 + add, fl))})
    return normalize_steps([{"at": r["at"], "feeCents": jround(ref * r["mult"])} for r in ramp], now, max_econ, c["minFloorFeeCents"])


def _effdl(order, note, dstop):
    w = dstop.get("window")
    return min(order["deadline"], co(note and note["noteDeadline"], INF), w["to"] if w else INF)


def evaluate_ordered_bundle(m, snow, supply, a, b, now, flu):
    if a["order"]["id"] == b["order"]["id"]:
        return None
    if len(a["order"]["legs"]) != 1 or len(b["order"]["legs"]) != 1:
        return None
    leg1, leg2 = a["order"]["legs"][0], b["order"]["legs"][0]
    n1 = a["notes"][0] if a["notes"] else None
    n2 = b["notes"][0] if b["notes"] else None
    if leg1["pickup"]["privateAddress"] or leg1["delivery"]["privateAddress"]:
        return None
    if leg2["pickup"]["privateAddress"] or leg2["delivery"]["privateAddress"]:
        return None
    if leg1["car"]["premium"] or leg2["car"]["premium"]:
        return None
    if co(n1 and n1["releasedAt"], 0) > now or co(n2 and n2["releasedAt"], 0) > now:
        return None
    P1, D1, P2, D2 = leg1["pickup"]["placeId"], leg1["delivery"]["placeId"], leg2["pickup"]["placeId"], leg2["delivery"]["placeId"]
    if n1 and n1["summerTyres"] and snow.overlaps(P1, D1, now, a["order"]["deadline"]):
        return None
    if n2 and n2["summerTyres"] and snow.overlaps(P2, D2, now, b["order"]["deadline"]):
        return None
    r1, dh, r2, ret = m.road_minutes(P1, D1), m.road_minutes(D1, P2), m.road_minutes(P2, D2), m.road_minutes(D2, P1)
    total = r1 + dh + r2
    if dh > 50 or total > 675:
        return None
    manual = bool(a["built"]["audience"]["manualLicence"] or b["built"]["audience"]["manualLicence"])
    pool_p1 = supply.pool30(P1, False, manual)
    pool_d2 = supply.pool30(D2, False, False)
    if manual and pool_p1 < 30:
        return None
    if pool_p1 < 6 and supply.pool65(P1, False, manual) < 20:
        return None
    if dh <= 45 and ret <= 50:
        tier = 1
    elif dh <= 50 and ret <= 135 and (ret <= 95 or pool_d2 >= 18):
        tier = 2
    else:
        return None
    min_last = min(a["built"]["effectiveLastPickupAt"], b["built"]["effectiveLastPickupAt"])
    if min_last - now < 260:
        return None
    p1s, d1s = a["built"]["stops"][0], a["built"]["stops"][1]
    p2s, d2s = b["built"]["stops"][0], b["built"]["stops"][1]
    hP1 = co(n1 and n1["pickupHours"], leg1["pickup"].get("hours"))
    hD1 = co(n1 and n1["deliveryHours"], leg1["delivery"].get("hours"))
    hP2 = co(n2 and n2["pickupHours"], leg2["pickup"].get("hours"))
    hD2 = co(n2 and n2["deliveryHours"], leg2["delivery"].get("hours"))
    effdl1 = _effdl(a["order"], n1, d1s)
    effdl2 = _effdl(b["order"], n2, d2s)
    p1_from = p1s["window"]["from"] if p1s.get("window") else leg1["pickup"]["window"]["from"]
    p1_to = min(effdl1, p1s["window"]["to"] if p1s.get("window") else a["order"]["deadline"])
    p2_from = p2s["window"]["from"] if p2s.get("window") else leg2["pickup"]["window"]["from"]
    p2_to = min(effdl2, p2s["window"]["to"] if p2s.get("window") else b["order"]["deadline"])
    extra1 = (PLATES_MINUTES if p1s.get("withPlates") else 0) + (CHARGING_MINUTES if p1s.get("withCharging") else 0)
    extra2 = (PLATES_MINUTES if p2s.get("withPlates") else 0) + (CHARGING_MINUTES if p2s.get("withCharging") else 0)
    snow1 = snow.overlaps(P1, D1, now, effdl1)
    snow2 = snow.overlaps(P2, D2, now, effdl2)
    drive1 = jceil(r1 * (1.32 if snow1 else 1.04))
    drive_dh = jceil(dh * (1.25 if (snow1 or snow2) else 1.02))
    drive2 = jceil(r2 * (1.32 if snow2 else 1.04))
    day0 = jfloor(now / DAY) * DAY
    feasible = False
    for start in (now + 60, day0 + DAY + 7 * HOUR + 15, day0 + 2 * DAY + 7 * HOUR + 15):
        if start > min_last - 120:
            break
        tP1 = visit_at(max(start, p1_from), p1_to, hP1, 15)
        if not isfinite(tP1):
            continue
        tD1 = visit_at(max(tP1 + 15 + extra1 + drive1, leg1["delivery"]["window"]["from"]), effdl1, hD1, 15)
        if not isfinite(tD1):
            continue
        fin1 = tD1 + 15
        arr_p2 = fin1 + drive_dh
        tP2 = visit_at(max(arr_p2, p2_from), p2_to, hP2, 15)
        if not isfinite(tP2) or tP2 - arr_p2 > 90:
            continue
        tD2 = visit_at(max(tP2 + 15 + extra2 + drive2, leg2["delivery"]["window"]["from"]), effdl2, hD2, 15)
        if not isfinite(tD2):
            continue
        fin2 = tD2 + 15
        if jfloor(tP1 / DAY) != jfloor(fin2 / DAY):
            continue
        if effdl1 - fin1 < 240 or effdl2 - fin2 < 240:
            continue
        feasible = True
        break
    if not feasible:
        return None
    ref_sum = a["request"]["referenceFeeCents"] + b["request"]["referenceFeeCents"]
    ref_max = max(a["request"]["referenceFeeCents"], b["request"]["referenceFeeCents"])
    mkt = 1.0 + (0.10 if (snow1 or snow2) else 0) + (0.08 if flu else 0)
    coeffs = [0.58, 0.66, 0.75, 0.85] if tier == 1 else [0.66, 0.74, 0.83, 0.93]
    sched = normalize_steps([{"at": now if k == 0 else clamp_out_of_night(now + k * 30, k),
                              "feeCents": jround(max(cf * ref_sum, (0.90 + 0.08 * k) * ref_max) * mkt)} for k, cf in enumerate(coeffs)], now)
    crosses = jfloor(min_last / DAY) > jfloor(now / DAY) and min_last - now >= 600
    lpa_day_start = jfloor(min_last / DAY) * DAY
    split_at = min(min_last - 240, max(now + 150, lpa_day_start + 9 * HOUR + 15)) if crosses else min(now + 125, min_last - 210)
    if split_at <= now + 35:
        return None
    savings = ref_sum - sched[0]["feeCents"]
    hub = min(600, pool_p1 * 2) - dh * 12 - ret * 6
    return {"plan": {"firstOrderId": a["order"]["id"], "secondOrderId": b["order"]["id"],
                     "stops": [*a["built"]["stops"], *b["built"]["stops"]], "audience": {"experienced": False, "manualLicence": manual},
                     "schedule": sched, "tier": tier, "splitAt": split_at}, "score": savings + hub}


def find_best_two_order_bundle(m, snow, supply, target, candidates, now, level, flu):
    if level < 3:
        return None
    best = None
    for cand in candidates:
        if cand["order"]["id"] == target["order"]["id"]:
            continue
        ab = evaluate_ordered_bundle(m, snow, supply, target, cand, now, flu)
        ba = evaluate_ordered_bundle(m, snow, supply, cand, target, now, flu)
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


def try_extend_two_to_three(m, snow, supply, a, b, c, now, flu):
    if flu or supply.total_drivers < 760:
        return None
    entries = [a, b, c]
    for e in entries:
        if len(e["order"]["legs"]) != 1:
            return None
        l = e["order"]["legs"][0]
        if l["car"]["premium"] or l["pickup"]["privateAddress"] or l["delivery"]["privateAddress"]:
            return None
        n = e["notes"][0] if e["notes"] else None
        if co(n and n["releasedAt"], 0) > now:
            return None
        if n and n["summerTyres"]:
            return None
    l1, l2, l3 = (e["order"]["legs"][0] for e in entries)
    P1, D1 = l1["pickup"]["placeId"], l1["delivery"]["placeId"]
    P2, D2 = l2["pickup"]["placeId"], l2["delivery"]["placeId"]
    P3, D3 = l3["pickup"]["placeId"], l3["delivery"]["placeId"]
    r1, dh1, r2 = m.road_minutes(P1, D1), m.road_minutes(D1, P2), m.road_minutes(P2, D2)
    dh2, r3, ret = m.road_minutes(D2, P3), m.road_minutes(P3, D3), m.road_minutes(D3, P1)
    total = r1 + dh1 + r2 + dh2 + r3
    if dh1 > 32 or dh2 > 32 or ret > 90 or total > 440:
        return None
    manual = any(e["built"]["audience"]["manualLicence"] for e in entries)
    pool_p1 = supply.pool30(P1, False, manual)
    pool_d3 = supply.pool30(D3, False, False)
    if pool_p1 < 35 or (ret > 55 and pool_d3 < 45):
        return None
    min_lpa = min(e["built"]["effectiveLastPickupAt"] for e in entries)
    if min_lpa - now < 300:
        return None
    day0 = jfloor(now / DAY) * DAY
    any_snow = False
    feasible = False
    for start in (now + 60, day0 + DAY + 7 * HOUR + 15):
        if start > min_lpa - 180:
            break
        cur_at, first_day, ok, sim_snow = start, -1, True, False
        for idx in range(3):
            e = entries[idx]
            prev = entries[idx - 1] if idx > 0 else None
            leg = e["order"]["legs"][0]
            n = e["notes"][0] if e["notes"] else None
            ps, ds = e["built"]["stops"][0], e["built"]["stops"][1]
            effdl = _effdl(e["order"], n, ds)
            sw = snow.overlaps(leg["pickup"]["placeId"], leg["delivery"]["placeId"], now, effdl)
            if sw:
                sim_snow = True
            link_sw = snow.overlaps(prev["order"]["legs"][0]["delivery"]["placeId"], leg["pickup"]["placeId"], now, effdl) if prev else None
            if link_sw:
                sim_snow = True
            link = jceil(m.road_minutes(prev["order"]["legs"][0]["delivery"]["placeId"], leg["pickup"]["placeId"]) * (1.25 if link_sw else 1.03)) if prev else 0
            arr = cur_at + link
            hP = co(n and n["pickupHours"], leg["pickup"].get("hours"))
            hD = co(n and n["deliveryHours"], leg["delivery"].get("hours"))
            p_from = ps["window"]["from"] if ps.get("window") else leg["pickup"]["window"]["from"]
            p_to = min(effdl, ps["window"]["to"] if ps.get("window") else e["order"]["deadline"])
            tP = visit_at(max(arr, p_from), p_to, hP, 15)
            if not isfinite(tP) or (idx > 0 and tP - arr > 75):
                ok = False
                break
            if idx == 0:
                first_day = jfloor(tP / DAY)
            extra = (PLATES_MINUTES if ps.get("withPlates") else 0) + (CHARGING_MINUTES if ps.get("withCharging") else 0)
            drv = jceil(m.road_minutes(leg["pickup"]["placeId"], leg["delivery"]["placeId"]) * (1.32 if sw else 1.04))
            tD = visit_at(max(tP + 15 + extra + drv, leg["delivery"]["window"]["from"]), effdl, hD, 15)
            if not isfinite(tD):
                ok = False
                break
            fin = tD + 15
            if effdl - fin < 260 or jfloor(fin / DAY) != first_day:
                ok = False
                break
            cur_at = fin
        if ok:
            feasible = True
            any_snow = sim_snow
            break
    if not feasible:
        return None
    ref_sum = 0
    for e in entries:
        ref_sum = ref_sum + e["request"]["referenceFeeCents"]
    ref_max = max(e["request"]["referenceFeeCents"] for e in entries)
    mkt = 1.0 + (0.10 if any_snow else 0) + (0.08 if flu else 0)
    sched = normalize_steps([{"at": now if k == 0 else clamp_out_of_night(now + k * 30, k),
                              "feeCents": jround(max(km * ref_sum, (1.04 + 0.08 * k) * ref_max) * mkt)}
                             for k, km in enumerate([0.56, 0.64, 0.72, 0.81])], now)
    crosses = jfloor(min_lpa / DAY) > jfloor(now / DAY) and min_lpa - now >= 600
    split_at = (min(min_lpa - 250, max(now + 150, jfloor(min_lpa / DAY) * DAY + 9 * HOUR)) if crosses
                else min(now + 135, min_lpa - 220))
    if split_at <= now + 35:
        return None
    return {"firstOrderId": a["order"]["id"], "secondOrderId": b["order"]["id"],
            "stops": [*a["built"]["stops"], *b["built"]["stops"], *c["built"]["stops"]],
            "audience": {"experienced": False, "manualLicence": manual}, "schedule": sched, "tier": 1, "splitAt": split_at}


_PER_DAY = re.compile(r"per day|three|3|limit", re.IGNORECASE)
_DRIVER = re.compile(r"driver", re.IGNORECASE)


class DirectOfferTracker:
    def __init__(self):
        self.last_active: dict = {}
        self.gig_viewers: dict = {}
        self.booked_or_delivered_day: dict = {}
        self.recent_deliveries: dict = {}
        self.offers_sent_by_day: dict = {}
        self.open_offers_by_gig: dict = {}
        self.global_open: set = set()
        self.attempted: set = set()
        self.declined_max_fee: dict = {}

    def record_view(self, driver, at, gig=None):
        prev = self.last_active.get(driver, -INF)
        if at > prev:
            self.last_active[driver] = at
        if gig:
            by_gig = self.gig_viewers.get(gig)
            if by_gig is None:
                by_gig = {}
                self.gig_viewers[gig] = by_gig
            cur = by_gig.get(driver)
            if cur:
                cur["lastAt"] = max(cur["lastAt"], at)
                cur["count"] += 1
            else:
                by_gig[driver] = {"firstAt": at, "lastAt": at, "count": 1}

    def _worked(self, driver, at):
        key = str(jfloor(at / DAY))
        self.booked_or_delivered_day.setdefault(key, set()).add(driver)

    def record_booked(self, driver, gig, at):
        self.record_view(driver, at)
        self._worked(driver, at)
        self.clear_gig(gig)

    def record_delivered(self, driver, place, at):
        if not driver:
            return
        self.record_view(driver, at)
        self._worked(driver, at)
        self.recent_deliveries[driver] = {"placeId": place, "at": at}

    def record_offer_queued(self, gig, driver, fee, now):
        key = f"{jfloor(now / DAY)}:{driver}"
        self.offers_sent_by_day[key] = self.offers_sent_by_day.get(key, 0) + 1
        self.open_offers_by_gig.setdefault(gig, {})[driver] = fee
        self.global_open.add(driver)
        self.attempted.add(f"{gig}:{driver}")

    def _still_open(self, driver) -> bool:
        return any(driver in mm for mm in self.open_offers_by_gig.values())

    def rollback_offer_refused(self, gig, driver, now, reason=""):
        key = f"{jfloor(now / DAY)}:{driver}"
        o = self.open_offers_by_gig.get(gig)
        if o is not None:
            o.pop(driver, None)
        if not self._still_open(driver):
            self.global_open.discard(driver)
        if _PER_DAY.search(reason or "") and _DRIVER.search(reason or ""):
            self.offers_sent_by_day[key] = 3
        else:
            cur = self.offers_sent_by_day.get(key, 0)
            if cur > 0:
                self.offers_sent_by_day[key] = cur - 1
        self.attempted.add(f"{gig}:{driver}")

    def record_offer_answered(self, gig, driver, answer):
        o = self.open_offers_by_gig.get(gig)
        offered = (o.get(driver) if o is not None else None) or 0
        if o is not None:
            o.pop(driver, None)
        if not self._still_open(driver):
            self.global_open.discard(driver)
        if answer == "accepted":
            self.clear_gig(gig)
        elif answer == "declined" and offered > 0:
            key = f"{gig}:{driver}"
            self.declined_max_fee[key] = max(self.declined_max_fee.get(key, 0), offered)

    def clear_gig(self, gig):
        o = self.open_offers_by_gig.pop(gig, None)
        if o is not None:
            for driver in o:
                if not self._still_open(driver):
                    self.global_open.discard(driver)
        self.gig_viewers.pop(gig, None)

    def offers_today(self, driver, now) -> int:
        return self.offers_sent_by_day.get(f"{jfloor(now / DAY)}:{driver}", 0)

    def open_count(self, gig) -> int:
        o = self.open_offers_by_gig.get(gig)
        return len(o) if o is not None else 0

    def select_offers_for_gig(self, m, supply, commitments, gig, now, level, max_new=2):
        if level < 3:
            return []
        tod = now % DAY
        if tod < 7 * HOUR or tod > 22 * HOUR + 45:
            return []
        slots = min(max_new, 3 - self.open_count(gig["gigId"]))
        if slots <= 0:
            return []
        scarce = supply.pool30(gig["pickupPlaceId"], gig["audience"]["experienced"], gig["audience"]["manualLicence"]) <= 8
        slack = gig["effectiveLastPickupAt"] - now
        urgent = gig["urgent"] or gig["isPastDeadline"] or slack <= 220
        exec_at = max(now, gig["earliestPickupAt"])
        exec_day = jfloor(exec_at / DAY)
        exec_wd = exec_day % 7
        evening_or_sat = exec_wd == 5 or (exec_at % DAY) >= 17 * HOUR
        same_day_exec = exec_day == jfloor(now / DAY)
        worked_today = self.booked_or_delivered_day.get(str(jfloor(now / DAY)))
        by_driver: dict = {}
        for cm in commitments:
            by_driver.setdefault(cm["driverId"], []).append(cm)
        scored = []
        viewers = self.gig_viewers.get(gig["gigId"])
        for d in supply.drivers:
            did = d["id"]
            if did in self.global_open:
                continue
            if not urgent and f"{gig['gigId']}:{did}" in self.attempted:
                continue
            used = self.offers_today(did, now)
            if used >= 3:
                continue
            is_exp = d["rating"] >= 4.8 and d["completedGigs"] >= 50
            if gig["audience"]["experienced"] and not is_exp:
                continue
            if gig["audience"]["manualLicence"] and d["licence"] != "manual":
                continue
            mins_since = now - self.last_active.get(did, -INF)
            worked = bool(worked_today and did in worked_today)
            day_drive, overlaps, chained = 0, False, False
            for cm in by_driver.get(did, []):
                if jfloor(cm["estStartAt"] / DAY) == exec_day:
                    day_drive += cm["driveMinutes"]
                    link = m.road_minutes(cm["deliveryPlaceId"], gig["pickupPlaceId"])
                    if cm["estFinishAt"] + link <= gig["effectiveLastPickupAt"] - 15 and m.dist_km(cm["deliveryPlaceId"], gig["pickupPlaceId"]) <= 35:
                        chained = True
                    elif gig["earliestPickupAt"] + gig["driveMinutes"] + 30 + m.road_minutes(gig["deliveryPlaceId"], cm["pickupPlaceId"]) <= cm["estStartAt"]:
                        pass
                    else:
                        overlaps = True
            if overlaps or day_drive + gig["driveMinutes"] > 440:
                continue
            if not chained:
                rec = self.recent_deliveries.get(did)
                if (rec and jfloor(rec["at"] / DAY) == exec_day and now - rec["at"] <= 180
                        and m.dist_km(rec["placeId"], gig["pickupPlaceId"]) <= 35):
                    chained = True
            v = viewers.get(did) if viewers else None
            repeat = bool(v and v["count"] >= 2)
            recent_viewer = bool(v and now - v["lastAt"] <= 95)
            max_inactive = 240 if v else 180 if (urgent or scarce) else 90
            if not worked and not chained and mins_since > max_inactive:
                continue
            dist_p = m.dist_km(d["homePlaceId"], gig["pickupPlaceId"])
            dist_d = m.dist_km(d["homePlaceId"], gig["deliveryPlaceId"])
            if not chained and not repeat and dist_p > 65 and dist_d > 30:
                continue
            transit = 0 if (chained or repeat) else jceil(m.road_minutes(d["homePlaceId"], gig["pickupPlaceId"]) * 1.25)
            if not chained and not repeat and now + transit + 15 > gig["effectiveLastPickupAt"]:
                continue
            score = -INF
            if chained and dist_d <= 30:
                score = 112
            elif chained:
                score = 96 if dist_p > 30 else 80
            elif dist_d == 0 and dist_p > 30:
                score = 84 - transit * 0.05
            elif dist_d <= 30 and dist_p > 30:
                score = 76 - transit * 0.05
            elif 30 < dist_p <= 65:
                score = 72 if (scarce or urgent) else 48
            elif dist_p <= 30 and dist_d <= 30:
                score = 54
            elif dist_p <= 30:
                score = 64 if (urgent or scarce) else 40
            elif repeat:
                score = 58
            if not isfinite(score):
                continue
            viewer_bonus = 52 if repeat else 32 if recent_viewer else 0
            activity = 30 if mins_since <= 15 else 22 if worked else 18 if mins_since <= 60 else 10
            drop_pen = min(26, d["drops"] * 3.8)
            budget_pen = used * 10
            exp_pen = 8 if (not gig["audience"]["experienced"] and is_exp) else 0
            total = score + viewer_bonus + activity - drop_pen - budget_pen - exp_pen
            if total < (50 if (urgent or scarce) else 72):
                continue
            if len(gig["orderIds"]) > 1:
                cap = jround(gig["refFeeCents"] * (0.68 if len(gig["orderIds"]) >= 3 else 0.75))
                tgt = jround(gig["currentAppFeeCents"] * (0.98 if chained else 1.02 + gig["offerWave"] * 0.04))
                fee = min(cap, max(gig["currentAppFeeCents"], tgt))
            else:
                if chained and dist_d <= 30:
                    mult = 0.88
                elif chained:
                    mult = 0.93
                elif dist_d <= 30 and dist_p > 30:
                    mult = 0.98 if scarce else 0.93
                elif dist_p <= 30 and dist_d <= 30:
                    mult = 0.95
                elif dist_p <= 30:
                    mult = 1.00
                else:
                    mult = 1.08 if scarce else 1.02
                if gig["hasPrivateStop"]:
                    mult += 0.09
                if gig["audience"]["experienced"]:
                    mult += 0.14
                if evening_or_sat:
                    mult += 0.05
                if not same_day_exec:
                    mult += 0.03
                mult += gig["offerWave"] * 0.08
                if gig["isPastDeadline"]:
                    mult = max(mult, 1.55 + gig["offerWave"] * 0.22)
                elif urgent and slack <= 190:
                    mult = max(mult, 1.38 + gig["offerWave"] * 0.15)
                elif scarce and slack <= 360:
                    mult = max(mult, 1.15 + gig["offerWave"] * 0.09)
                raw = jround(gig["refFeeCents"] * min(2.65, mult))
                if urgent and slack <= 190:
                    fee = max(raw, jround(gig["currentAppFeeCents"] * 1.04))
                elif repeat and not urgent:
                    fee = max(gig["currentAppFeeCents"], min(raw, jround(gig["currentAppFeeCents"] * 1.06)))
                else:
                    fee = raw
                if (dist_p <= 30 or v) and fee < gig["currentAppFeeCents"]:
                    fee = gig["currentAppFeeCents"]
            if fee <= self.declined_max_fee.get(f"{gig['gigId']}:{did}", 0) + 50:
                continue
            scored.append((total, did, max(1, fee)))
        scored.sort(key=lambda s: -s[0])
        return [{"type": "offer", "gigId": gig["gigId"], "driverId": did, "feeCents": fee} for _, did, fee in scored[:slots]]
