"""Time helpers. Python port of time.ts (RoutePulse v21e)."""
from __future__ import annotations

import math

from .js import jfloor

HOUR = 60
DAY = 24 * HOUR

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _jmod(a, b):
    """JavaScript a % b (sign of the dividend)."""
    if isinstance(a, int) and isinstance(b, int):
        r = abs(a) % abs(b)
        return -r if a < 0 else r
    return math.fmod(a, b)


def day_of(minute):
    return jfloor(minute / DAY)


def day_start_of(minute):
    return jfloor(minute / DAY) * DAY


def tod_of(minute):
    return _jmod(_jmod(minute, DAY) + DAY, DAY)


def weekday_of_day(day):
    return _jmod(_jmod(day, 7) + 7, 7)


def clamp_out_of_night(t, stagger_idx=0):
    """Shifts overnight fee-step timestamps (22:45..07:05) to morning wake (07:05 + 25m stagger)."""
    day = day_of(t)
    tod = tod_of(t)
    if tod >= 22 * HOUR + 45:
        return (day + 1) * DAY + 7 * HOUR + 5 + stagger_idx * 25
    if tod < 7 * HOUR + 5:
        return day * DAY + 7 * HOUR + 5 + stagger_idx * 25
    return t


def clamp_trigger_to_awake_window(t):
    """Shifts overnight timer wakeups (>22:40 or <07:00) to the next 07:05 awake boundary."""
    tod = tod_of(t)
    if tod > 22 * HOUR + 40:
        return (day_of(t) + 1) * DAY + 7 * HOUR + 5
    if tod < 7 * HOUR:
        return day_start_of(t) + 7 * HOUR + 5
    return t


def clone_opening_hours(hours):
    if not hours:
        return None
    sat = hours.get("saturday")
    return {
        "opens": hours["opens"],
        "closes": hours["closes"],
        "weekdays": list(hours["weekdays"]),
        "saturday": dict(sat) if sat else None,
    }


def opening_slot_for_day(hours, day):
    wd = weekday_of_day(day)
    if wd == 5:
        return hours.get("saturday")
    return hours if wd in hours["weekdays"] else None


def shift_deadline_business_days(deadline, shift):
    """Shifts a dealer deadline forward by `shift` business days (skipping Sat/Sun, capped at last Monday)."""
    if shift <= 0:
        return deadline
    day = day_of(deadline)
    tod = _jmod(deadline, DAY)
    rem = shift
    while rem > 0:
        day += 1
        wd = weekday_of_day(day)
        if wd != 5 and wd != 6:
            rem -= 1
    return min(7 * DAY + tod, day * DAY + tod)
