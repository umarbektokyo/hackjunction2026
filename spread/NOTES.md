# Spread: working notes

Start a new session from this file instead of re-reading the history. Last updated Saturday 14 November 2026, ~05:00 Helsinki (hand-over).

## Setup

- `. spread/env.sh` sets `SPREAD_URL`, `SPREAD_KEY` (from the gitignored `spread/.env`) and `SSL_CERT_FILE` (from certifi; python.org Python on macOS lacks CA certificates).
- The kit is installed in `/Users/umarbek/Documents/claude/hackjunction2026/.venv`. Its source is in `spread/vendor/kit/spread/` (the starter is `starter.py`).
- `bot.py` holds our bot, `EvilDesk(Desk)`. Every idea is a key in `DEFAULTS`, and `--params '{json}'` overrides it.
- `bench.py --name X --seeds 8 --params '{json}'` runs the seeds `bench-1…8` in parallel (8 practice slots). It appends to `logs/bench.jsonl` and prints the mean margin, the weeks ranked and the worst on-time share.
- `sweep.sh N 'name {json}' …` runs several benches one after another. Run it with nohup and a Monitor on its output.
- `analyse.py <world id>` prints profit per order by option and by place, from a world's reveal.
- `board.sh` plays the 5 ranking runs of the current round with the best fee-clock setting.
- Clean-up: crashed runs leave unfinished worlds that hold practice slots. Delete the unfinished practice worlds where `boardRun` is None (snippet: `client.worlds()`, then `world.delete()`).

## Best bot: `bot2.py` (learned models)

`bot2.py` subclasses `EvilDesk` and uses `models.pkl`. The fee, late-risk, booking and dealer-choice models are trained by `ml_export.py`, `ml_tables.py`, `ml_features.py` and `ml_fit.py` from our logged reveals. Its defaults already include the hand-tuned configuration below.
- **Pricing (`win_model`):** per option, the price that maximises P(dealer takes it) × (price − expected fee − expected late cost). The market level is learned live with a grid Bayes filter.
- **Fees (`fee_model`):** the opening fee comes from the booking model, keeping the fee clock shape.
- **Result:** €7,336 a week on 8 seeds, ranked 8/8, 96.7% on time, worst week 93.3%. That is +37% over `bot.py`.
- **Benchmark:** `./ml_bench.sh 'name|bot2.py|1|{json}'` (7 jobs). The `--bot` option of `bench.py` chooses the script.
- **Ablations:**
  - Without the fee model (`{"fee_model":0}`): €7,389, ranked 8/8, worst week 94.8%. So the learned opening fee adds nothing over the fixed 0.8×; the gain comes from pricing. Run with `fee_model` 0 until the fee model is retrained.
  - Without the win model (`{"win_model":0}`): €5,653, ranked 8/8, worst week 91.7%. So the pricing model is worth about +€1,700 a week.
- **Speed is not yet checked against the final's clock** (4.5 s per quote, 20 actions/s). One orphan run used about 600% CPU; check `--final` timing before relying on it.
- **Retrain** when we have more logged weeks: run `ml_export.py`, then `ml_tables.py`, then `ml_fit.py`.

## Live play: final, test finals, ranking runs (`bot2.py`)

- **Final / test final:** `cd spread && . ./env.sh && nohup ../.venv/bin/python bot2.py --final > logs/final-$(date +%H%M).log 2>&1 &`.
  It waits until the final is set, then rebuilds from `snapshot()` and `events()` (`rejoin`), reads `world.stream(idle=1.0)`
  and sends its outbox with `act`, quotes first. After a lost connection or an error it rebuilds and goes on; a 403/404
  (world gone) stops it. **Restart = run the same command again**: it restores its learned state (market filter, dealer
  trust, ...) from `logs/live-state-<world>.pkl`, saved every 5 s; without that file it rebuilds trust from the events.
- **Ranking run:** `bot2.py --board --quiet --json`. It plays with `advance` like practice, but rebuilds from the
  server after any error instead of crashing (a crashed ranking run plays on without us and still counts).
- **Rehearsal of the final on a practice world:** `pace.py --seed X --final-clock` moves a practice world on the
  final's clock (18 s per weekday hour, 6 s on Saturday, 3 s at night; 34.3 min); `bot2.py --world <id>` plays it live.
  `pace.py --minutes 12` runs a uniform, harsher clock. Ctrl-C on pace.py deletes the world; nothing else does.
