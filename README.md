# hackjunction2026
All the projects from HackJunction2026

Junction 2026, Hype Areena, Espoo, Finland, 13–15 November 2026.

## Current drafts

| Draft | Challenge | Partner |
|---|---|---|
| Evil Club 1 | Break the Agent: agents working with copies of themselves ([direction](#our-break-the-agent-direction-agents-working-with-copies-of-themselves)) | AfterQuery |
| Evil Club 2 | Spread | Bahn Express ([strategy](spread/STRATEGY.md), [working notes](spread/NOTES.md)) |

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

## Our Break the Agent direction: agents working with copies of themselves

**Premise:** agents are trained to work alone. Put several copies of the same model on one task where none of them can finish alone, and they collaborate badly. They duplicate work, overwrite each other and assume a teammate already knows what they know. Because the teammate is the same model, it "feels" like shared context, but it isn't. The benchmark measures that gap.

**Scope for now:** every team member is the same model. Mixed teams (a weaker or stronger model as a teammate) come later and reuse the same environment.

> Full build plan: [break-the-agent/PLAN.md](break-the-agent/PLAN.md). It replaces the earlier "Unreliable Informants" idea and keeps its Harbor + Docker layout, signed log, replay-based verifier and baselines.

### The setup
- **Team:** the agent under test (Harbor's `main` container, run through OpenCode) plus 1–2 copies of the same model. The copies run as extra services in the task's `docker-compose.yaml`.
- **Split ownership:** each agent sees a different part of the task (spec, logs, data) and may only write to its own files or tools. No single agent has everything it needs, so collaboration is required, not optional. Together the team has all the information and tools, so nothing is withheld.
- **Channel:** agents talk only through a message-board tool on our MCP sidecar. The sidecar logs every message, edit and tool call to a signed log that the agents can't write to.
- **Task family:** small, seeded engineering tasks with hidden tests, such as fixing a bug that spans two agents' modules or implementing a feature whose spec is split between agents.

### What we measure
| Axis | How |
|---|---|
| Success | Share of hidden tests passing, from the verifier |
| Cost-efficiency | Tokens and messages spent by the whole team |
| Speed | Simulated steps until submission (counted in operations, not wall-clock, so latency doesn't matter) |
| Reliability | Same seed across 3 runs: does the team succeed every time? |

### Reward (per episode, 0..1)
- Correctness: hidden-test pass rate, computed by replaying the logged actions.
- A capped penalty for cost and steps, always worth less than one solved part, so doing the task well beats being cheap.
- Nothing submitted, or an early stop, scores 0. That covers the do-nothing and stop-early baselines.
- Writes outside an agent's own files are rejected by the sidecar, and the logs are HMAC-signed, so nobody can fake progress.

### Failure modes we expect (the 30 "meaningful difficulty" points)
- **Shared-mind illusion:** an agent assumes its copy already knows its half of the spec and never sends it.
- **Duplicated work:** two copies solve the same sub-problem while another goes untouched.
- **Overwrite or conflict:** incompatible changes to a shared interface.
- **Blind trust:** accepting a teammate's "done" without checking it against its own part of the spec.
- **Chatter:** spending a large share of the budget on messages that carry no information.

### Reference run
A scripted team (or the same model with a fixed coordination protocol: split the work, agree on interfaces, hand off, verify) that reliably solves each seed. It must beat the free-form team by a clear and reproducible margin.

### Open questions (ask AfterQuery mentors Saturday)
- Is it acceptable for teammates to be extra model processes inside the environment, using the same model and credits as the agent under test?
- Teammates run on an LLM, so results vary. Fixed seeds plus temperature 0 may not be enough. Report pass rate across k runs and check that the gap holds across all of them.
- Is a scripted team acceptable as the "stronger reference run"?

### Later
- Mixed teams: the same tasks with a weaker or stronger teammate.
- Tiebreaker: train a small model on the reference team's trajectories and show that it collaborates better.

## Checklist for any AfterQuery entry

- [ ] Fixed seeds, so every run can be reproduced
- [ ] One command (e.g. `make eval`) runs the reference, 3 agent runs, the do-nothing baseline and the stop-early baseline, and writes a results table
- [ ] Do-nothing and stop-early score close to zero
- [ ] Your own exploit attempts written up, each with the fix
- [ ] Agent failures sorted into categories and linked to decisions in the task
- [ ] Optional: a small model trained on reference-run trajectories that improves in the environment

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
