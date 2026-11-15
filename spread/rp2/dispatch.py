"""Port of dispatch.ts (RoutePulse v21e): fee schedules."""
from __future__ import annotations

from .js import INF, co, jfloor, jround
from .rptime import DAY, HOUR, clamp_out_of_night, day_of, day_start_of, weekday_of_day


def current_schedule_fee(schedule, now):
    fee = co(schedule[0]["feeCents"], 0) if len(schedule) > 0 else 0
    for step in schedule:
        if step["at"] <= now:
            fee = step["feeCents"]
    return fee


def bump_schedule_after_drop(schedule, now):
    prev_at = now
    out = []
    for idx, s in enumerate(schedule):
        raw_at = now if idx == 0 else max(now + idx * 25, s["at"])
        clamped_at = now if idx == 0 else clamp_out_of_night(raw_at, idx)
        at = now if idx == 0 else max(prev_at + 20, clamped_at)
        prev_at = at
        out.append({"at": at, "feeCents": jround(s["feeCents"] * 1.03)})
    return out


def build_monotonic_clamped_steps(now, step_gap, mults, fee_fn):
    prev_at = now
    out = []
    for k, mult in enumerate(mults):
        at = now if k == 0 else max(prev_at + 20, clamp_out_of_night(now + k * step_gap, k))
        prev_at = at
        out.append({"at": at, "feeCents": fee_fn(mult, k)})
    return out


def normalize_steps(steps, now, max_fee_cents=INF, min_first_fee_cents=1):
    cap = max(1, jround(max_fee_cents))
    floor0 = min(cap, max(1, jround(min_first_fee_cents)))
    mapped = [{"at": max(now, jround(s["at"])),
               "feeCents": min(cap, max(floor0 if idx == 0 else 1, jround(s["feeCents"])))}
              for idx, s in enumerate(steps)]
    mapped.sort(key=lambda s: s["at"])
    deduped = []
    for step in mapped:
        prev = deduped[-1] if deduped else None
        mono_fee = max(prev["feeCents"], step["feeCents"]) if prev else max(floor0, step["feeCents"])
        if prev and prev["at"] == step["at"]:
            prev["feeCents"] = mono_fee
        else:
            deduped.append({"at": step["at"], "feeCents": mono_fee})
    return deduped[:48]


def compute_base_step_multiplier(ctx, Q30, D_pool30, same_cluster30):
    exec_at = max(ctx["now"], ctx["earliestPickupAt"])
    pick_wd = weekday_of_day(day_of(exec_at))
    pick_tod = exec_at % DAY
    is_evening_or_sat = pick_wd == 5 or pick_tod >= 17 * HOUR

    has_extras = bool(
        ctx["hasPrivatePickup"]
        or ctx["hasPrivateDelivery"]
        or ctx["isTradeInTwoLegs"]
        or ctx["audience"]["experienced"]
        or ctx["withCharging"]
        or ctx["withPlates"]
    )

    flu_today = bool(ctx["fluActive"]) and day_of(ctx["effectiveLastPickupAt"]) == day_of(ctx["now"])

    m0 = 0.82
    if D_pool30 >= 95 and Q30 >= 40 and not has_extras and not ctx["snowOverlap"] and not flu_today and ctx["routeKm"] <= 220:
        m0 -= 0.045
    if D_pool30 <= 5 and not same_cluster30:
        m0 += 0.08
    elif D_pool30 <= 14 and not same_cluster30:
        m0 += 0.05

    if Q30 == 0:
        m0 += 0.12
    elif Q30 <= 5:
        m0 += 0.07
    elif Q30 <= 15:
        m0 += 0.03

    if ctx["routeKm"] > 260:
        m0 += 0.05
    if ctx["routeKm"] > 400:
        m0 += 0.05
    if ctx["hasPrivatePickup"] and not ctx["isTradeInTwoLegs"]:
        m0 += 0.12
    if ctx["hasPrivateDelivery"] and not ctx["isTradeInTwoLegs"]:
        m0 += 0.14
    if ctx["isTradeInTwoLegs"]:
        m0 += 0.21
    if ctx["audience"]["experienced"]:
        m0 += 0.17
    if ctx["withCharging"]:
        m0 += 0.08
    if ctx["withPlates"] or ctx["audience"]["manualLicence"]:
        m0 += 0.04
    if is_evening_or_sat:
        m0 += 0.05
    if ctx["snowOverlap"]:
        m0 += 0.12
    if flu_today:
        m0 += 0.08

    return max(0.76, min(1.45 if (has_extras or ctx["snowOverlap"]) else 1.31, m0))


