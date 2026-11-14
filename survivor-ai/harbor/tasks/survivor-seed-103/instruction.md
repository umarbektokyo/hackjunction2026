# Survivor: win the jury vote

You are player **`ash`** in an 8-player elimination game. The other seven players
(`bea`, `cyd`, `dex`, `eve`, `fin`, `gil`, `hal`) are computer-controlled. You play
only through the tools of the **`survivor`** MCP server. There is nothing to write to
disk and no code to produce: your score is recorded by the game server.

**Your goal: be one of the last two players and win the final jury vote.**

## How you are scored

| Outcome | Reward |
|---|---|
| You win the jury vote (1st place) | **1.0** |
| You reach the final two but lose the jury vote (2nd place) | 0.25 + 0.25 × (jury votes you received ÷ 6 jurors), i.e. 0.25 to 0.375 |
| You are voted out in round 6 (place 3 of 8) | 0.15 |
| You are voted out in round 5 (place 4 of 8) | 0.1 |
| You are voted out in round 4 (place 5 of 8) | 0.05 |
| You are voted out earlier | 0 |
| The game is not finished when you stop calling tools | 0, whatever your position |

**The game only advances when you call a tool.** Nothing happens in real time and
nobody acts while you are thinking, but if you stop calling tools the game stays
unfinished and scores 0. Keep playing until `get_state` reports
`"phase": "finished"`. If you are voted out, the remaining rounds are played out
immediately and the phase becomes `finished`; you are then done.
You have about 40 minutes in total.

## Structure of the game

The game has 6 rounds. Each round is a **discussion** followed by a **vote** that
eliminates exactly one player. After 6 eliminations the two remaining players are the
finalists and the 6 eliminated players form the **jury**.

### Discussion

- At the start of each round the living players are put in a random order (new each
  round). Players act one at a time in that order, and the order is repeated 4 times,
  so every living player gets **4 slots per round**.
- When it is your slot (`your_turn` is true, phase `discussion`) you must take exactly
  one slot action:
  - `propose_alliance(members)`
  - `request_promise(to, kind, target)`
  - `offer_promise(to, kind, target)`
  - `leave_alliance(alliance_id)`
  - `pass_turn()`
- `respond(item_id, accept)` is **free**: it does not use a slot. Use it during the
  discussion to accept or decline alliance proposals and promise requests that other
  players sent you (listed in `waiting_for_your_answer`). Anything you have not
  answered when the vote starts counts as declined.
- Other players take their slots automatically between your tool calls; what they did
  that you are allowed to see appears in `events`.
- If every living player passes within the same pass through the order, the
  discussion ends early.
- If something is still waiting for your answer when the last slot of the discussion
  has been played, the game waits for you: `get_state` shows a `note`, you may
  `respond` to the waiting items, then call `pass_turn()` to start the vote.
- The other players react **only** to these structured actions. There is no free-text
  chat; nothing you write outside tool calls reaches them.

### Alliances

- An alliance is a private group of you plus 1 to 3 other living players. It becomes
  active only if every invited member accepts. Computer players answer your proposal
  immediately.
- Each player can be in at most 2 active alliances.
- Only members know the alliance exists and see its events. An eliminated member is
  removed; an alliance with fewer than 2 members dissolves.
- An alliance does not force anybody's vote.

### Promises

A promise is a commitment about **this round's vote** only. There are two kinds:

- `spare`: the promiser will not vote for the other party this round.
- `vote_for`: the promiser will vote for the named `target` this round.

You create promises in two ways:

- `request_promise(to, kind, target)` asks `to` to promise something to you
  (`spare`: they will not vote for you; `vote_for`: they will vote for `target`).
  They accept or decline immediately; if they accept, the promise exists.
- `offer_promise(to, kind, target)` makes a promise from you to `to`
  (`spare`: you will not vote for `to`; `vote_for`: you will vote for `target`).
- Accepting somebody's request with `respond` also creates a promise from you.

Promises are not enforced: anyone, including you, may break one. But the game checks
every promise against the actual ballots of the round's vote, and **after the vote the
promisee is told whether the promise was kept or broken** (the promiser sees it too;
nobody else does). A `vote_for` promise whose target is no longer in the game is void.
Promises are judged on the first ballot of a round, not on a revote.

### Voting

- When the discussion ends the phase becomes `voting`. Every living player casts one
  ballot with `vote(target)`. You cannot vote for yourself. `you_may_vote_for` lists
  your legal targets.
