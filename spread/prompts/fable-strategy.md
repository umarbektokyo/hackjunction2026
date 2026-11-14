# Prompt for Fable: better decision logic for a Spread bot

Copy everything below the line into Fable. If you have them, attach `bot.py` and the latest `logs/bench.jsonl`.

---

You are helping a hackathon team build an automated dispatcher for **Spread**, a simulation challenge by Bahn Express at Junction 2026. We have a working bot that's barely profitable. The best teams make about 6× more per week. I want you to design **better decision logic**: the maths, the algorithms and the order to build them in. Be concrete enough that we can code each idea in an hour or two and measure it.

## The game

We run a car-transport company in Finland for one simulated week. Times are whole minutes from Monday 00:00, and money is integer euro cents.

**Requests.** Car dealers send about 1,000 price requests a week, Monday 08:00 to Friday 18:00. Each request has:
- one or two legs: a car from a pickup place to a delivery place. A trade-in has two legs, the new car out and the old car back.
- 1–3 delivery options: `same_day`, `next_day` and `within_3_days`. Each has a deadline (always 20:00 on a business day) and a **list price**. The list price comes from a public price list by distance.
- a **typical fee** (`referenceFeeCents`): roughly what a driver who lives in the pickup town needs, scaled by one world-wide factor, plus noise. In our data, list price ≈ 1.11 × typical fee (median), with a range of 0.5–2.4.
- sometimes a free-text note in Finnish, Swedish or English, which can change ready times, site hours, plates or the gearbox.
- 15 minutes to answer.

**Quoting.** We quote a price for any subset of the options, and can re-quote until the deadline. The dealer then compares our price for each option with a competitor's price and with how much it values speed. A losing quote costs nothing. Not quoting costs a little goodwill, so we decline by quoting very high. We learn only won or lost: never the competitor's price.