RAMP_ANCHORS = [
    {"beforeLpa": 390, "add": 0.11, "floor": 0.98},
    {"beforeLpa": 295, "add": 0.22, "floor": 1.12},
    {"beforeLpa": 220, "add": 0.36, "floor": 1.28},
    {"beforeLpa": 165, "add": 0.54, "floor": 1.48},
    {"beforeLpa": 110, "add": 0.78, "floor": 1.76},
]


def build_single_gig_schedule(m, supply, ctx):
    Q30 = supply.pool30(ctx["pickupPlaceId"], ctx["audience"]["experienced"], ctx["audience"]["manualLicence"])
    D_pool30 = supply.pool30(ctx["deliveryPlaceId"], False, False)
    same_cluster30 = m.is_same_cluster30(ctx["pickupPlaceId"], ctx["deliveryPlaceId"])
    is_long_or_dead_end = ctx["routeKm"] > 250 or (D_pool30 <= 14 and not same_cluster30)
    m0 = compute_base_step_multiplier(ctx, Q30, D_pool30, same_cluster30)
    now = ctx["now"]
    base = ctx["baseRefFeeCents"]

    if ctx["orderPriceCents"] > 0:
        max_econ_fee = max(jround(base * 2.50), jround(ctx["orderPriceCents"] * 2.85))
    else:
        max_econ_fee = INF

    if ctx["level"] == 1:
        flat_mult = 2.20 if ctx["isPastDeadline"] else (max(1.48, m0 + 0.35) if ctx["urgent"] else m0)
        fee = min(max_econ_fee, max(ctx["minFloorFeeCents"], jround(base * flat_mult)))
        return [{"at": now, "feeCents": max(1, fee)}]

    if ctx["isPastDeadline"] and ctx["endsAt"] - now <= 42 * HOUR:
        rescue_mults = [
            max(m0 + 0.45, 1.58),
            max(m0 + 0.75, 1.88),
            max(m0 + 1.05, 2.22),
            max(m0 + 1.40, 2.58),
            max(m0 + 1.75, 2.95),
        ]
        rescue_abs_floors = [3800, 5000, 6400, 7800, 9500]
        return normalize_steps(
            build_monotonic_clamped_steps(
                now, 35, rescue_mults,
                lambda mult, k: max(rescue_abs_floors[k] if k < len(rescue_abs_floors) else 3800, jround(base * mult)),
            ),
            now, max_econ_fee, ctx["minFloorFeeCents"],
        )

    if (ctx["isPastDeadline"] or now > ctx["rawLastPickupAt"]) and not ctx["hasPrivateDelivery"] and ctx["endsAt"] - now > 42 * HOUR:
        t24 = co(ctx.get("tier24PickupCapAt"), None)
        cliff_slack = t24 - now if t24 is not None else INF
        if t24 is not None and cliff_slack > 35 and cliff_slack <= 380:
            if ctx["orderPriceCents"] > 0:
                break_even_mult = min(
                    2.12,
                    max(1.68, 1.20 + (0.25 * ctx["orderPriceCents"]) / max(1, base) + 0.08),
                )
            else:
                break_even_mult = 1.85
            cliff_mults = [
                max(m0 + 0.14, 1.22),
                max(m0 + 0.28, 1.36),
                max(m0 + 0.44, min(break_even_mult, 1.52)),
                max(m0 + 0.60, min(break_even_mult, 1.68)),
                max(m0 + 0.76, break_even_mult),
            ]
            cliff_gap = max(20, min(48, jfloor(max(80, cliff_slack - 32) / 4)))
            return normalize_steps(
                build_monotonic_clamped_steps(now, cliff_gap, cliff_mults, lambda mult, k: jround(base * mult)),
                now, max_econ_fee, 1,
            )

        late_day_mults = [
            max(m0 + 0.10, 1.05),
            max(m0 + 0.24, 1.20),
            max(m0 + 0.40, 1.38),
            max(m0 + 0.60, 1.60),
            max(m0 + 0.82, 1.85),
        ]
        return normalize_steps(
            build_monotonic_clamped_steps(now, 70, late_day_mults, lambda mult, k: jround(base * mult)),
            now, max_econ_fee, 1,
        )

    slack_min = ctx["effectiveLastPickupAt"] - now
    max_urgent_mult = 2.42 if ctx["highTrustDealer"] else 2.28

    if ctx["urgent"] or slack_min <= 155:
        lead_soft = -0.08 if (not ctx["isPastDeadline"] and slack_min > 155) else 0
        step_mults = [
            max(m0 + 0.24, 1.36 + lead_soft),
            max(m0 + 0.44, 1.56 + lead_soft),
            max(m0 + 0.68, 1.80 + lead_soft),
            max(m0 + 0.94, 2.06 + lead_soft),
            max(m0 + 1.18, max_urgent_mult),
        ]
        urgent_abs_floors = (
            [2800, 3400, 4100, 4900, 5800] if ctx["audience"]["experienced"] else [2100, 2600, 3200, 3900, 4700]
        )
        gap = 30 if slack_min >= 175 else 24
        return normalize_steps(
            build_monotonic_clamped_steps(
                now, gap, step_mults,
                lambda mult, k: max(urgent_abs_floors[k] if k < len(urgent_abs_floors) else 2100, jround(base * mult)),
            ),
            now, max_econ_fee, ctx["minFloorFeeCents"],
        )

    lpa = ctx["effectiveLastPickupAt"]
    lpa_day_start = day_start_of(lpa)
    post_day_start = day_start_of(now)
    crosses_night = day_of(lpa) > day_of(now)
    flu_today = bool(ctx["fluActive"]) and day_of(lpa) == day_of(now)

    ramp_offsets = []
    if slack_min >= 450 and Q30 >= 16 and not ctx["snowOverlap"] and not flu_today and not ctx["isTradeInTwoLegs"]:
        disc = 0.09 if (slack_min >= 720 and Q30 >= 28) else 0.06
        m_disc = max(0.68, m0 - disc)
        ramp_offsets.append({"at": now, "mult": m_disc})
        t_mid = clamp_out_of_night(now + 45, 0)
        if t_mid < lpa - 255:
            ramp_offsets.append({"at": t_mid, "mult": max(m_disc + 0.03, m0 - disc * 0.45)})
        t_base = clamp_out_of_night(now + 92, 1)
        if t_base < lpa - 215:
            ramp_offsets.append({"at": t_base, "mult": m0})
    else:
        ramp_offsets.append({"at": now, "mult": m0})

    if crosses_night and ctx["routeKm"] > 400:
        eve_train_at = max(now + 60, post_day_start + 19 * HOUR + 15)
        if eve_train_at <= post_day_start + 21 * HOUR + 45 and eve_train_at < lpa - 300:
            ramp_offsets.append({"at": eve_train_at, "mult": max(m0 + 0.08, 1.04)})

    if day_of(lpa) - day_of(now) >= 2:
        mid_day_at = max(now + 120, post_day_start + DAY + 10 * HOUR)
        if mid_day_at < lpa_day_start:
            ramp_offsets.append({"at": mid_day_at, "mult": min(0.98, m0 + 0.06)})

    if crosses_night and is_long_or_dead_end:
        morning_wave_at = max(now + 90, lpa_day_start + 7 * HOUR + 35)
        if morning_wave_at < lpa - 240:
            ramp_offsets.append({"at": morning_wave_at, "mult": max(m0 + 0.12, 1.08)})

    min_ramp_start = max(
        ctx["earliestPickupAt"] - 180,
        max(now + 120, lpa_day_start + ((7 * HOUR + 55) if is_long_or_dead_end else (8 * HOUR + 45)))
        if crosses_night else now + 75,
    )

    span_end = lpa - 45
    if min_ramp_start > lpa - 390 and span_end > min_ramp_start + 25:
        for idx, a in enumerate(RAMP_ANCHORS):
            frac = idx / (len(RAMP_ANCHORS) - 1)
            raw_t = jround(min_ramp_start + frac * (span_end - min_ramp_start))
            t = clamp_out_of_night(raw_t, idx)
            if t < lpa - 15:
                ramp_offsets.append({"at": t, "mult": min(max_urgent_mult, max(m0 + a["add"], a["floor"]))})
    else:
        for idx, a in enumerate(RAMP_ANCHORS):
            t = clamp_out_of_night(max(min_ramp_start, lpa - a["beforeLpa"]), idx)
            if t < lpa - 15:
                ramp_offsets.append({"at": t, "mult": min(max_urgent_mult, max(m0 + a["add"], a["floor"]))})

    return normalize_steps(
        [{"at": r["at"], "feeCents": jround(base * r["mult"])} for r in ramp_offsets],
        now, max_econ_fee, ctx["minFloorFeeCents"],
    )
