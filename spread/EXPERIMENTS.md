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

The lane fit used revealed worlds while excluding the eight benchmark worlds.
It combines pickup and delivery place effects learned from quote outcomes with
the existing lane prior. Both strengths underperformed the baseline, so the
fit remains opt-in and is not a recommended ranking policy.

The current leaderboard gap suggests the stronger teams are winning more
orders while keeping slightly better margin per order. These broad policy
changes did not reproduce that combination. The next experiments should
target incremental driver cost and capacity from bundles, direct offers, and
dispatch timing, while measuring the 90% on-time constraint on each seed.
