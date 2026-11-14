# hackjunction2026
All the projects from HackJunction2026

Junction 2026, Hype Areena, Espoo, Finland, 13–15 November 2026.

## Current drafts

| Draft | Challenge | Partner |
|---|---|---|
| Evil Club 1 | Break the Agent | AfterQuery |
| Evil Club 2 | Spread | Bahn Express ([strategy](spread/STRATEGY.md), [working notes](spread/NOTES.md)) |
| Evil Club 3 | Earned Trust in AI Code | Tieto ([concept card](earned-trust/CONCEPT.md), [README](earned-trust/README.md), [reports](earned-trust/reports/)) |

## AfterQuery: Break the Agent

Build a reinforcement learning (RL) environment where today's best AI agents fall short. The task needs a clear goal, actions the agent can take and a reward that can be checked. Run a frontier agent in it and compare the results with a stronger reference run that your team demonstrates and can reproduce. AfterQuery provides the agent harness and model credits.

**Prizes:** €3,000 plus a work trial at AfterQuery and merch for 1st place, €1,500 plus merch for 2nd, €500 for 3rd.

**Judging rubric**

| Criterion | Points | Full points when |
|---|---|---|
| The gap | 30 | The frontier agent consistently scores below your reference run, and both results reproduce across repeated runs |
| Meaningful difficulty | 30 | You can explain the agent's mistakes and tie them to decisions in the task. The agent had the information and tools it needed. No trick wording, withheld information, impossible timing or broken tools |
| Reward integrity | 25 | Doing nothing or stopping early earns little or no credit. Judges' attempts to exploit the reward fail. Doing the task well is the best way to score |
| Craft | 15 | The rules make sense for the setting. Judges can reproduce your results from the README with one command |

**How judging runs:** each team gives a 10-minute demo. Judges then rerun the evaluation with the standard harness: your reference run, 3 agent runs, a do-nothing baseline and a stop-early baseline. They also spend 15 minutes looking for reward exploits.

**Tiebreaker:** if scores are close, they favour a team that shows a smaller model improving after training on experience from its environment. This is also AfterQuery's optional stretch goal.

## Bahn Express: Spread (key facts)

- Run a simulated car-transport company for a week in Finland. Quote prices to dealers, who also ask a competitor for a price. When you win a car, post the drive as a gig for freelance drivers and set the driver's fee.
- **Score:** gross margin, meaning what dealers pay you minus what you pay drivers. At least 90% of cars must arrive by their deadline.
- **Join:** create your team at `spread.bahnexpress.com/join` with event code `spread-kmu9z6`. The handbook, rules, API reference, TypeScript and Python kits and the leaderboard are all on that site. Give your agent `spread.bahnexpress.com/llms.txt`.
- **Schedule:** ranking rounds open Friday at 19:30. Registration for the final closes Sunday at 07:30, and the final starts at 08:00 (one secret week, about 34 minutes). The 10 teams with the highest margin pitch to the jury, which judges the system's elegance, clarity, creativity and robustness.
- **Prizes:** €2,000, €1,000 and €500.

## Option A: one simulator for both challenges

Build a local simulator based on the Spread handbook. Your Spread bot doubles as AfterQuery's reference run.

**For**
- **Shared work.** A local simulator lets you test the Spread bot without waiting for ranking rounds. The simulator and the bot are also about half the AfterQuery entry (the environment and the reference run).
- **The difficulty is real.** The hard part isn't arithmetic. The agent has to learn while it plays: how the competitor prices, how drivers respond to fees, and when to try new prices versus use what works. That's a classic RL problem and a solid case for "meaningful difficulty".
- **A large, reproducible gap is likely.** A tuned bot should reliably beat an LLM agent, and fixed seeds make every week replay the same way.
- **A strong reward to start from.** Margin with a 90% on-time rule gives zero for doing nothing and blocks the "accept every job" cheat.

**Against**
- The world comes from another partner. "Why this setting?" opens the demo, and "we copied another partner's challenge" is a weak answer.
- Other teams may port Spread too.
- How good it looks depends on how well your own simulator is built.

**If you choose it**
- Design your own models of drivers and the competitor. The handbook probably doesn't reveal them, and designing them makes the world yours.
- Frame the agent's failures as "it can't learn the market", not "it can't do maths".
- Check Junction's rules on entering one project in several challenges and on partners owning the work. Also ask Bahn at their booth whether they mind you copying their world.

