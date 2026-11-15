# Porting RoutePulse v21e (TypeScript) to Python: shared rules for every porter

Goal: a Python package `spread/rp2/` that does **exactly** what the TypeScript in `.rpv/eaa121a/src/` does: the same
actions, in the same order, with the same numbers, on the same world. It will be checked by diffing action logs of
both on the same seed, so a single different rounding or iteration order is a bug.

Paths (all under `/home/ayo/Projects/hackjunction2026/.claude/worktrees/rp-v21e/`):
- Source to port: `.rpv/eaa121a/src/*.ts` (v21e, the target).
- Old TypeScript (v17) that the existing Python port was made from: `.rpv/d00ab25/typescript/*.ts`.
- Existing, verified Python port of v17: `spread/rp/*.py`. **Reuse it.** Most v21e functions exist there in v17
  form; port the v17→v21e differences into a copy instead of translating from scratch where that is faster.
  `python3 .rpv/fndiff.py .rpv/d00ab25/typescript .rpv/eaa121a/src <tsFunctionName>` prints the v17→v21e diff of one
  function (without a name it lists every changed/new function).
- Output: `spread/rp2/<module>.py`. Only write your own assigned files. Do not edit `spread/rp/`, `.rpv/` or
  anything else.

## Module map (TypeScript file → Python module)

| TS | Python | | TS | Python |
|---|---|---|---|---|
| time.ts | rp2/rptime.py | | dispatch.ts | rp2/dispatch.py |
| supply.ts | rp2/supply.py | | bundling.ts | rp2/bundling.py |
| notes.ts | rp2/notes.py | | offers.ts | rp2/offers.py |
| planner.ts | rp2/planner.py | | outbox.ts | rp2/outbox.py |
| estimator.ts | rp2/estimator.py | | desk.ts (lines 1–1136) | rp2/desk.py |
| market.ts | rp2/market.py | | desk.ts (lines 1137–end) | rp2/desk_b.py |
| rejoin.ts | rp2/rejoin.py | | types.ts, spread.ts, reveal-csv.ts | not ported (types only / kit) |

Import each other with relative imports exactly as the TS imports: `from .planner import compute_option_plan`.
JS helpers come from `rp2/js.py` (already written): `co` (??), `or_` (||), `truthy`, `isfinite`, `jround`, `jceil`,
`jfloor`, `jtrunc`, `jmax`, `jmin`, `sum_js`, `sigmoid`, `jdiv`, `to_fixed`, `INF`. Do not redefine them.

`desk.ts` is split in two: `rp2/desk_b.py` defines `class DeskB:` holding the methods from line 1137 to the end;
`rp2/desk.py` defines `class Desk(DeskB):` with the type definitions, constructor, fields and methods of lines
1–1136. Both use `self.` for every field. Module-level helper functions of desk.ts go in the file that contains them.

## Naming (must match across modules, since each porter only sees their own files)

- Functions and methods: the TS name in snake_case, mechanically: `computeOptionPlan` → `compute_option_plan`,
  `isSameCluster30` → `is_same_cluster30`, `pool30` → `pool30`, `roadKm` → `road_km`. Private methods: no
  leading underscore (`private foo()` → `foo`). Getters (`get x()`) become plain methods `x()` — note it in a comment.
- Class names unchanged (`PricingEngine`, `RosterSupplyModel`, `DirectOfferTracker`, `ActionOutbox`,
  `CompetitorMarketEstimator`, `MapGraph`, `SnowTracker`, `Desk`).
- Class fields (`this.fooBar`) → attributes in snake_case (`self.foo_bar`).
- Exported constants: same name (`CHARGING_MINUTES`, `DAY`, `HOUR`, ...).
- **Object literals, records and JSON keep their camelCase keys as dict keys**: server events/requests/orders
  (`request["referenceFeeCents"]`), actions (`{"type": "post", "feeCents": ...}`), and every internal object literal
  or `type X = {...}` record (`plan["premiumAny"]`, `ev["trueCostCents"]`, gig states, batch states, notes). Only
  class instances use attributes. Optional fields that TS leaves undefined: leave the key out (or None) and read with
  `.get(...)`, matching how `=== undefined` / `??` are used.

## Semantics that must match exactly

- Numbers: `Math.round` → `jround` (NOT Python `round`), `Math.floor/ceil/trunc` → `jfloor/jceil/jtrunc`,
  `Math.max/min` → `max/min` when args are plain numbers (use `jmax/jmin` only if NaN or zero args are possible),
  `/` is float division (never `//` unless the TS does `Math.floor(a / b)`), `%` on possibly-negative numbers:
  JS keeps the sign of the dividend → use `math.fmod` (Python `%` differs for negatives). `Number.isFinite` →
  `isfinite`. `x | 0` → `jtrunc`. Sums with reduce → `sum_js` (left to right).
- Iteration order: JS `Map` and `Set` iterate in insertion order. Use `dict` for Map and **`dict` (keys only,
  value None or True) for any Set that is iterated**; a Python `set` may be used only for pure membership tests.
  `Object.keys/values/entries` → dict order. Deleting and re-adding a Map key moves it to the end in both.
- Sorting: `arr.sort((a, b) => ...)` → `arr.sort(key=functools.cmp_to_key(lambda a, b: ...))`, in place; JS sort is
  stable like Python's. A comparator returning a boolean or NaN: reproduce the JS result (NaN/false → 0).
  `arr.sort()` without comparator sorts as **strings**.
- Truthiness: `if (x)` / `x || y` / `!x` on numbers, strings or possibly-undefined values → `truthy` / `or_`
  (0, NaN, "" and None are falsy; empty arrays/objects are truthy). `??` → `co`.
- `undefined`/`null` → `None`. `arr.at(-1)`, `arr[arr.length-1]` → `arr[-1]` (guard empty → None).
  `arr.find(...)` → `next((x for x in arr if ...), None)`; `findIndex` → `-1` when absent.
  `arr.includes`, `str.includes` → `in`. `arr.slice(a, b)` → `arr[a:b]` (negative indices behave alike).
  `str.toLowerCase()` → `.lower()`; regexes: translate carefully (`\b`, `\s` and `\w` in JS are ASCII-only unless
  the `u` flag is set → use `re.ASCII`); `str.replace(/x/, y)` replaces the first match only unless `/g`.
  `JSON.stringify` key order = insertion order.
- Copies: `{...a}` → `dict(a)` / `{**a}`; `[...a]` → `list(a)`; `structuredClone` → `copy.deepcopy`.
- Integer cents stay int where the TS keeps integers; results of `/` are float — don't add int() casts the TS
  doesn't have.

## Done means

Your modules import cleanly (`cd spread && python3 -c "import rp2.<module>"`; modules that import others may wait
until those exist — then check with a stub-free syntax check `python3 -m py_compile`), every function and method of
your TS files is ported with the names above, and you report: the public names you defined, any TS construct whose
translation you were unsure about (with file:line), and any name you had to assume from another module.