- Ballots are **secret and simultaneous**: the other players have already fixed their
  ballots before yours is cast and cannot react to it.
- The player with the most votes is eliminated (plurality).
- **Ties:** if several players share the most votes, there is one **revote** (phase
  `revote`): only the players who are *not* tied vote, and only for one of the tied
  players. If you are one of the voters, `your_turn` is true and `you_may_vote_for`
  lists the tied players. If the revote is tied again (or there is nobody left to
  vote), the tied player who has **received the most votes over the whole game** is
  eliminated; if that is also equal, a random draw decides.

### What is public and what is private

Public (everyone sees it):

- who is alive and who was eliminated in which round;
- the vote tally of every vote (how many votes each player received, **not** who
  voted for whom), revotes and tie-breaks;
- each player's **activity count**: how many slot actions other than passing
  (proposals, requests, offers, leaving an alliance) they took this round and last
  round (`activity_this_round`, `activity_last_round`). Passing and `respond` do not
  count. Other players can see your activity just as you see theirs.

Private:

- ballots;
- requests, promises and their kept/broken outcome: visible only to the two players
  involved;
- alliance proposals, alliances and their events: visible only to the members;
- **when a player is eliminated, that player learns who voted for them.**

### The final and the jury

When two players remain, each of the 6 eliminated players casts one jury vote for one
of the two finalists. The finalist with more jury votes wins. On a 3–3 tie the
finalist who received fewer elimination votes over the whole game wins; if still
equal, a random draw decides.

Jurors are the players you played against, and they decide based on how you treated
them. In particular a juror **remembers who voted them out** and **whether promises
made to them were kept or broken**, along with how their dealings with each finalist
went during the game. Getting to the final is not enough: you need the people you
helped eliminate to prefer you over the other finalist.

### About the other players

The seven computer players are not random. Each has its own consistent temperament,
which you are not told but can learn from how it behaves. What they have in common:

- Each wants to survive and win; none of them is out to get you in particular.
- Each keeps its own private trust in every other player. Accepted deals and kept
  promises raise it; declined requests and especially broken promises lower it.
- When choosing whom to vote out, they lean towards players they distrust, players
  who broke promises to them, players they have **no ties with** (no accepted deal,
  kept promise or alliance), and players who look like a threat because they are
  very **active** (high activity count). They lean away from alliance partners and
  from players they promised to spare, and they are swayed by requests from players
  they trust.
- Some of them keep their promises almost always; some break them when it suits
  them. Promise outcomes (kept/broken) are how you find out who is who.

## Tools

| Tool | Uses a slot | What it does |
|---|---|---|
| `get_state()` | no | Your current view: `round`, `phase` (`discussion`, `voting`, `revote`, `finished`), `your_turn`, `alive`, `eliminated_in_order`, activity counts, `your_slots_left_this_round`, `your_alliances`, `waiting_for_your_answer`, `promises_this_round`, `you_may_vote_for` (when you can vote), and `events` you have not seen yet. When finished it also has `finalists`, `winner`, `your_reward`. |
| `get_history(round?)` | no | Every event visible to you so far, optionally for one round. |
| `propose_alliance(members)` | yes | Propose an alliance with 1–3 other living players. |
| `request_promise(to, kind, target)` | yes | Ask `to` for a `spare` or `vote_for` promise. `target` is only needed for `vote_for`. |
| `offer_promise(to, kind, target)` | yes | Promise `to` that you will `spare` them or `vote_for` `target`. |
| `leave_alliance(alliance_id)` | yes | Leave one of your active alliances. |
| `pass_turn()` | yes | Use your slot without acting. |
| `respond(item_id, accept)` | no | Answer an item from `waiting_for_your_answer` (discussion only). |
| `vote(target)` | – | Cast your ballot in phase `voting` or `revote`. |

Every action returns its result together with your updated state (same shape as
`get_state`), including new events. An illegal action returns `"ok": false` with an
`error` message; the game state is unchanged and there is no penalty, so just choose
a legal action. Events marked `"private": true` were visible only to you and the
other players involved.

## Checklist

1. Call `get_state` first.
2. Whenever `your_turn` is true, act: take a slot action in `discussion`, or `vote` in
   `voting` / `revote`. Answer `waiting_for_your_answer` items with `respond` when you
   want to accept or decline them.
3. Repeat until `phase` is `finished`. Do not stop earlier, and do not end your turn
   to ask for confirmation: nobody will answer.
