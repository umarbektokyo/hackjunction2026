# Break the Agent

**By:** AfterQuery · **Type:** Main challenge · **Track:** Agentic AI Track · **Tags:** AI

**Page:** https://hackjunction.app/participate/45/challenges/328 · **Website:** https://www.afterquery.com/

Build a reinforcement learning environment that challenges today's best AI agents, demonstrate real failure modes, and show that its rewards reflect real progress.

## Introduction
Today's cutting-edge AI systems can solve Millennium Problems, discover new drugs, and create entire production apps with a few lines of prompting. But they still struggle in a wide variety of novel situations, ranging from everyday use cases to niche, highly technical workflows. We ask: **what should AI agents be able to do that they still struggle with today?**

At AfterQuery, we build environments for training and testing agents. The work starts with choosing a problem worth learning, defining an action and observation space, and defining a reward function that defines what success looks like. Getting those pieces right is a heavy research and engineering problem in itself.

For this challenge, we want to see your take on it. Build a world with something interesting to learn. Find out where strong agents struggle, and whether your reward actually encourages the behavior you intended.

## The challenge
Choose a setting you find interesting and **build an environment an agent can interact with**. It could be a game, a scientific simulation, a software task, a real-world process, or something we haven't thought of. Explain why you chose it and what an agent could learn there.

Your environment should have **a clear goal, actions the agent can take, and a reward you can check**. Run a frontier agent in it and compare the results with a stronger reference run your team can demonstrate and reproduce. We'll provide the agent harness and model credits.

Show **where the agent falls short and why**. The challenge should come from the decisions it needs to make, with access to the information and tools needed to succeed. We'll also try to find shortcuts that earn a high score without completing the task: **reward hacking**.

The setting and approach are yours to choose. We care about what makes the environment useful for learning and what your experiments reveal.

### Optional stretch goal
Train a smaller model using experience from your environment and show whether it improves.

### Prizes
The top three teams receive €3,000, €1,500 and €500 in cash. Members of the winning teams can go straight to the final stage of AfterQuery's interview process: a work trial with our environments team, when they're ready. Finalists also receive AfterQuery gear.

How we judge: We'll look at four things: how much room there is for the agent to improve, whether its mistakes come from meaningful challenges, how well the reward holds up to exploits, and how well the environment is built and the results can be reproduced.

### Judging rubric 
**• The gap (30 p)** – Full points: the frontier agent consistently scores below a stronger reference run your team demonstrates; both results can be reproduced across repeated runs. Zero points: no measurable gap, or the claimed gap cannot be reproduced or checked against a demonstrated reference run.
**• Meaningful difficulty (30 p)** – Full points: you can explain the agent's main mistakes and connect them to decisions in the task; the information and tools needed to do better are available to it. Zero points: the gap comes from unfairly withheld information, trick wording, impossible timing, or broken tools.
**• Reward integrity (25 p)** – Full points: the reward measures success at the task and holds up when judges try to exploit it; doing nothing or stopping early earns little or no credit; completing the task well remains the best way to score. Zero points: an exploit, scoring loophole, or strategy that avoids the task earns a better score than successful play.
**• Craft (15 p)** – Full points: the environment's rules and behavior make sense for the setting; judges can run the evaluation from your README with one command and reproduce your reported results. Zero points: the environment only works in your demo, or judges cannot reproduce the evaluation.

**How judging runs:** Each team gets a 10-minute demo. Judges then rerun the evaluation with the standard harness: your reference run, three agent runs, a do-nothing baseline, and a stop-early baseline. They also spend 15 minutes looking for reward exploits. Scores are based on these runs.

**Tiebreaker:** If point totals are close, we'll favor a team that shows a smaller model improving after training on experience from its environment.

## Insight

### Starting points
- Planning several steps ahead
- Exploring an unfamiliar system
- Using tools
- Managing limited resources
- Adapting when new information arrives

These are prompts, not a list of required features.

**A small environment with a well-chosen challenge can be enough.** Think about what better play looks like, how you would measure it, and whether an agent could increase its score without getting better at the task.

## Resources

## What we'll bring
An open-source agent harness – **Harbor running the OpenCode agent** – that connects to your environment over **MCP**, a scoring skeleton, and frontier model API credits for each team to benchmark throughout the 48 hours.

- **Open-source agent harness:** Harbor + OpenCode
- **Scoring skeleton**
- **Frontier model API credits** per team
- **On-site mentors** for environment design reviews and reward testing
- **Starter kit:** harness documentation and the judging rubric

## Mentors
**Daksh Raghuwanshi** and **Ved Vedere** from AfterQuery's environments team, on site all weekend. They build RL environments and agent evaluations for frontier AI labs.

## Judging criteria

- **The gap** (30%) – Full points: the frontier agent consistently scores below a stronger reference run your team demonstrates; both results can be reproduced across repeated runs. Zero points: no measurable gap, or the c
- **Meaningful difficulty** (30%) – Full points: you can explain the agent's main mistakes and connect them to decisions in the task; the information and tools needed to do better are available to it. Zero points: the gap comes from unf
- **Reward Integrity** (25%) – Full points: the reward measures success at the task and holds up when judges try to exploit it; doing nothing or stopping early earns little or no credit; completing the task well remains the best wa
- **Craft** (15%) – Full points: the environment's rules and behavior make sense for the setting; judges can run the evaluation from your README with one command and reproduce your reported results. Zero points: the envi

## Prizes

- **1st Place:** 3,000€ + A work trial at AfterQuery + Merch
- **2nd Place:** 1,500€ + Merch
- **3rd Place:** 500€