- **Defaults now:** `fee_model` 0. Direct offers are off by default (`offer_raise`, `chain_offers`).
- **Timing (rehearsal 1, 20 world min/s, harsher than the final):** model time per quote ≤ 32 ms; quote + send
  p50 95 ms, p99 0.5-0.9 s, one 2.1 s send (server latency). A quote has 15 world minutes = 4.5 s on weekdays,
  1.5 s on Saturday, so this is fine. One process, `OMP_NUM_THREADS=1` (set in bot2.py), about 6% CPU.
- **Rehearsal 2 (final clock, bench-2, 34 min):** quote + send p50 91 ms, p99 ~0.5 s, max 1.9 s (one server spike);
  model ≤ 17 ms; no rejected quotes. A DNS outage on our side at minute ~13000: the bot retried and rejoined with its
  state restored. Score at minute 12966: €4,749, 270 orders, 94.8% on time (the pacer then died in the outage).
  Since then, quotes go in their own `act` request before posts and other actions (a send spike can't delay a quote).
- **During the final, run nothing else on the key** (practice drops to 20 req/s while a final runs).
- **Kill test (rehearsal 1):** `kill -9` at minute ~3270, restart 10 s later: "learned state restored", rejoined at
  minute 3530 with 41 orders and 5 open requests in 3.0 s. A 20 s server timeout later was handled (retry).

## Session of Sat 14 Nov, 02:30-05:00: results and hand-over

All benchmarks: level 8, seeds bench-1..8, `bot2.py`, against **baseline `{"fee_model":0}` = €7,389, worst week 94.8%**.

| Change | €/week | Worst on time | Verdict |
|---|---|---|---|
| Direct offers before each raise (`offer_raise`) | 7,413 | 95.2% | noise; ~1% of offers accepted |
| Offers + chain offers to our finishing drivers | 7,370 | 94.3% | no gain |
| Chain offers only | 7,326 | 93.8% | no gain |
| Retrained models on 188 weeks incl. bot2's (`models_v2.pkl`) | 7,344 | **97.0%** (mean 98.0%) | same money, safer |
| `fee_open` 0.9 | 7,019 | 92.4% | worse |
| `fee_open` 0.7 | 6,041 | 96.5% | worse |
| `fee_open` 0.6 | 3,965 | 94.1% | much worse |

So the opening fee 0.8 with the fee clock is a sharp optimum, and offers are not the lever. Offers stay off by default.
`models.pkl` is still the original (copy in `models_v1.pkl`); to use v2 pass `{"models":"models_v2.pkl"}`, or copy it over
`models.pkl`. It is a judgement call: same margin, better worst week (good for the 90% rule in the final).

**Margin analysis (bot2, `ml_orders`):** ~289 orders/week, revenue €70/car, driver fee €43/car (= 1.0× typical fee),
margin €26/order. Price/list 1.36 on all options. Margin by drive: ≤60 min €16 (1000 of 2311 orders), 60-120 €30,
120-180 €42. 66% of gigs book at the first step (0.8×), median 14 min. Leaders make ~€49/car, so the gap is pricing
(short cheap lanes earn little) rather than fees, which we have now tuned. Ideas not yet tried: price short lanes higher
or decline them; "price of lateness" (spend on-time slack, Fable 5.1); return-leg pairs (Fable 4.2).

**Code changes this session:** `bot2.py --final` / `--world <id>` (live stream play, rejoin, state file, timing,
quotes sent first in their own request), `bot2.py --board` (ranking run with auto-rebuild on errors), direct offers
behind switches, `fee_model` default 0; `pace.py` (real-time practice world, `--final-clock`); `ml_fit.py --out=`;
`ml_tables.py` labels bot2 weeks with their real fee policy.

**To do next (in order):**
1. Test final 1, Sat 14:00 Helsinki (set 13:45): from `spread/`, `. ./env.sh && nohup ../.venv/bin/python bot2.py --final > logs/final-test1.log 2>&1 &`
   (start any time before; it waits). Mid-run, kill it (`pkill -f "bot2.py --final"`) and run the same command again
   to test the restart. Run nothing else on the key meanwhile. Test final 2 at 20:00, same command.
2. Ranking round (09:00, 12:00, ...): 5 runs one at a time: `for i in 1 2 3 4 5; do ../.venv/bin/python bot2.py --board --quiet; done`
   (`--board` is untested on a real ranking run; check the first run's log).
3. Pricing for short lanes / price of lateness, benchmarked with `./ml_bench.sh 'name|bot2.py|1|{json}'`.
4. Sunday: register before 07:30, final 08:00 (`bot2.py --final`), code link + hash by 10:00.

## Hand-tuned configuration (`bot.py`)

```json
{"fee_open":0.8,"fee_cap":1.7,"target_win":0.4,"max_minutes":180,"min_drivers":20,"fee_clock":1,"past_saving":1}
```

That gives €5,373 a week on 8 seeds, ranked on 8 of 8, with 95.5% on time on average and a worst week of 91.9%.

For the final, consider adding `"loc_k":0.05,"loc_free":3,"min_slack":360`. That setting held a worst week of 96.8% for about −€350 a week (it was measured without the fee clock).

## Results (level 8, 8 seeds unless noted)

| Setting | €/week | Ranked | Worst on time |
|---|---|---|---|
| Kit starter | about −70k | 0 | 45% |
| v1: opening fee 1.25, target win 0.55 (16 seeds) | −6,086 | 8/16 | 81% |
| Opening fee 1.0, cap 1.8, target win 0.4 | 2,246 | 6/8 | 83% |
| Opening fee 0.8 | 5,626 | 6/8 | 84.5% |
| Opening fee 0.6 | 2,757 | 6/8 | 85% |
| Opening fee 1.0 + cutoffs (max 180 min, min 20 drivers) | 4,238 | 8/8 | 92% |
| **Opening fee 0.8 + cutoffs** | **5,154** | **8/8** | **93%** |
| + dealer trust uplift 1% | 4,937 | 8/8 | 93.5% |
| + local congestion and min slack 6 h | 4,806 | 8/8 | **96.8%** |
| + adaptive opening fee | 4,674 | 8/8 | 94.4% |
| + fee clock + past_saving | **5,373** | 8/8 | 91.9% |
| + fee clock + bulk controls | 4,666 | 8/8 | 92.3% |
| **`bot2.py`, learned pricing and fees** | **7,336** | **8/8** | **93.3%** |

**Our ranking round, "Saturday 00:00"**, played with the best configuration above: runs of €6,346, €6,619, €7,132, €6,060 and €6,013. That totals €32,170 (€6,434 a week), with 97.4% on time and all five weeks ranked. Rank 28 of 32 ranked teams; 124 teams in the round.

**Board, round "Saturday 00:00":** #1 makes €16.0k a week, House best €14.4k, #10 €11.3k. We need more than €11k a week to make the top 10. The board shows 5-week totals.

## Findings

- Our margin per car is about €15; the leaders make about €49. Our reliability is fine, so the gap is in pricing and fees.
- With an opening fee of 1.0, 78% of gigs booked at the first step, with a median of 9 minutes. An opening fee of 0.6 is too low, because drivers learn to wait.
- Drives over 3 h and pickups with few drivers nearby lose money. Fable found that driver supply near the delivery predicts cost better than supply near the pickup.
- Unranked weeks came from the Friday same-day bulk order (30–40 cars from one yard, with the same `batchId`) and from long northbound lanes.
- The old fee ladder raised fees overnight; the fee clock fixes that.
- Python's default macOS SSL fails; `env.sh` handles it.

## Next steps

Done: the learned models (`bot2.py`, +37%). Next, in order of expected gain per hour:

1. **Make `bot2` final-ready.** Add a `--final` mode: copy `play_final` from the starter, using EvilDesk's rejoin. Time each decision, and keep it under about 0.5 s per quote batch. Play test final 1 (Saturday 14:00 Helsinki) live, including a kill and restart. Without this, the gains don't count.
2. **Learning loop.** Every bot2 week becomes new training data. Retrain on all weeks, including bot2's own, which covers prices and fees the old bots never tried; then benchmark. Repeat 2–3 times.
3. **Direct offers** (Fable 3.4 and 4.1): offer a gig to its viewers before a raise, and to drivers finishing one of our gigs near its pickup. This is the biggest unused lever, because chained drivers are the cheapest.
4. **Price of lateness** (Fable 5.1): one variable, ρ, from the forecast on-time share. It replaces the hard cutoffs, so we can win more long or thin-supply cars on safe weeks.
5. **Return-leg two-car gigs** (Fable 4.2), only if an offline count finds at least 25 feasible pairs a week.
6. Ranking rounds at 09:00, 12:00 and so on, with the best bot. They don't count for the final but show our real position.
7. Before Sunday 10:00, submit the code link and hash on the Junction platform. Register for the final before 07:30 on Sunday.

## Saving tokens

- Run long jobs with nohup and watch them with Monitor. Batch the settings into one sweep, so there is one notification per setting.
- Use subagents only for heavy reading or analysis whose raw output we don't need; each one starts cold.
- Start a fresh session from this file when the conversation gets long.
