# RoutePulse ranking experiments

Level 8 practice results. The eight-world baseline was €15,364/week, with all
eight runs ranked. Changes below were evaluated against the same fixed seeds.

| Policy change | Worlds | Mean margin/week | Ranked | Worst on-time | Decision |
|---|---:|---:|---:|---:|---|
| Throughput target ×1.12 | 4 | €14,663 | 4/4 | 93.4% | Reject |
| Quote price ×1.02 | 4 | €14,520 | 4/4 | 93.3% | Reject |
| Lateness threshold ×1.15 | 4 | €14,916 | 4/4 | 95.8% | Reject |
| Throughput target ×0.90 | 4 | €14,600 | 4/4 | 93.6% | Reject |
| Fitted lane effects ×1.00 | 8 | €14,690 | 8/8 | 92.5% | Reject |
| Fitted lane effects ×0.50 | 8 | €14,812 | 8/8 | 92.1% | Reject |
| Quote price ×0.98 | 4 | €14,983 | 4/4 | 92.8% | Reject |
| Quote price ×0.99 | 4 | €14,986 | 4/4 | 93.9% | Reject |
| 2% discount, modeled cost ≤55% of reference | 4 | €15,067 | 4/4 | 95.6% | No score change |
| 2% discount, modeled cost ≤75% of reference | 4 | €14,693 | 4/4 | 92.8% | Reject |
| Driver schedule fees ×0.98 | 4 | €14,691 | 4/4 | 93.4% | Reject |
| Direct offers disabled | 4 | €14,228 | 4/4 | 92.5% | Reject |
| Bundling disabled | 4 | €13,239 | 3/4 | 89.9% | Reject |
| Direct-offer fee ×0.98 | 4 | €14,812 | 4/4 | 94.7% | Reject |
| Online quote learning disabled | 4 | €14,114 | 4/4 | 91.2% | Reject |
| 2% discount while order pace <90% | 4 | €14,375 | 4/4 | 92.7% | Reject |

The lane fit used revealed worlds while excluding the eight benchmark worlds.
It combines pickup and delivery place effects learned from quote outcomes with
the existing lane prior. Both strengths underperformed the baseline, so the
fit remains opt-in and is not a recommended ranking policy.

The current leaderboard gap suggests the stronger teams are winning more
orders while keeping slightly better margin per order. These broad policy
changes did not reproduce that combination. The next experiments should
target incremental driver cost and capacity from bundles, direct offers, and
dispatch timing, while measuring the 90% on-time constraint on each seed.

The simplification ablations show that both direct offers and bundling earn
their complexity: disabling direct offers reduced the four-world mean by
€839/week; disabling bundling reduced it by €1,828/week and made one world
unranked. Disabling online quote learning reduced the mean by €953/week.
Keep these features enabled while tuning how they are used.

## Pairing hold window

The default waits 22–32 minutes for a compatible second order before posting a
single-order gig. Since another public bot reported a gain from return-trip
pairing, I tested 1.5× and 2× waits on `bench-1`…`bench-4` against the current
four-seed baseline (€14,523/week, 97.2% mean on time, worst 95.6%). The 1.5×
window scored €14,054/week (−€469), 96.5% mean on time, worst 93.4%. The 2×
window scored €14,407/week (−€116), 96.7% mean on time, worst 93.4%. Neither
added consistent order volume. Keep the existing 22–32 minute window.

## Within-3-days steering discount

Dealers took `within_3_days` on only ~4 of ~180 weekly requests where we quoted it, because its price was
capped just €2 under `next_day`. `d3_discount` (default 0, off) prices it at `next_day × (1 − d)` (floor: cost
+ €5) to steer dealers to the slower, cheaper-to-serve option. Against the 8-seed baseline (€15,364/week):

| d3_discount | bench-1…4 | bench-5…8 | 8-seed mean | Worst on time | Decision |
|---:|---:|---:|---:|---:|---|
| 0 (baseline) | €14,523 | €16,205 | €15,364 | 94.3% | keep |
| 0.05 | €14,208 | €15,863 | €15,036 | 94.0% | Reject |
| 0.08 | €14,813 | €15,144 | €14,978 | 91.7% | Reject |
| 0.12 | €13,727 | €15,575 | €14,651 | 91.1% | Reject |

The 0.08 run looked like +€290 on bench-1…4 and then lost €1,061 on bench-5…8. Any small policy change
moves a single seed by ±€1,000, so a 4-seed mean has a noise floor of about ±€500. Most single-split
"Reject" rows above are within that noise.

## 32-seed paired sweep (Sun 15 Nov, 06:06–06:59)

`bot4.py` on `bench-1`…`bench-32`, each setting against the same seeds; Δ is the mean per-seed difference
from the baseline with its standard error. All 32 weeks ranked in every setting.

| Setting | Mean €/week | Paired Δ | Better on | Worst on time |
|---|---:|---:|---:|---:|
| Baseline | €15,156 | | | 93.4% |
| `late_threshold_mult` 1.15 | €15,022 | −€134 ± 109 | 16/32 | 93.5% |
| `d3_discount` 0.05 | €15,159 | +€3 ± 90 | 17/32 | 93.2% |
| `quote_mult` 0.99 | €15,254 | +€98 ± 196 | 18/32 | 93.4% |
| `target_mult` 1.12 | €15,065 | −€91 ± 149 | 17/32 | 93.3% |
| `quote_mult` 1.01 | €14,976 | −€180 ± 135 | 11/32 | 93.6% |

No setting beats the baseline by more than its noise. The current RoutePulse defaults sit at a local optimum
for these knobs; quote prices of 0.99–1.00× are best, and 1.01× is worse.
