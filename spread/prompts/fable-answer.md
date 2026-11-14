# Decision logic for the Spread bot: design, pseudocode and build order

Scope: this answers `prompts/fable-strategy.md`. Pseudocode targets `EvilDesk` in `bot.py` (hooks `quote`, `fees_for`, `handle`, state `self.orders`, `self.requests`, `self.booked`, `self.leg_gigs`, `self.posts`, `self.near`, `self.close`, `self.minutes`, `self.urgent`, `self.outbox`). Nothing here was run against the server; the numbers in section 0 come from the four reveal folders already in `logs/`, and every expected gain is an estimate to be confirmed on the benchmark.

---

## 0. What the existing logs already say

I read the four reveals in `logs/` (three weeks of our bot with different parameters, one week of the kit starter). Three worlds is a small sample and the parameters differed, so treat these as leads, not facts.

| Finding | Evidence (our three weeks) | Consequence |
|---|---|---|
| **The fee ladder creeps overnight.** 19–22% of gigs book on a later day than they were posted, at 1.28–1.42× their opening fee. Gigs that book within 15 minutes pay exactly 1.00×. | `booked on later day`: n=86/70 of ~380, mean booked÷open 1.28 / 1.39; `06–09h` next morning: 1.27 / 1.42 | `fees_for` spreads its 6 steps evenly over clock time to `lastPickupAt − 3h`. An order won at 16:00 has climbed to about 1.6× by 07:00, when the morning drivers first look. Nobody saw the lower steps. This is most of why `next_day` loses and why long drives pay 1.5×. |
| **We pay 1.17–1.48× typical on average**, the top teams must pay under 1.0×. | fee÷ref 1.45, 1.17, 1.48 | The fee side is the larger half of the gap. |
| **Tight slack is poison.** Orders won with 3–6 h between winning and `lastPickupAt`: fee÷ref 1.56–2.01, 12–38% late, −€11 to −€30 each. | `slack_h = 1` bucket, 25–48 orders a week | Price slack explicitly, or decline. |
| **Drives ≥ 180 road minutes**: 9–30% late, −€31 and −€73 per order in two of three weeks (71–108 orders). | `drive = 3` bucket | Needs a real cost estimate, not a uniform multiplier. |
| **Delivery-side supply predicts cost better than pickup-side.** Deliveries into places with >100 drivers within 30 km: fee÷ref 1.05–1.36 and the fewest late in all three weeks. Deliveries into places with ≤10: worst in all three (1.26–1.70). Pickup-side counts flip sign between worlds (in one week the ≤10 bucket was the *best*, n=125). | `near delivery bucket` vs `near pickup bucket` | The current `min_drivers` rule on the pickup is the wrong feature. The driver's expensive leg is the trip home from the delivery. |
| **Short drives have list ÷ typical ≈ 1.65**, the rest ≈ 1.0–1.08. | `drive = 0` bucket | Same ratio-to-list on every lane leaves the best lanes under-won and the worst over-won. |
| **The win curve against ratio-to-list is flat**: 60% at 1.2×, 50% at 1.5×, 33% at 1.8× in one week. | `win by min-ratio bin` | Thresholds differ a lot between lanes and dealers. A single multiplier wins the lanes where the competitor is dear, which are the hard lanes: a winner's curse. |
| **Monday is given away.** Price÷list on Monday 1.16–1.26, later days 1.33–1.60. | `day` table | Start from the published prior (1.26–1.54×), not from 1.25. |
| **Four dealers send ~60% of requests** (D01: 250–370 of ~1,040; 40 dealers in all). | dealer counts | The 25-order trust cap is reachable for the big four by Tuesday. Trust must be per dealer. |
| **Bulk orders carry a `batchId`** (largest batch 37–40 requests). | `requests.csv` | Detection is a counter, not inference. |
| ~370–460 distinct drivers view our gigs per weekday, of ~800 on the roster. | `views.csv` | About half the roster is active on a day; views identify who. |

Target arithmetic. Our best week: 356 orders, price ≈ 1.37× typical, fee ≈ 1.17×, other costs 0.04× → 0.16 × €75 ≈ €12 an order. Leader: €49 an order ≈ 0.65× typical. That needs roughly **+0.2 on price** (per-dealer trust, per-lane pricing, more short lanes) **and −0.25 on fee** (no overnight creep, area-specific opening, selection toward cheap deliveries, no rescue overpay), at 300 orders rather than 380.

---

## 1. Quoting as an optimisation

### 1.1 One formula

For request *i*, option *k*, price `p = r · L_k` (`L_k` = list price):

```
EV_k(r) = P_win_k(r) · ( r·L_k − C_k )
C_k     = fee_hat_k                                  # section 2
        + p_late_k · (0.25·1.4·L_k + rho + trust_loss_d)   # refund, ranking risk, trust halving
        + lambda_area                                # shadow price of local drivers, section 2.3
        − (1 − p_late_k) · (trust_gain_d + 0.07·rho) # an on-time order is an asset
quote r_k* = argmax over a grid r ∈ {0.90, 0.95, …, 2.40}
```

A grid search of 31 points is exact enough, has no failure modes and makes the "falls quickly above the competitor" kink harmless.

Sanity check of what it does (median threshold 1.40× list, scale s = 0.2):

| Cost ÷ list | Optimal ratio | Win probability | Today (uniform 1.35×) |
|---|---|---|---|
| 0.6 (short lane) | ≈1.25 | ≈64% | 55%, under-won |
| 1.0 | ≈1.50 | ≈41% | 55%, thin margin |
| 1.3 (long, bad delivery) | ≈1.75 | ≈25% | 55%, loss |

So the same formula wins more of the cheap cars, fewer of the dear ones, and replaces `min_drivers`, `max_minutes`, `min_margin`, `same_day`/`next_day` factors and both congestion surcharges with one number each: a cost.

