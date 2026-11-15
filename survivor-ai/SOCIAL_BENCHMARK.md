# Survivor social reasoning benchmark

## Research goal

Measure whether an agent can build and use a reliable social model while pursuing
its own goals in a changing group. The benchmark should support research on four
related capabilities:

1. **Belief tracking:** infer what each player knows, believes, and has committed to;
   distinguish public information from private messages and track who has seen what.
2. **Trust calibration:** decide whom to rely on, update trust after promises are kept
   or broken, and avoid both indiscriminate trust and blanket distrust.
3. **Negotiation:** make and respond to offers, find mutually acceptable agreements,
   protect one's own position, and honor commitments when the strategic situation shifts.
4. **Persuasion:** change another player's intentions with credible proposals, evidence,
   and relationship management rather than relying on a mechanical vote bonus.

The overall game reward remains useful, but it is not sufficient by itself. Each
capability needs at least one diagnostic outcome so a low score can be explained.

## Design principles

- **Strategic NPCs with private goals.** Give each NPC a stable objective, reservation
  value, reliability profile, and limited private information. Their decisions should
  follow those rules and be reproducible from the seed.
- **Messages carry information, not automatic influence.** Support public group chat
  and private messages with strict visibility. A message may contain a proposal or
  evidence, but does not directly add votes. Recipients respond based on their goals,
  trust, and beliefs.
- **Track knowledge boundaries.** Log who sent, received, and observed each item.
  NPCs and the evaluated agent must not access private messages addressed to others.
- **Make commitments consequential.** Negotiated agreements should be explicit,
  time-bounded, and scored as kept, broken, or superseded by a clearly defined rule.
- **Keep scenarios paired and reproducible.** Use the same seed and NPC objectives
  while changing one condition at a time, such as public-only versus public-plus-private
  communication, or reliable versus deceptive counterparts.
- **Separate capability from luck.** Report multi-seed averages and outcome variation,
  alongside diagnostic metrics and representative trajectories. Avoid tuning to a small
  fixed seed set.

## Initial scenario suite

Start with small, controlled scenarios inside the Survivor game rather than giving all
seven NPCs live LLMs immediately:

| Scenario | Controlled challenge | Primary evidence |
|---|---|---|
| Public negotiation | Several players share incentives but have different reservation values | Agreement rate, joint utility, evaluated player's utility |
| Private information | Players receive different facts about a threat or coalition | Correct inferences, leakage, decisions based on who knows each fact |
| Reliability calibration | NPCs have seeded high, mixed, or low commitment reliability | Reliance on reliable players; trust updates after observed outcomes |
| Persuasion under conflict | A proposal benefits one recipient but imposes a cost on another | Recipient response and whether the agent adapts its argument or offer |
| Deception and verification | Some NPC claims conflict with observable evidence or later actions | False-claim detection, evidence seeking, and avoidable broken agreements |

For each scenario, create paired variants that isolate one factor. Keep NPC policies
deterministic for the first benchmark version; later, add an optional LLM-opponent
track with fixed model, prompt, sampling settings, and recorded outputs.

## Measurements

- **Belief tracking:** accuracy of decisions that depend on private/public knowledge;
  where practical, add occasional low-cost belief probes with known answers and score
  them with a proper scoring rule.
- **Trust calibration:** relationship between an NPC's demonstrated reliability and
  the agent's willingness to rely on it; test both recovery after a kept commitment and
  reduced reliance after a broken one.
- **Negotiation:** individual utility, joint utility, agreement durability, and whether
  offers respect each side's reservation value.
- **Persuasion:** change in a counterpart's stated or observed position after an
  evidence-backed proposal, compared with a matched no-message or generic-message case.
- **Integrity:** passive and stop-early baselines, spam attempts, false-message
  strategies, and verifier isolation must not earn comparable rewards to competent play.

Use the official Survivor reward as an end-to-end outcome, but publish these diagnostics
next to it. A representative trace should show the private knowledge and commitments
available to each player, the evaluated agent's relevant choices, and how those choices
changed the final coalition and outcome.

## Prototype decisions

The current engine prototype adds one public and one private message per player per
round and records audience visibility. Keep those useful limits and logs. Rework the
prototype's explicit `vote_target` signal before benchmarking: it currently gives
message content a direct, deterministic ballot influence. Replace it with proposals
or offers that NPCs may accept or reject using their goals, reservation values, trust,
and information. The message itself should persuade through those decisions, not act
as a hidden vote multiplier.

## Milestones

1. Define a small NPC goal/reservation-value schema and the first paired negotiation
   and trust-calibration scenarios.
2. Replace direct vote-target influence with recipient-side proposal/offer decisions;
   preserve public/private visibility and a complete auditable event log.
3. Add capability diagnostics and integrity baselines to the verifier.
4. Compare the existing environment and prototype across capable agents and fresh
   seeds. Keep the prototype only if outcomes are repeatable, interpretable, and hard
   to game.
5. After the deterministic version is useful, add an opt-in LLM-opponent track and
   measure how its results vary across fixed model configurations.
