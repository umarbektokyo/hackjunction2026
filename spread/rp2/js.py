"""JavaScript-compatible helpers for the rp2 port (RoutePulse v21e). Every module imports from here, so all modules
round, sum and compare exactly as the TypeScript does: the port must replay the TypeScript's actions to the cent."""
from __future__ import annotations

import math

INF = math.inf


def co(a, b):
    """JavaScript a ?? b."""
    return a if a is not None else b


def isfinite(x) -> bool:
    """Number.isFinite."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def jceil(x):
    return x if not math.isfinite(x) else math.ceil(x)


def jfloor(x):
    return x if not math.isfinite(x) else math.floor(x)


def jround(x):
    """Math.round: halves go up (towards +infinity)."""
    return x if not math.isfinite(x) else math.floor(x + 0.5)


def jtrunc(x):
    return x if not math.isfinite(x) else math.trunc(x)


def jmax(*xs):
    """Math.max: NaN wins; max() of nothing is -Infinity."""
    if len(xs) == 1 and not isinstance(xs[0], (int, float)):
        xs = tuple(xs[0])
    if not xs:
        return -INF
    if any(x != x for x in xs):
        return math.nan
    return max(xs)


def jmin(*xs):
    """Math.min: NaN wins; min() of nothing is +Infinity."""
    if len(xs) == 1 and not isinstance(xs[0], (int, float)):
        xs = tuple(xs[0])
    if not xs:
        return INF
    if any(x != x for x in xs):
        return math.nan
    return min(xs)


def sum_js(xs) -> float:
    """Left-to-right sum, as reduce((a, b) => a + b, 0)."""
    s = 0
    for x in xs:
        s = s + x
    return s


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def jdiv(a, b):
    """a / b with JavaScript's results for division by zero."""
    if b == 0:
        if a == 0 or a != a:
            return math.nan
        return INF if (a > 0) == (math.copysign(1, b) > 0) else -INF
    return a / b


def truthy(x) -> bool:
    """JavaScript truthiness (0, NaN, '', None, False are falsy; empty list/dict are truthy)."""
    if x is None or x is False:
        return False
    if isinstance(x, (int, float)):
        return x == x and x != 0
    if isinstance(x, str):
        return x != ""
    return True


def or_(a, b):
    """JavaScript a || b."""
    return a if truthy(a) else b


def to_fixed(x: float, digits: int) -> str:
    """Number.prototype.toFixed for the magnitudes used here (half away from zero on the decimal string)."""
    from decimal import Decimal, ROUND_HALF_UP
    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