**Competitor price.** For each option it is list price × four factors:
- **Lane factor (pickup → delivery).** Part of it is almost the same in every world: higher where little work comes back and where few drivers live near the delivery. The rest is new in each world.
- **Day factor.** New each day.
- **World price level.** At level 8 (the final's level) this is 1.26–1.54 × list, drawn once per world.
- **A small per-request factor.**

The competitor also moves during the week:
- Some mornings it shifts prices for cars into or out of one place by a step.
- Once a week its price curve changes shape, so short and long lanes move in opposite directions.
- Each morning it lowers its prices for dealers where we won most of their recent requests, and raises them where we won few, by a few steps at most.
- **Price war:** on one working day, 08:00–18:00, unannounced, it quotes 20% below its usual prices everywhere.
- **Outage:** on one working day, it is down in one region (a town plus 80 km), and dealers there use a backup about 30% dearer.

The acceptance probability falls with our price relative to the competitor's, and falls quickly above it. Dealers differ in price sensitivity and in how much they value speed.

**Dealer trust (level 8).** Each dealer counts our on-time orders, up to 25. Each one raises the prices that dealer accepts from us by 1%. A late order halves the count. Late or undelivered orders also make a dealer generally accept only lower prices from us.

**Gigs and fees.** For each order we win, we post a **gig** in a drivers' app. A gig is an ordered list of stops plus a fee schedule of 1–48 steps of `(minute, fee)`; fees never fall within a schedule.
- We can `reprice` or `withdraw` an unbooked gig.
- We can send a **direct offer** to one driver: they have 10 minutes to answer, with at most 3 offers per driver per day and 3 open offers per gig.
- We can `release` a booked driver before they leave, for a fee.
- One gig can carry several cars, with up to 12 hours of driving between first pickup and last delivery.

**Drivers.**
- **Who they are.** About 800 drivers. The roster (home town, rating, licence, completed gigs, drops) is visible at the start. At level 8, the world has only 26–40% of an average world's drivers, and each town's share is multiplied by a random factor, so some towns have almost none.
- **What a gig costs them.** Drive time, plus public transport to the pickup, plus a pricier same-day ticket home, plus extras (evening, weekend, private address, trade-in, charging, plates, dislikes).
- **When they book.** A driver books when fee − cost beats their other options that day and beats what they expect from waiting for a raise. Notifications go only to drivers whose home is within 30 km of the first pickup, and not between 23:00 and 07:00. Most views come in the first minutes after posting.
- **Drivers learn our fee behaviour.** For each order, a driver who viewed it and could have done it records (booked fee ÷ first fee viewed) and (minutes from first view to booking). Their belief is a fading running mean. So a bot that always raises teaches drivers to wait. A repost at a higher fee also counts as a raise.
- **Drops.** A driver can drop a booking. The longer they hold it, and the thinner the fee's margin over their cost, the likelier a drop. A driver who dropped comes back only at a higher fee.
- **Chaining.** A driver already on one of our gigs can do another nearby cheaply, paying only the extra time and tickets. We can see where our drivers are while they work our gigs.

**Lateness and score.**
- `deadline_close` fires 3 hours before `lastPickupAt` if an order has no driver.
- Late refunds: ≤2 h late = 10% of the price back; 2–24 h = 25%; up to 2 business days = 50%; later = 100%.
- Undelivered at the end of the world (Wednesday 22:00 of the next week) = a penalty of 2× the price.
- **Score = gross margin**: revenue minus fees, refunds and fines.
- **Hard rule: at least 90% of won orders on time, or the team is not ranked.**

**Other rules.**
- Premium car without an experienced driver: €150 fine.
- Electric car under 30% charge on a route over 200 km without a charging stop: €100 fine.
- Failed visit (car not ready, site closed, wrong licence, no plates): half the car's share of the fee, at least €25.

**Map.** 30 places, with road km and minutes for every pair. Most drivers live in the Helsinki area (~420 within 30 km), then Tampere (~110), then a long tail of 0–40 per town.

## Practice and the final

- **Practice worlds** are deterministic given a seed and our actions, and only move when we call `advance`. `fork` copies a world, with the same future random draws, at the current minute. We can hold 8 unfinished worlds; one level 8 week takes about 50–90 s over the network.
- **The final** is one secret level 8 week in real time: about 34 minutes in total, about 4.5 real seconds per quote window, and at most 20 actions/s. Everything must run in plain Python with no per-decision LLM calls.

**Jury.** The top 10 by final margin pitch to a jury, which scores elegance, clarity, creativity and robustness. So prefer ideas that are simple, explainable, and can be switched on and off to show their effect.

## What our bot does now

The bot subclasses the kit's starter, which handles restarts, a regex note reader, reposting after failed visits and expired gigs, and steep fees after `deadline_close`.

**Quoting.**
- price = list × `mult` × option factor (same_day 1.15, next_day 1.05, within_3_days 1.0).
- `mult` starts at 1.25 and moves after every won or lost quote towards a target win rate of 0.4, clamped to [1.0, 1.6].
- **Global congestion surcharge:** +0.02 per car without a driver beyond 10.
- **Declines:** pickups with fewer than N drivers living within 30 km.

**Fees.** We post each order immediately. The schedule opens at `fee_open` × typical fee (best so far: 1.0) and rises linearly in 6 steps to `fee_cap` (1.8) by `lastPickupAt` − 3 h. After `deadline_close` it goes to 2.0–3.0×.

**Switches written but not yet tested:**
- an adaptive opening fee that aims for 50% of bookings at the first step
- trust-based price uplift per dealer
- an expected-profit filter
- a minimum time slack per option
- local congestion pricing per pickup area

## Results so far (level 8, our own fixed seeds)

| Version | Mean margin/week | Weeks ranked (≥90% on time) |
|---|---|---|
| Kit starter (quotes list, opens at typical fee) | about −€70,000 | 0 |
| v1 (fee open 1.25, target win 0.55) | −€6,086 | 8/16 |
| Fee open 1.0, cap 1.8 | €152 | 10/16 |
| + target win 0.4 | **€2,449** | 13/16 |

The **practice leaderboard** (the same 5 secret level 8 weeks for every team) shows:
- #1 at **€14,678/week**: 98% on time, about 300 orders a week, so about €49 margin per order.
- The organisers' best bot at €14,358.
- 10th place at about €10,200.

We win about 350–400 orders a week at about €100 revenue each, with roughly €0–7 margin per order.

**What the data shows:**
1. **78% of gigs book at the opening fee, median 9 minutes after posting.** So we overpay: the opening fee is above many drivers' reservation price.
2. **Profit by drive length.** Drives under ~35 road minutes are very profitable. Drives over ~3 h lose heavily, with about 14% late and fees about 1.5× typical.
3. **Profit by pickup supply.** Pickups with ≤34 drivers living nearby lose money; pickups in the Helsinki area make money.
4. **Profit by option.** At our current factors, same_day orders made money while next_day and within_3_days lost.
5. **Lateness in a failing week (86% on time).**
   - Most late orders were same_day cars won on Friday 10:00–13:00, many from one yard (an unannounced bulk order of 30–40 cars). Their gigs were never booked before their windows closed.
   - The rest were long northbound lanes (to Rovaniemi or Kemi) with no driver until after the deadline.
6. Drops: about 10% of bookings.

## What I want from you

Design the decision logic that closes the gap from ~€2.5k to €14k+ a week while staying at ≥95% on time on every week. Cover:

1. **Quoting as an optimisation.**
   - The formula for choosing which options to quote and at what price, given an estimate of our cost to deliver and a win-probability model learned online from won/lost data only. Include the right model for censored won/lost data, how to share strength across lanes, dealers and days, and how to detect and react to the price-war and outage days quickly.
   - How to account for the competitor cutting prices where we win too often, and for dealer trust making on-time deliveries worth more later.
2. **Cost-to-deliver estimation.**
   - How to estimate, per request and before quoting, the fee a car will need and its probability of being late. Use the driver roster (homes, licences), the map, the time of day and week, our current commitments (drivers already near the pickup or delivery), and what we learn during the week from views, bookings and drops.
   - Include an opportunity-cost or shadow-price term for scarce drivers in each area, so we stop winning cars that crowd out better ones.
3. **Fee schedule design under drivers who learn.**
   - The opening fee and the shape of the raises, given that drivers learn (booked fee ÷ first fee) and minutes-to-booking from us and wait accordingly.
   - Is a flat fee better than a rising one? Should we have one rising pattern only for urgent orders? When should we use direct offers instead, and to whom?
   - Think about this as a repeated game with learners, and say what equilibrium we want them to learn.
4. **Batching and chaining.** When to combine cars into one multi-car gig (same yard, return legs) and when to target drivers who will be near a pickup after our earlier gigs. How to do this greedily within the time limits.
5. **Risk control for the 90% rule.** A policy that keeps us safely ranked on bad weeks (bulk orders, flu, price war, Friday afternoons, towns with no drivers). Examples: a per-area capacity budget, a forecast of our on-time share, or rescue rules for when to pay any fee.
6. **Fork-based experiments.** How to use deterministic practice worlds and `fork` offline to learn things we can't observe directly, for example the shared part of the lane factors, or drivers' reservation fees, and turn that into tables or priors for the final.

For each idea, give:
- the maths or algorithm, written so we can implement it
- Python-like pseudocode, using hooks we already have: `quote(request)`, `fees_for(order, cars)`, `handle(event)`, plus `self.orders`, `self.requests`, `self.booked`, a roster of drivers, and a road-minutes table
- the expected effect on margin and on-time share, with your reasoning
- how to measure it on our benchmark (a seeds × with/without design)
- the main way it could fail

Finish with a **ranked build order**: what to build first for the biggest gain per hour of work. We have about 30 hours until the final.

Where the rules above leave something unknown (exact functional forms, distributions), say so, and propose how to estimate it from practice data rather than guessing a constant.
