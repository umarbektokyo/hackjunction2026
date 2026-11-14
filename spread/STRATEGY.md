# Spread: strategy draft

Sources: the site's `/how` page, `HANDBOOK.md`, `RULES.md`, `API.md` and `/judging`, read on 14 Nov 2026. Where they differ, the rules win.

## What matters

- **Only level 8 counts.** The final is one secret level 8 week, and ranking rounds don't carry over. Use levels 1–6 to test the plumbing, then tune only on level 8.
- **Margin gets you into the top 10. After that, the jury decides.** It scores elegance, clarity, creativity and robustness, and wants each idea shown "with and without" on the same weeks. Every idea below should be something we can switch off and measure.
- **The 90% on-time rule is a hard limit, not a target.** Below it you are not ranked at all. An undelivered car costs twice its price. At level 8 a late car also halves that dealer's trust count.
- **We don't need our own simulator for Spread.** Practice worlds are deterministic, and `fork` copies a world with the same future draws. The server already is the simulator. (A local simulator only matters if we still want one for AfterQuery.)

## The bot in one sentence

For each request, estimate what it will cost us to deliver each option and how likely each price is to win. Quote the price with the highest expected profit. Quote a very high price on cars we can't deliver cheaply and on time. Then dispatch our wins as cheaply and as early as we safely can.

```
expected profit(price) = P(win | price) × (price − expected driver cost − expected late cost)
```

## 1. Cost model: what will a car cost to move?

- `GET /v1/worlds/{id}/drivers` gives every driver's **home place**, rating, licence and drop count. Together with `GET /v1/map` (road minutes for every pair of places), we can estimate driver supply near each pickup and the extra driving to it.
- Fit a fee model from practice logs, using `gig_booked` fees against road minutes, distance from pickup to the nearest driver homes, hour, weekday, private address, trade-in, charging and plates. A few hundred level 8 weeks give plenty of data.
- At level 8 some towns lose nearly all their drivers. Find them early in the week (gigs there are not viewed, or are viewed only at high fees) and price cars into or out of them as near-declines.
- Count a **pairing discount**: a car whose pickup is near a delivery we already have, or two cars from the same yard, costs "only the extra time and tickets" when both go on one multi-car gig.

## 2. Win model: what will the competitor charge?

The competitor's price is list × lane × day × world level × noise. We only ever see won or lost.

- **World level (level 8: 26–54% above list):** this is the biggest unknown and it is fixed for the whole week. Estimate it in the first hour with a Bayesian update from won and lost quotes, starting from the prior above. Quote a little lower early on, so each answer tells us more.
- **Lane factor:** part of it is shared across all worlds. **Fork** a practice world at a request, quote different prices in each copy, and read off the exact price where we stop winning. Repeat across seeds to build a table of lane factors offline. This is our most "creative" lever, and it is fully within the rules: practice worlds are meant to be forked.
- **Day factor and morning shifts:** a short-memory adjustment from today's win rate on each lane and region.
- **Price-war day (20% below on one working day, unannounced):** detect a sudden drop in our win rate across all regions by about 09:00, then stop chasing. Lose those requests on purpose rather than winning at a loss.
- **Outage day (one region, about 30% dearer backup):** detect a sudden rise in our win rate in one region, then raise our prices there.
- **The competitor reacts to us:** when we win most of a dealer's requests, it lowers its prices for that dealer the next morning. Cap our win share per dealer and keep a margin on cars we would win anyway.

## 3. Choosing cars

- Always send a quote. A silent request costs goodwill, but a losing quote costs nothing, so we decline by quoting high.
- **Prefer `within_3_days`**: it gives room to batch and to reach cheaper drivers. Charge a lot for `same_day`, especially to the north.
- **Dealer trust (level 8):** every on-time order raises what that dealer accepts by 1%, up to +25%, and a late one halves the count. Focus on a set of dealers with cheap lanes, build their trust from Monday, and never risk a late car for them.
- **Capacity:** with only a third of the drivers, every car we win uses up supply. Weigh the expected cost of each new car against the drivers already committed in that area that day.

## 4. Dispatch

- **Post as soon as we win.** A late fee raise usually finds nobody.
- **Fee schedule:** open near the estimated cost, raise only a little and not on a fixed pattern (drivers learn a pattern and wait for it), then jump at `deadline_close`.
- **Direct offers** to drivers whose homes are near the pickup (up to 3 per driver per day, 10 minutes to answer). Prefer drivers already on our gigs nearby, since a second car costs them little.
- **Rescue mode:** as the deadline nears, pay whatever it takes. A €300 fee beats a 2× penalty.
- **Hard rules in code:** experienced driver for premium cars, a charging stop for EVs under 30% on routes over 200 km, plates when needed, pickups inside opening hours.
- **Dealer notes** (fi/sv/en): an LLM turns each note into structured changes (ready time, site hours, plates, risk) before we quote. Quote high on notes it can't parse.

## 5. Robustness (part of the jury score)

- Rebuild state from events: on restart, read `snapshot` and `events` and resume. Test it by killing the bot halfway through a test final.
- Stay within final rate limits: 20 actions/s and 50 reads/s, with up to 50 actions per call. Keep a priority queue (quotes before `respondBy` first, then rescues, then new posts).
- Handle 429/502/503/504 by backing off and re-reading state, never by blindly resending.

## 6. Evaluation

- `make bench`: 20 fixed level 8 seeds, reports margin, on-time share and undelivered share for each seed. Every idea is a flag, so we get the "with/without" table for the pitch for free.
- Log every request, quote, outcome and fee to disk. That log trains the fee and win models.
- Play every ranking round (from Fri 19:30, then every 3 h) and both test finals (Sat 14:00 and 20:00) with the current best bot.

## Timeline

| When | Goal |
|---|---|
| Fri night | Starter kit runs at level 8, event-sourced state, logging, `make bench` |
| Sat morning | Fee model and win model v1; always send a quote; decline bad lanes |
| Sat 14:00 | Test final 1, run live, including a kill-and-restart test |
| Sat afternoon | Fork-based lane table, dealer trust, multi-car gigs, direct offers |
| Sat 20:00 | Test final 2 with the full bot |
| Sat night | Detect price-war and outage days, LLM note parser, freeze the code |
| Sun 07:30 | Register for the final; preliminary hash already submitted |
| Sun 08:00 | Final (about 34 min); hash and code link by 10:00 |

## Open questions

- How well can we estimate the fee from the driver list? Check on the first 20 logged weeks.
- Is `fork` cheap enough to probe lane factors at scale under the practice rate limit?
- Is the starter kit's TypeScript or Python version the better base for us?