### 1.2 Win-probability model for won/lost data

Each quote reveals only whether the dealer's threshold was above or below our price. That is current-status (interval-censored) data, and the likelihood of a threshold model is a binary regression on `ln r`:

```
P_win = sigmoid( (theta − ln r) / s )
theta = M                      # market level today = world level + day factor   (grid filter)
      + LANE[(a,b)]            # shared-across-worlds lane part                   (offline table, sec. 6)
      + A_pick[a] + A_del[b]   # this world's lane part                           (online, shrunk)
      + A_dealer[d]            # dealer sensitivity + competitor's reaction to us (online, shrunk, forgetting)
      + ln(1 + 0.01·trust[d])  # KNOWN from the rules: coefficient fixed at 1
      + KIND[k]                # speed value of the option                        (offline table)
      − 0.223·war − (−0.262)·outage_here                                        # event hypotheses
```

- **Scale `s`.** A pooled fit on our logs gives s ≈ 0.13 (with world-day intercepts) to 0.30 (without). Both are biased because the multiplier controller raises prices after wins. Start at **0.20** and refit from the randomised weeks of section 6.
- **Market level `M`: an exact grid Bayes filter.** The rules publish the prior: world level uniform on [ln 1.26, ln 1.54]. Hold a probability vector over `M ∈ [ln 1.0, ln 2.0]` in steps of 0.02 and multiply by the likelihood of each outcome. No gradient steps, no learning rate, correct for censored data, 50 multiplications per outcome.
- **Price war as a second hypothesis.** Keep the grid twice: `p[0][M]` (normal day) and `p[1][M]` (war day, likelihood uses `M − 0.223` between 08:00 and 18:00). Each midnight: marginalise over the hypothesis, convolve `M` with the day kernel `N(0, σ_day²)` (start σ_day = 0.06, estimate in sec. 6), and split with prior `π = 1/(working days left)` until a war has been seen (posterior > 0.9 at 18:00), then π = 0. With ~20 quotes an hour the posterior passes 0.9 within 30–45 minutes of the first busy hour. The reaction needs no special rule: the optimiser re-solves with thresholds 20% lower, so we keep bidding only where `C/L` is small and sit out the rest. A win-rate controller instead chases the war down for a day and climbs back for another.
- **Lane, place and dealer offsets: assumed-density filtering**, which is online logistic regression with a variance per parameter. It gives partial pooling for free: a group with few observations stays near its prior.

```python
def adf_update(off, var, key, y, P, s, share):
    # y = 1 won, 0 lost; P = predicted win probability; share = this group's part of the gradient
    v = var.get(key, V0)
    off[key] = off.get(key, 0.0) + share * v * (y - P) / s
    var[key] = v / (1.0 + v * P * (1 - P) / (s * s))
```

  Priors: `V0 = 0.10²` for places, `0.08²` for dealers. Each midnight add `0.03²` to every dealer variance (forgetting), because the competitor re-prices per dealer every morning in response to our wins.
- **Outage.** For each candidate centre `c` (30 places) keep a log-likelihood ratio over today's outcomes whose dealer site lies within 80 km of `c`: `LLR[c] += ln P(y | theta + 0.262) − ln P(y | theta)`. When `max LLR > 3`, add +0.262 to `theta` for that region until 18:00. Whether "dealers there" means the pickup site or the delivery site is not stated: test both in the fork data and keep the one with the higher likelihood. Detection needs some quotes above our usual price, which the jitter below supplies.
- **Exploration.** Multiply every quote by a deterministic jitter `exp(0.06·u)`, `u ∈ {−1, 0, +1}` from a hash of the request id. This costs under 1% of expected value (the EV curve is flat at its top), identifies `s` and the offsets, and supplies the high probes that detect an outage.

### 1.3 Several options in one quote

The dealer picks among our options and the competitor's. The exact choice rule is hidden, so use the rule that is safe under any choice model: **never let the dealer choose an option on which we earn less.**