## Option B: a separate AfterQuery environment

### Hidden-law lab
The agent runs experiments on a simulated system governed by rules it can't see, for example a made-up chemistry or an ecosystem. Each experiment costs budget. At the end it predicts outcomes for test cases it never saw.

- **Reward:** prediction accuracy minus experiment cost. The test cases are hidden, so the reward is hard to exploit.
- **Typical agent failures:** sticking with the first hypothesis, running experiments that can't tell two hypotheses apart, and stopping too early.
- **Reference run:** a Bayesian experiment-design solver that picks the most informative experiment each step.
- **Risks:**
  - "Discover the hidden rules" is a fairly common benchmark genre.
  - Judges could mark the gap down as "withheld information" unless the agent is told what kinds of rules are possible.
  - Frontier models with code tools may do well in simple worlds, so getting a clear gap may take tuning.
  - You build everything from scratch.

### Other ideas
- **On-call incident environment:** a simulated set of services with one injected fault. The agent investigates logs, metrics and traces, then restarts or rolls back services. It scores only if the simulator confirms the fix worked.
- **Rules-maze bureaucracy:** a permit or benefits process with many interacting rules. The agent has to finish the paperwork in a valid order. Reward is easy to check, and it tests tracking state over many steps.
- **Tieto's code-review challenge as an environment:** the agent reviews AI-written pull requests with planted bugs. It earns points for real catches and loses points for false alarms. Uses the branches Tieto provides.
- **Valio Aimo's purchasing challenge as an environment:** the agent orders within its approval limits. "Send everything to a human for approval" is a lazy baseline that should score low.

## Recommendation

- **If the goal is the most prize money for your hours:** Option A, with your own driver and competitor models, after checking the rules.
- **If the goal is to stand out to AfterQuery** (the work trial, an original project): Option B. Pick the environment because it shows a failure that matters, not because it's quick.

Still to decide: what "nobility" means for the team, originality or real-world usefulness.

## Checklist for any AfterQuery entry

- [ ] Fixed seeds, so every run can be reproduced
- [ ] One command (e.g. `make eval`) runs the reference, 3 agent runs, the do-nothing baseline and the stop-early baseline, and writes a results table
- [ ] Do-nothing and stop-early score close to zero
- [ ] Your own exploit attempts written up, each with the fix
- [ ] Agent failures sorted into categories and linked to decisions in the task
- [ ] Optional: a small model trained on reference-run trajectories that improves in the environment

## Tieto: Earned Trust in AI Code (key facts)

- Design an AI code-review concept for agent-written changes and show it on Tieto's sample repo (`te-industry-tech-office/junction26-messagepack-csharp`, branches `ju26-issue-2283/2234/2129/2297`). Concept weighs more than code; it is a reference implementation, not a product.
- **Deliverables:** concept card (recommendation, principles, trade-offs, limits), live walkthrough showing where trust comes from, lessons log, demo video or presentation.
- **Judging:** clarity 30%, practicality 25%, measurement 25% (reverts and incidents don't rise as review time falls; AI findings accepted; time to merge; share routed to humans), evidence 20% (a named human can accept without a full read; what the AI found, what it refused to decide, and why).
- **Prizes:** €2,000, €1,000, €500. Only 25 preliminary submissions, the fewest of the software challenges.
- Our entry: `earned-trust/` — claims → evidence → verdict review (`cev`). Picked because it needs no partner credentials, and the agent branches contain real over-promises to find (e.g. branch 2234 adds tests and a README section for analyzer behaviour the base branch already had; its only code change is a duplicate-key crash guard).

## Other prize pools (Agentic AI track)

| Partner | Challenge | 1st prize |
|---|---|---|
| Valio Aimo | Trusted Trade Agents | €4,000 |
| AfterQuery | Break the Agent | €3,000 + work trial |
| Exa | The Internet Butler | $2,500 + $5k credits |
| Hostinger | Decode the Noise (must run live on Hostinger) | €2,000 |
| Tieto | Earned Trust in AI Code | €2,000 |
| Bahn Express | Spread | €2,000 |
| Cala | Make Unicorns Real | 3 hackathon trips (~€5k) + €1k credits |

Full list: https://hackjunction.app/participate/45/challenges