1. Solve `r_k*` and `EV_k*` for every option separately (with `KIND[k]` and each option's own cost and lateness).
2. Let `k°` be the option with the highest `EV`. Its margin is `m° = r_k°·L_k° − C_k°`.
3. Quote `k°` at its optimum. Quote every other option with `EV_k > 0` at `max(r_k*·L_k, C_k + m°)`. Options with `EV_k ≤ 0` or `p_late_k > p_max` get the decline price.

Estimate `KIND[k]` offline from the fork ladder (sec. 6, E1), quoting one option per fork.

### 1.4 Trust as an investment, the competitor's reaction as a cost

- **Known uplift.** `ln(1 + 0.01·trust[d])` enters `theta` with coefficient 1. The bot already counts `self.trust`. This alone turns the blended multiplier into per-dealer prices: D01 at +25% from Tuesday, a new dealer at +0%.
- **Value of the next on-time order to dealer `d`** (while `trust[d] < 25`):
  `trust_gain_d = 0.01 · R_d(t)`, where `R_d(t)` = expected revenue we will still win from `d` after this order is delivered = `rate_d · hours_left_after_delivery · win_rate · mean_price`. Estimate `rate_d` online as requests so far ÷ request-hours so far. Order of magnitude on Monday: D01 ≈ €60–80, D02–D04 ≈ €30, a small dealer ≈ €5. So on Monday the optimiser quotes the big dealers' safe `same_day` cars noticeably lower, reaches the cap a day or more earlier, and stops by itself when the count is 25 or the week is short.
- **Cost of a late order to dealer `d`**: `trust_loss_d = 0.01 · (trust[d] − trust[d]//2) · R_d(t)`. For D01 mid-week that is hundreds of euros, far more than the refund. It goes into `C_k` through `p_late_k`, so risky cars for big dealers are priced up or declined, and risky cars are taken, if at all, from dealers with no trust to lose.
- **Competitor's reaction.** It lowers its prices for a dealer where we won "most" recent requests. `A_dealer[d]` with forgetting tracks the effect. To avoid causing it, add a soft penalty when our recent share at a dealer is high: `C_k += kappa · L_k · max(0, share_d − 0.5)`, with `share_d` over that dealer's last 20 decided requests and `kappa = 0.2` as a starting value. Measure the true step in forks (sec. 6, E1c) before trusting the constant.

### 1.5 Pseudocode

```python
GRID_R = [0.90 + 0.05 * i for i in range(31)]

def quote(self, request):
    self.requests[request["id"]] = request
    d, legs = request["dealerId"], request["legs"]
    a, b = legs[0]["pickup"]["placeId"], legs[-1]["delivery"]["placeId"]
    best, cand = None, {}
    for opt in request["options"]:
        k, L = opt["kind"], opt["listPriceCents"]
        cost, p_late = self.cost_to_deliver(request, opt)          # section 2
        theta = self.theta(request, k, a, b, d)                    # 1.2, uses E[M] via p_win below
        ev, r = max((self.p_win(theta, r) * (r * L - cost), r) for r in GRID_R)
        cand[k] = (ev, r, L, cost, p_late)
        if best is None or ev > cand[best][0]:
            best = k
    prices, m0 = {}, cand[best][1] * cand[best][2] - cand[best][3]
    for k, (ev, r, L, cost, p_late) in cand.items():
        if ev <= 0 or p_late > self.p_max():                       # p_max tightens with rho, section 5
            prices[k] = int(L * self.p["decline_mult"])
        else:
            price = r * L if k == best else max(r * L, cost + m0)
            prices[k] = int(price * self.jitter(request["id"]) + 0.5)
    self.quoted[request["id"]] = prices
    self.pred[request["id"]] = {k: (self.theta(request, k, a, b, d), prices[k] / cand[k][2]) for k in cand}
    self.inflight[request["id"]] = (a, sum(self.p_win(*self.pred[request["id"]][k]) for k in cand
                                           if prices[k] < cand[k][2] * 4) )   # expected wins not yet decided
    self.outbox.append({"type": "quote", "requestId": request["id"], "prices": prices})

def p_win(self, theta_minus_M, r):
    # average the logistic over the market-level posterior (both hypotheses)
    return sum(w * sigmoid((theta_minus_M + m - 0.223 * h * self.war_hours() - math.log(r)) / self.s)
               for h in (0, 1) for m, w in self.grid[h].items())

def learn(self, won, request_id, option=None):
    self.inflight.pop(request_id, None)
    pred = self.pred.pop(request_id, None)
    if not pred: return
    # one observation per request: the option won, or (lost) the option we priced lowest against list
    k = option or min(pred, key=lambda k: pred[k][1])
    if pred[k][1] >= 4: return                                     # a decline teaches nothing
    th, r = pred[k]; y = 1 if won else 0
    P = self.p_win(th, r)
    for h in (0, 1):                                               # exact Bayes on the market grid
        for m in self.grid[h]:
            q = sigmoid((th + m - 0.223 * h * self.war_hours() - math.log(r)) / self.s)
            self.grid[h][m] *= q if won else 1 - q
    normalise(self.grid)
    req = self.requests[request_id]
    a, b = req["legs"][0]["pickup"]["placeId"], req["legs"][-1]["delivery"]["placeId"]
    for off, var, key in ((self.A_pick, self.V_pick, a), (self.A_del, self.V_del, b),
                          (self.A_dealer, self.V_dealer, req["dealerId"])):
        adf_update(off, var, key, y, P, self.s, 1 / 3)
    self.outage_update(req, y, th, r)
```

`handle` already calls `learn(True, order_id)` / `learn(False, requestId)`; pass `event["order"]["option"]` on a win.

**Expected effect.** +€3k to +€5k a week from the formula with a table-based cost (sec. 2), of which roughly €1k is Monday (starting at the prior instead of 1.25×), plus +€1.5k to +€3k from per-dealer trust and place offsets. On-time share rises because tight-slack and bad-delivery cars are now priced at their real cost. **Measure:** 16 fixed seeds, `--params '{"pricing":"ev"}'` against the current best; then switch on `trust`, `offsets`, `war`, `outage` one at a time on the same seeds. Leading indicators that are less noisy than margin: price÷list by day, win rate by `C/L` tercile, Brier score of predicted win probability. **Main failure mode:** the cost estimate is biased low for a class of cars and the optimiser, unlike a uniform multiplier, concentrates on exactly that class. Guard with the online residual in 2.2 and a floor `C_k ≥ 0.8·ref`.

---

## 2. Cost to deliver

### 2.1 Fee estimate

```
fee_hat = ref · phi,   ln phi = K                 # this world's fee level today (grid filter, as M)
                              + G[bucket]         # offline table
                              + B_del[b] + B_pick[a]   # online residuals, shrunk
bucket = (drive band: <35 / 35–90 / 90–180 / 180–300 / >300 road minutes,
          slack band at posting: <4h / 4–8h / >8h same day / overnight,
          delivery supply band, pickup supply band)
```

- **`G[bucket]` now**: median booked fee ÷ typical by bucket from the reveals we have, after the ladder fix of section 3 has been run on the bench seeds (the current fees are inflated by the overnight creep). **`G[bucket]` properly**: from the flat-fee ladder forks (sec. 6, E2), which measure the reservation fee instead of what our ladder happened to pay.
- **Supply bands, measured, not from the roster alone.** The roster count `self.near` flipped sign between worlds. Use *active* supply: `active[p]` = distinct drivers who viewed any of our gigs in the last 24 h and whose home is within 30 km of `p` (homes from the roster). Before any views on Monday use `0.5 · self.near[p]`. This also captures the flu day and the town factors.
- **Our own drivers.** `inbound[p]` = booked gigs of ours whose last delivery is within 30 km of `p` and ends before this car's last pickup. Count each as 3 active drivers on the pickup side; they are the cheapest drivers for this car (sec. 4).
- **Online residuals.** On every `gig_booked`: `res = ln(fee / ref) − ln phi_predicted_at_quote`; update `K` with step 0.05 and `B_del[b]`, `B_pick[a]` with shrinkage `n/(n+5)`. On every gig that reaches its first raise unbooked, feed `res = +0.15` (it needed more than we thought).

### 2.2 Probability of being late

Lookup table from practice data, the same buckets, value = share of orders late; the logs give the first version today:

| | slack ≥ 6 h at win | slack 3–6 h |
|---|---|---|
| drive < 180 min, delivery supply high | ≈ 2–4% | ≈ 10% |
| drive < 180 min, delivery supply low | ≈ 6–8% | ≈ 20% |
| drive ≥ 180 min | ≈ 9–15% (30% in a bad week) | ≈ 30–40% |

Multiply by a load factor `1 + 0.5·max(0, U_a − 3)` (2.3) and by 1.5 on a Friday for `same_day` (a miss rolls to Monday: more refund, Saturday short hours). Compute slack before winning as

```
latest_pickup = min(deadline − drive − charging, pickup site closing on the deadline day)
earliest      = max(respondBy, pickup window from, time read from the note)
slack         = latest_pickup − earliest_bookable     # in market minutes, 07:00–20:00 only
```

The current `slack = deadline − now − drive` ignores site hours, ready times and nights.

### 2.3 Shadow price of local drivers

Capacity is used when a driver near pickup area `a` takes our car instead of another of ours. Two observable signals, no hidden constants:

```
U_a = number of our cars with pickup within 30 km of a that have been open (unbooked)
      for more than 30 market minutes
    + sum of P_win over our undecided quotes with pickup in a          # self.inflight
lambda_a = m_bar · clip((U_a − u_free) / u_span, 0, 2)
```

`m_bar` = our running mean margin per order (the value of the order that gets crowded out), `u_free = 2`, `u_span = 4` to start. Fit the real slope offline: regress realised (fee ÷ ref) of each order on `U_a` at the minute it was posted; the coefficient times `ref` is the externality per queued car.

The in-flight term matters most. Today 30 simultaneous requests from one yard are each quoted as if they were alone; with it, the fifth quote already sees four expected wins ahead of it and prices up, and the fifteenth declines. That is the bulk-order failure of the 86% week.

```python
def cost_to_deliver(self, request, opt):
    legs = request["legs"]; a = legs[0]["pickup"]["placeId"]; b = legs[-1]["delivery"]["placeId"]
    ref, L, d = request["referenceFeeCents"], opt["listPriceCents"], request["dealerId"]
    slack = self.slack(request, opt)
    bucket = self.bucket(request, slack)
    phi = math.exp(self.K + self.G.get(bucket, 0.1) + self.B_del.get(b, 0) + self.B_pick.get(a, 0))
    phi *= self.pair_discount(request, opt)                 # section 4: return leg or inbound driver, else 1
    U = self.queue(a)
    p_late = min(0.95, self.PL.get(bucket, 0.08) * (1 + 0.5 * max(0, U - 3)) * self.friday(opt))
    lam = self.m_bar * min(2.0, max(0.0, (U - 2) / 4))
    cost = max(0.8 * ref, ref * phi) + 0.03 * ref           # 3% for failed visits, drops, waiting
    cost += p_late * (0.35 * L + self.rho + self.trust_loss(d))
    cost += lam + self.share_penalty(d, L)
    cost -= (1 - p_late) * (self.trust_gain(d, opt) + 0.07 * self.rho)
    return cost, p_late
```

**Expected effect.** Counted inside the +€3–5k of section 1 (the formula is only as good as this cost); the in-flight term and the slack fix are worth most of the on-time gain (86% week → 93–95%). **Measure:** calibration plots on the bench weeks: predicted `phi` against realised fee÷ref by decile, predicted `p_late` against realised late share. **Main failure mode:** buckets with few observations. Shrink each cell toward its drive-band mean with weight `n/(n+20)`.

---

## 3. Fee schedules when drivers learn

### 3.1 The equilibrium to aim for

A driver waits only if they expect (a) a raise that (b) arrives before someone else books. Their belief is a running mean of *booked fee ÷ first fee viewed* and of *minutes from first view to booking*, learned only from orders that got booked and that they viewed.

The belief we want is **ratio 1.00, minutes small**: "this desk posts its price; it does not get better; the good ones go in minutes". Under that belief a driver's best response is to book at once whenever the fee covers them, which is exactly the posted-price outcome, and the first-wave booking share stops depending on what they think of us. Every order that books after a raise moves the belief away from this, for every driver who viewed it. So:

1. **Flat is the default.** One step, held for most of the available time.
2. **Raises are rare, late and in few large steps**, placed where the rules say waiting is weakest: close to the pickup ("they wait less for a raise"). A late jump of +25% on 10% of orders teaches a mean ratio of about 1.03. A smooth ladder on every order that is not booked in an hour teaches 1.10 and long minutes.
3. **Before any raise, make direct offers at the current fee** to the drivers who viewed and did not book (3.4). A direct offer is take-it-or-leave-it by rule: the driver "takes it when the fee pays", with no waiting logic. A booking made that way records ratio 1.00.
4. **Never raise while nobody is looking.** No steps between 20:00 and 07:30. A raise at night only raises the first fee the morning crowd sees, and it does not even count as "first fee viewed" for the ones who looked the evening before, so it teaches ratio > 1 as well.

A flat fee is not always cheaper per gig (a ladder discovers the price on the 20% that do not book), but it is cheaper per week because of what the ladder teaches and because of the overnight creep.

### 3.2 Opening fee: by area, not one number

With `n` active drivers getting the notification and reservation fees distributed as `F`, the first wave books with probability `1 − (1 − F(f))^n`. With n ≈ 60–120 around Helsinki the lowest reservation is far below typical; with n ≈ 3 it is not. One global `fee_open` therefore overpays in dense areas (78% book at the opening fee in a median of 9 minutes) and under-opens in thin ones. Keep one opening multiple per `(delivery supply band, drive band)` plus a global level:

```
ln f0 = Kf + O[bucket]
on a gig that books at its first step within 30 market minutes:  both −= eta · (1 − q)
on a gig that reaches its first raise (or 45 market min) unbooked: both += eta · q
```

`q` is the share we want booking at the opening fee: **0.6** when slack > 8 h, **0.75** at 4–8 h, **0.9** under 4 h. `eta = 0.04` for the bucket, `0.01` for the global level, bounds [0.55, 1.5]. A week gives only ~40 updates per bucket, so the **starting values must come from practice** (E2 in sec. 6), and the online rule is a correction. This generalises the existing `fee_adapt` switch.

Count drops in the experiment: a fee that "only just pays" is dropped more often, and a driver who dropped comes back only for more. The quantity to minimise is total fee paid per delivered car plus late costs, not the booked fee.

### 3.3 Shape

```python
MKT_OPEN, MKT_CLOSE = 7 * HOUR + 30, 20 * HOUR

def fees_for(self, order, cars):
    req = self.requests[order["id"]]
    ref = req["referenceFeeCents"] * cars / len(order["legs"])
    now, T = self.now, order["lastPickupAt"] - 3 * HOUR          # the climb must be over by the warning
    if order["id"] in self.past_saving:                           # cannot be on time any more: 5.3
        return [{"at": now, "feeCents": int(ref * self.late_flat(order))}]
    f0  = self.open_mult(order)                                   # 3.2
    cap = self.cap_mult(order, ref)                               # willingness to pay, 5.2
    if order["id"] in self.urgent:
        steps = [(now, max(f0, 0.75 * cap)), (now + 30, cap)]     # two steps, not five
    else:
        n, climb = 3, 4 * HOUR                                    # 3 jumps in the last 4 market hours
        start = max(mkt_add(now, 45), mkt_back(T, climb))         # flat until then, never at night
        steps = [(now, f0)] + [(mkt_add(start, climb * i // n), f0 + (cap - f0) * (i + 1) / n)
                               for i in range(n) if mkt_add(start, climb * i // n) < T + 2 * HOUR]
    out, last = [], 0
    for at, m in steps:
        fee = max(last, int(ref * m + 0.5), 1)
        if out and at <= out[-1]["at"]: out[-1] = {"at": at, "feeCents": fee}
        else: out.append({"at": at, "feeCents": fee})
        last = fee
    return out
```

`mkt_add(t, m)` moves `m` minutes forward counting only 07:30–20:00 on Monday to Saturday; `mkt_back` does the reverse. For a `next_day` car won at 16:00 with last pickup tomorrow 15:00, the fee is flat at `f0` all evening, all night and until 08:00, then three jumps by 12:00. Today the same car shows about 1.6× at 07:00.

### 3.4 Direct offers

Track viewers and activity in `handle`:

```python
elif event["kind"] == "gig_viewed":
    self.viewers.setdefault(event["gigId"], []).append(event["driverId"])
    self.seen_today[event["driverId"]] = event["at"]              # this driver works today
```

Three uses, in order of value:

1. **Offer before raise.** Ten minutes before each scheduled jump, send up to 3 offers at the *current* fee to that gig's viewers (most recent first, seen today, licence and audience fit, fewer than 3 offers today). This converts the waiters without teaching a raise.
2. **Drivers who live at the delivery.** The notification goes only to homes within 30 km of the pickup, but the cheapest driver for A→B is often one who lives near B: no dear same-day ticket home. For any gig whose drive is ≥ 90 minutes and that is still open after 30 market minutes, offer to drivers in `seen_today` with home within 30 km of the *last delivery*, at 0.85× the app fee. Test in E4 whether such drivers really accept lower; the data in section 0 says deliveries into driver towns are the cheapest, which is the same effect seen through the app.
3. **Our own drivers downstream** (sec. 4): a driver who will finish one of our gigs near this pickup.

Offers also serve the rescue at `deadline_close` (5.2). Send via `self.outbox.append({"type": "offer", "gigId": g, "driverId": d, "feeCents": fee})`; mark the driver's daily count and the gig's open offers; clear on `offer_answered`.

Timed actions need a clock tick. In `play_practice`, cap each `advance` at `min(ends_at, midnight, desk.next_timer())` and call `desk.tick()` after the events; in the final the stream's `idle=1.0` already gives a tick. Keep timers in a heap of `(minute, kind, gig_or_order_id)`.

**Expected effect.** Ladder clock fix: about 20% of gigs stop paying +0.3× typical → **+€1.5k to +€3k a week**, on the first hour of work. Area opening fee: if dense-area gigs open 10–15% lower → +€1.5k to +€2.5k. Offer-before-raise: +€0.3k to +€1k and a slower drift of driver beliefs. **Measure:** same seeds, switches `fee_clock`, `open_by_area`, `offer_before_raise`. Report fee÷typical for gigs booked on a later day, share booked at the first step by weekday (if Thursday and Friday show a lower share than Monday at the same opening multiple, drivers have learned to wait), drops per booking, late share. **Main failure mode:** flat-until-late leaves too little time to climb for tight-slack cars. That is why `q` and the hold shorten with slack, and why tight slack is priced in section 2.

One thing to test, not assume: whether a `next_day` or `within_3_days` car should be posted at once or held until the evening before / 07:30 on the day it can be driven. Posting at once spends the single per-order notification on a day when most drivers cannot commit ("most know only the next day"), and a gig that sits ages, which the rules say makes drivers wait more. Holding loses the cheap evening drivers who could take it today. Run it as a switch `defer_post` on the bench seeds.

---

## 4. Batching and chaining

A multi-car gig is a sequence (deliver car 1, drive to car 2, deliver it), at most 12 road hours including the links. What it saves is a driver's dear trip home and a second driver in a thin area. Three patterns, by value per hour of work:

**4.1 Chain by direct offer (cheap to build, no bookkeeping risk).** On `gig_booked`, `picked_up` and `delivered` keep `self.driver_plan[driverId] = (place of last delivery, eta)`, with `eta = pickup time + road minutes` or the delivery time itself. In `tick()`:

```python
for gid, post in self.open_gigs():                       # ours, unbooked, not combined
    p0 = self.place_of(post["stops"][0]); start_by = self.last_pickup(gid)
    for drv, (place, eta) in self.driver_plan.items():
        if place in self.close[p0] and eta + 20 <= start_by and self.can_offer(drv, gid):
            home_bonus = 0.75 if self.home[drv] in self.close[self.place_of(post["stops"][-1])] else 0.9
            self.offer(gid, drv, int(self.app_fee(gid) * home_bonus))
            break
```

Send the offer when the driver is 30–60 minutes from finishing, since an offer lives 10 minutes and a busy driver reads fewer. A gig that takes the driver back toward home is the one they accept cheaply. Also feed `inbound[p]` into the cost model (2.1) so we *win* the follow-on car in the first place: the competitor cannot see our driver arriving, we can.

**4.2 Return legs as one gig.** When an order is won (and at `tick`), look for an unbooked single-car order `q` such that `q.pickup ∈ close[o.delivery]` and `q.delivery ∈ close[o.pickup]` (or the same with the roles swapped):

```
total = min[o] + min[o.delivery → q.pickup] + min[q]  ≤ 720
feasible: o delivered by its deadline; q's pickup inside its window and site hours after that;
          q delivered by its deadline; both with ≥ 2 h spare
saving_est = 0.25 · (ref_o + ref_q)        # the dear ticket home, once; replace with E2/E4 numbers
```

If feasible: withdraw both singles, post one gig with stops `[o.pickup, o.delivery, q.pickup, q.delivery]` at `0.8 × (f_o + f_q)` flat, set a timer 60 market minutes ahead; if it is still open then, withdraw it and repost the singles (they keep their age and first-viewed fee, so do this only for orders with slack > 6 h). In the quote path, `pair_discount` returns ≈ 0.75 for a request that is the return of an order we hold unbooked: this is the signal "pairs with an order that you have", and it lets us price that car below the competitor at a profit.

Bookkeeping to respect in the starter: `carry()` already maps several orders' legs to one gig, but `repost()`, `raise_fees()` and `send_post_of()` assume one order per gig and call `fees_for(order, cars)`. Keep a `self.combined[gig_id] = [order ids]` map and build the schedule for a combined gig from the sum of the typical fees and the earliest `lastPickupAt`. On `order_cancelled` with outcome `withdrawn`, repost the partner.

**4.3 Same yard, several cars.** Without a car to bring back, a second car from the same yard only saves anything if the delivery places are close and the driver can get back cheaply. Do not build it for general use. For the **bulk order**, use it differently: quote the later options, win only what `U_a` allows, and spread the gigs over two or three mornings (`defer_post` by target day) so that the yard's 30 km of drivers are asked a few cars per morning, not thirty at once.

**Expected effect.** Chain offers +€1k to +€2k (it also converts cars at thin pickups from losses to wins); return legs +€0.5k to +€1.5k, depending on how many pairs a week has (count them offline in `requests.csv` first: if fewer than ~25 feasible pairs a week among orders we would win, skip it). **Measure:** switches `chain_offers`, `pair_gigs`; report offers sent / accepted, fee÷typical of chained gigs against the rest, late share of paired orders. **Main failure mode:** a combined gig that nobody takes ties up two cars; the 60-minute split-back and the slack condition bound that.

---

## 5. Risk control for the 90% rule

### 5.1 One dual variable: the price of lateness

Target 95% so that noise leaves room: `late ≤ 0.05·N`. The Lagrangian adds to each won order `rho · (p_late − 0.05)`: a risky car costs more, a safe car earns a credit. Safe cars matter because the rule is a ratio: at 88% with 300 orders we need 60 more on-time orders, and they can only be won before Friday 18:00.

```python
def update_risk(self):                                     # in tick(), every 30 market minutes
    N = late = 0; at_risk = 0.0
    for o in self.all_won.values():                        # includes delivered ones
        N += 1
        if o["late_known"]: late += 1
        elif not o["done"]: at_risk += self.p_late_now(o)
    S = 1 - (late + at_risk + 0.03 * 30) / (N + 30)        # 30 pseudo-orders at 3% steady Monday's noise
    self.S = S
    self.rho = min(60_000, max(0, int(10_000 * (0.96 - S) / 0.01)))   # cents: €100 per point under 96%

def p_late_now(self, o):
    if o["cannot_be_on_time"]: return 1.0
    if self.is_booked(o): return 0.04 if o["started"] else 0.08
    h = (o["lastPickupAt"] - self.now) / 60
    return 0.9 if h < 1 else 0.5 if h < 3 else 0.2 if h < 6 else 0.06

def p_max(self):                                           # hard gate used in quote()
    return 0.25 if self.S > 0.955 else 0.12 if self.S > 0.94 else 0.05
```

At S = 0.94, `rho` = €200: a car with 20% lateness risk carries +€30 of cost and is effectively declined; a car with 2% risk gets −€6 and is quoted cheaper. Below 0.94 only near-certain cars are quoted at all. Nothing else in the bot needs a "panic mode".

### 5.2 Rescue: what an on-time delivery is worth

At `deadline_close`, and at our own earlier amber point (unbooked 6 market hours before `lastPickupAt`), the most we should pay is

```
W = fee_normal + 0.25·price + trust_loss_d + rho·0.95
cap_mult = clip(W / ref, 1.4, 3.0)
```

So with a comfortable on-time share the cap is about 1.4–1.6×, and near the boundary it goes to 3×. At the amber point: send 3 direct offers (viewers of this gig, then drivers seen today living near the delivery, then near the pickup), and reprice to two steps (`0.75·cap` now, `cap` in 30 minutes). The rules warn that a high fee shortly before the pickup finds nobody, so the amber point, not the 3-hour warning, is where the money should go.

After a `gig_dropped` with less than 5 market hours of slack: treat as amber at once, and exclude the dropper from offers (they return only for more).

### 5.3 Stop paying once the deadline is lost

When `now + drive > deadline` for an unbooked order it will be late whatever we pay, yet today it stays in `self.urgent` and every repost goes out at 2–3× typical. Move it to `self.past_saving`, drop it from `self.urgent`, and reprice (a reprice may lower the fee) to a flat `late_flat ≈ max(1.0, f0)` with one jump timed 6 market hours before the next refund boundary (2 h late → 10%, 24 h → 25%, two business days → 50%). Each boundary is worth 15–25% of the price, about €15–30, never 1.5× typical.

### 5.4 Named bad weeks

| Event | Signal | Response |
|---|---|---|
| Bulk order | `batchId` count ≥ 6 within 20 minutes, or `U_a` jumping through in-flight wins | Automatic via `lambda_a` and `p_late` load factor; quote later options; stagger posting |
| Flu | views per new gig in its first 15 minutes at half the week's norm by 09:30; `K` rising | `K` and `active[p]` feed cost and `p_late`; `rho` rises through `S` |
| Price war | war hypothesis > 0.9 | Hold margin, win less; no change to fees |
| Friday `same_day` | weekday = Friday | `p_late` × 1.5; `slack ≥ 5 h` required after 10:00 |
| Town with no drivers | `active[b]` and `active[a]` both in the lowest band, no `inbound` | Cost and `p_late` from the table; usually declines itself |

**Expected effect.** Ranked on every bench seed with ≥ 94% on time (from 13/16); +€0.5k to +€1.5k from 5.3. The margin effect of 5.1 is near zero on good weeks by design. **Measure:** minimum and 10th percentile of on-time share over 16 seeds, count of unranked weeks, fees paid on orders that ended late. **Main failure mode:** `p_late_now` too optimistic, so `S` reacts late. Calibrate it from the bench weeks (predicted against realised by state), and keep the 30-pseudo-order prior.

---

## 6. Fork-based experiments

All of these run offline and produce JSON tables the final bot loads as priors. Each fork holds one of 8 slots, so run a base world plus up to 6 forks at a time, and delete each fork when read.

**E0. Randomised weeks (no forks, do first).** Play 6–8 seeds with the price ratio drawn uniformly from [1.05, 1.95] per request (hash of the id), independent of everything, and with the opening fee multiple drawn from {0.6, 0.75, 0.9, 1.05, 1.2} per order, flat for 60 market minutes. Losses in practice cost nothing. This removes the controller's bias from the win curve and gives the first reservation-fee curve. Fit `s`, the place effects and `G[bucket]` from these.

**E1. Price ladder: the competitor's price per request.** The base world plays the current bot. At each step that delivers price requests: fork 6 copies; in copy *j* quote every open request at ratio `r_j ∈ {1.1, 1.25, 1.4, 1.55, 1.7, 1.9}` on one option (rotate the option by request hash), advance the copy 15 minutes, read `order_won` / `order_lost`, delete it. The same future draws make the outcome a step function of the price, so each request yields a bracket for the dealer's threshold about 10% wide: almost uncensored data. About 18 calls per request step, 10–15k calls per week.
 - (a) Regress `ln threshold` on world, world-day, pickup effect, delivery effect, a spline in km, option kind, dealer and `ln(1 + 0.01·trust)`: the pickup and delivery effects that repeat across 4+ worlds are the shared lane part → `LANE[(a,b)] = u_a + v_b + g(km)`. The residual scale is `s`; the world-day effects give `σ_day`; the option effects give `KIND`.
 - (b) The war day and the outage region show up directly as a −0.22 and a +0.26 shift: confirm the sizes, and whether the outage keys on the pickup or the delivery place.
 - (c) Competitor reaction: compare a dealer's thresholds on the morning after we won 80% of its requests with a fork in which we won 20%. That gives the step size for `kappa` in 1.4.
 - Check first, on 20 requests, that outcomes are monotone in the ratio. If not, the draw is not shared between forks; the data is then 6 independent yes/no answers per request, still six times what a week gives, and the same regression applies as a logistic fit.

**E2. Fee ladder: reservation fees.** At `order_won` in the base world: fork 6 copies; copy *j* posts the gig flat at `{0.55, 0.7, 0.85, 1.0, 1.2, 1.5} × typical` (one step), advances 4 hours (or to `lastPickupAt − 3h`), and records booked or not, minutes to booking, the booker's home, and a drop if any. Output: the lowest flat multiple that books within 4 h, by bucket → `G[bucket]` and the opening table `O[bucket]`; time-to-book curves → the hold length; where bookers live relative to pickup and delivery → whether to target delivery-home drivers. About 18 calls per order; sample every third order.

**E3. Whole-week A/B on the same seeds (no forks).** `fee_clock` on/off, `defer_post` on/off, flat-then-jump against the linear ladder. For the learning effect compare Thursday–Friday first-step booking share at equal opening multiples.

**E4. Offer ladder.** For an open gig, in 6 forks send a direct offer to the same driver at 6 fees; repeat for three driver classes (home near pickup, home near delivery, our driver finishing nearby). Output: acceptance against fee÷typical by class → `home_bonus` and chain discounts in section 4.

**E5. Late-probability table.** No experiment needed: pool every bench week's orders with their state at winning (slack, drive, supply bands, `U_a`) and outcome.

Limits to remember: the final cannot be forked, a ranking run cannot be forked or revealed, and worlds differ in price level, day factors, town factors and half of each lane factor. So ship **priors with variances**, not constants, and let the online filters of sections 1–2 move them. A table that the online data contradicts should lose within a few dozen observations; `V0` sets exactly that.

---

## 7. Plumbing these ideas need (small, do once)

- `tick()` and a timer heap; cap `advance` at the next timer in `play_practice`.
- `gig_viewed` handling: `self.viewers`, `self.seen_today` (clear at midnight), `self.home` from the roster.
- A per-order record `self.all_won[order_id]` with price, typical fee, dealer, state, fees paid, late flag (from `ledger` lines), so `S`, `m_bar` and the calibration plots need no reveal.
- State after a restart in the final: the learners must be rebuilt in `rejoin`. Replay `history` through a light path that calls only `learn`, the fee residual updates, the trust counter and the view tracker, with `self.now` set to each event's minute. Keep `self.pred` reconstructible by recomputing `theta` from the stored quote, or accept losing the outcomes of the requests open at the restart.
- Every idea behind a `self.p[...]` switch, default off, so `bench.py` runs seeds × with/without. Use the 16 fixed seeds, report the paired mean difference with its standard error and the worst on-time share. Weekly margin differs by thousands of euros between seeds, so only paired comparisons mean anything; with 16 seeds a change under about €700 is noise unless the leading indicators agree.

---

## 8. Ranked build order (30 hours)

Gains are per week at level 8, relative to the €2.4k version; they overlap, so expect the sum to land at roughly half to two thirds of its face value: **about €9k–13k**, with the on-time share at 94–97%.

| # | Build | Hours | Expected gain | Why this rank |
|---|---|---|---|---|
| 1 | **Fee clock**: flat hold, 3 late jumps on market hours, nothing overnight (3.3) | 1 | +€1.5k–3k | Measured in our own logs; 20 lines in `fees_for` |
| 2 | **Stop paying once late** + rescue cap from willingness to pay (5.2, 5.3) | 1 | +€0.5k–1.5k | Removes 2–3× fees on orders already lost |
| 3 | **Plumbing**: tick, view tracking, per-order record, switches (7) | 1.5 | enables 5–11 | Everything after depends on it |
| 4 | **Correct slack + in-flight expected wins + late table as gates** (2.2, 2.3) | 2 | +€1k–3k, on-time to ≥ 94% | Fixes the unranked weeks (bulk, Friday, tight slack) |
| 5 | **E0 randomised weeks, start E1/E2 forks in the background** (6) | 2 + machine time | priors for 6–8 | Runs while we code; needs only item 3 |
| 6 | **EV pricing with the market-level grid filter and cost table**, start at the published prior, war hypothesis included (1.1–1.3, 2.1) | 4 | +€3k–5k | The core change: per-car price from cost and win curve |
| 7 | **Per-dealer trust term, trust gain/loss, place and dealer offsets** (1.2, 1.4) | 2 | +€1.5k–3k | Known functional form; four dealers are 60% of volume |
| 8 | **Opening fee by area** from E0/E2 with online correction (3.2) | 2 | +€1.5k–2.5k | Attacks the 78% that book at once |
| 9 | **Risk dual `rho`** and on-time forecast (5.1) | 1.5 | ≈ €0 on good weeks; keeps us ranked | Insurance for the single final week |
| 10 | **Direct offers**: before each raise, delivery-home drivers, our downstream drivers (3.4, 4.1) | 3 | +€1.5k–3k | Uses what the competitor cannot see |
| 11 | **Outage detection** (1.2) | 1.5 | +€0.3k–1k | One day, one region; cheap once offsets exist |
| 12 | **Return-leg gigs** (4.2), only if the offline pair count is ≥ 25 a week | 3 | +€0.5k–1.5k | Most bookkeeping risk; do last |
| — | Test finals, restart rehearsal, freezing parameters, one ranking round | 4 | — | Reserve; do not spend it on features |

Stop rules: after items 1–4 run one ranking round to see the level; freeze features 4 hours before the final and spend what is left on seeds, the restart path and the with/without table for the jury.

## 9. What stays unknown, and where it gets estimated

| Unknown | Starting value | Estimated from |
|---|---|---|
| Win-curve scale `s`, and whether it is steeper above the competitor's price | 0.20, symmetric | E0, E1(a); fit two slopes if E1 brackets show the kink |
| Day-factor spread `σ_day` | 0.06 | E1(a) world-day effects |
| Shared lane part | 0 | E1(a) across ≥ 4 worlds |
| Speed value per option | 0 | E1(a) option effects |
| Competitor's per-dealer step and what "most" means | `kappa` = 0.2 above a 50% share | E1(c) |
| Outage keyed on pickup or delivery site | pickup | E1(b) |
| Drivers' reservation fee by area and time | `G` from current logs after the clock fix | E2 |
| Whether delivery-home and downstream drivers accept less | 0.85 and 0.75–0.9 | E4 |
| Share of the roster active per day and place | 0.5 × roster count | views, online |
| How fast drivers' beliefs move | — | E3, Thursday–Friday first-step share |
| Post now or defer for later options | post now | E3 `defer_post` |
| Lateness probability by state | table in 2.2 | E5, every bench week |
